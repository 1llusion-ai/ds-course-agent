"""Probe predicted learner obligations without exposing gold learner labels."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from benchmarks.knowledge_state_search.controlled_profiles import controlled_profiles
from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.model_retry import is_retryable_status, retry_delay
from benchmarks.knowledge_state_search.models import EvidenceGap, EvidenceRequirement, SearchTask, StudentProfile
from benchmarks.knowledge_state_search.prompt_probe import (
    _accumulate_usage,
    _core_gap,
    _request,
    _telemetry,
)

DEFAULT_DATA = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/predicted_gap_probe_v1.json")
DEFAULT_BASE_URL = "http://model.mify.ai.srv/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"

PREDICTOR_SYSTEM_PROMPT = """你是一个数据科学课程的 learner-evidence obligation predictor。
你只能根据问题、所有方法共享的核心证据契约和学生画像，预测当前学生额外需要的教学证据。
不要输出最终答案，不要输出隐藏思维链，不要使用 requirement_id、gold label 或外部搜索。
只输出 JSON：
{
  "obligations": [
    {
      "kind": "prerequisite|misconception|goal",
      "concept": "概念或学习目标",
      "claim": "当前学生需要补充的可验证证据主张",
      "search_terms": ["English search phrase"],
      "trigger": {
        "field": "weak_concept|misconception|learning_goal",
        "value": "触发该 obligation 的画像事实"
      },
      "priority": 1
    }
  ]
}
最多输出 2 条 obligation；如果学生没有 weak_concepts、misconceptions，
且 learning_goal 没有明确要求额外深度，必须输出空列表。
当 learning_goal 为空、仅为“理解算法原理”或“理解评估曲线”等通用目标时，
不得输出 kind=goal；如果 learning_goal 明确要求比较、阈值选择、业务决策、
公式推导、直观例子或应用等额外证据维度，可以输出 kind=goal。
同一个 learning_goal trigger 最多输出 1 条 kind=goal obligation；
不要把一个学习目标拆成多个证明步骤或互相重叠的数学子主张。
不要把所有学生都需要的核心事实重复输出为 learner obligation。
每条 obligation 至少提供 1 个英文 search_terms，不得使用中文 search term。
"""


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(raw[start : end + 1])


def build_predictor_prompt(task: SearchTask, profile: StudentProfile) -> str:
    """Build a predictor prompt that excludes gold learner requirements."""

    core = _core_gap(task)
    profile_view = {
        "level": profile.level,
        "mastered_concepts": list(profile.mastered_concepts),
        "weak_concepts": list(profile.weak_concepts),
        "misconceptions": list(profile.misconceptions),
        "learning_goal": profile.learning_goal,
    }
    return f"""问题：
{task.question}

所有方法共享的核心证据契约：
{json.dumps(core.to_dict(), ensure_ascii=False, indent=2)}

学生画像：
{json.dumps(profile_view, ensure_ascii=False, indent=2)}

请只预测该学生额外需要的 learner evidence obligations。
"""


def _validate_prediction(payload: dict[str, Any]) -> str | None:
    obligations = payload.get("obligations")
    if not isinstance(obligations, list) or len(obligations) > 2:
        return "obligations must be a list of at most 2 items"
    allowed = {"prerequisite", "misconception", "goal"}
    goal_triggers: set[str] = set()
    for index, item in enumerate(obligations):
        if not isinstance(item, dict):
            return f"obligations[{index}] must be an object"
        if str(item.get("kind", "")) not in allowed:
            return f"obligations[{index}] has invalid kind"
        if not str(item.get("concept", "")).strip() or not str(item.get("claim", "")).strip():
            return f"obligations[{index}] requires concept and claim"
        search_terms = item.get("search_terms", [])
        if not isinstance(search_terms, list) or not search_terms:
            return f"obligations[{index}].search_terms must be a non-empty list"
        if any(
            not str(term).strip() or re.search(r"[\u4e00-\u9fff]", str(term)) or not re.search(r"[A-Za-z]", str(term))
            for term in search_terms
        ):
            return f"obligations[{index}].search_terms must be English"
        trigger = item.get("trigger")
        if not isinstance(trigger, dict) or trigger.get("field") not in {
            "weak_concept",
            "misconception",
            "learning_goal",
        }:
            return f"obligations[{index}] requires a valid trigger field"
        if not str(trigger.get("value", "")).strip():
            return f"obligations[{index}] requires a non-empty trigger value"
        if "requirement_id" in item:
            return f"obligations[{index}] must not contain requirement_id"
        if str(item.get("kind", "")) == "goal" and trigger.get("field") != "learning_goal":
            return f"obligations[{index}] goal requires a learning_goal trigger"
        if str(item.get("kind", "")) == "goal":
            trigger_key = str(trigger.get("value", "")).strip()
            if trigger_key in goal_triggers:
                return f"obligations[{index}] duplicates a learning_goal obligation"
            goal_triggers.add(trigger_key)
    return None


def _validate_prediction_for_profile(
    payload: dict[str, Any],
    profile: StudentProfile,
    *,
    neutral_learning_goal: str | None = None,
) -> str | None:
    """Reject obligations whose claimed trigger is absent from the profile."""

    generic_goals = {"", "理解算法原理", "理解评估曲线", "understand", "understand algorithm"}
    for index, item in enumerate(payload.get("obligations", [])):
        trigger = item.get("trigger") or {}
        field = trigger.get("field")
        trigger_value = str(trigger.get("value", ""))
        if field == "weak_concept" and trigger_value not in profile.weak_concepts:
            return f"obligations[{index}] weak trigger does not match profile"
        if field == "misconception" and trigger_value not in profile.misconceptions:
            return f"obligations[{index}] misconception trigger does not match profile"
        if field != "learning_goal":
            continue
        if item.get("kind") != "goal":
            return f"obligations[{index}] learning_goal trigger requires goal kind"
        if trigger_value != profile.learning_goal:
            return f"obligations[{index}] goal trigger does not match profile"
        if neutral_learning_goal is not None:
            if profile.learning_goal == neutral_learning_goal:
                return f"obligations[{index}] neutral learning goal cannot trigger learner evidence"
        elif profile.learning_goal.strip().lower() in generic_goals:
            return f"obligations[{index}] generic learning goal cannot trigger learner evidence"
    return None


def _coalesce_goal_obligations(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep one goal obligation per learning-goal trigger without gold labels."""

    obligations = payload.get("obligations")
    if not isinstance(obligations, list):
        return payload
    normalized: list[Any] = []
    seen_goal_triggers: set[tuple[str, str]] = set()
    for item in obligations:
        if not isinstance(item, dict) or item.get("kind") != "goal":
            normalized.append(item)
            continue
        trigger = item.get("trigger")
        if not isinstance(trigger, dict):
            normalized.append(item)
            continue
        trigger_key = (str(trigger.get("field", "")), str(trigger.get("value", "")).strip())
        if trigger_key in seen_goal_triggers:
            continue
        seen_goal_triggers.add(trigger_key)
        normalized.append(item)
    return {**payload, "obligations": normalized}


def _is_retryable_status(status_code: int) -> bool:
    """Return whether an HTTP failure may succeed after backoff."""

    return is_retryable_status(status_code)


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Choose a bounded delay, honoring a server-provided Retry-After value."""

    return retry_delay(
        status_code=response.status_code if response is not None else None,
        retry_after=response.headers.get("Retry-After") if response is not None else None,
        attempt=attempt,
    )


def predict_obligations(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    timeout: float,
    max_retries: int,
    neutral_learning_goal: str | None = None,
) -> dict[str, Any]:
    """Predict learner obligations without providing gold learner requirements."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": PREDICTOR_SYSTEM_PROMPT},
            {"role": "user", "content": build_predictor_prompt(task, profile)},
        ],
        "temperature": 0.0,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    url = f"{base_url.rstrip('/')}/chat/completions"
    last_error = ""
    last_response: dict[str, Any] | None = None
    total_latency = 0.0
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage_reported = False
    attempts = 0
    for attempt in range(1, max_retries + 1):
        attempts = attempt
        response: requests.Response | None = None
        started = time.perf_counter()
        try:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            total_latency += time.perf_counter() - started
            if response.ok:
                body = response.json()
                usage_reported = _accumulate_usage(usage_totals, body.get("usage")) or usage_reported
                content = body["choices"][0]["message"].get("content") or ""
                parsed = _coalesce_goal_obligations(_extract_json(content))
                last_response = parsed
                validation_error = _validate_prediction(parsed)
                if validation_error:
                    last_error = f"schema_invalid: {validation_error}"
                else:
                    profile_error = _validate_prediction_for_profile(
                        parsed,
                        profile,
                        neutral_learning_goal=neutral_learning_goal,
                    )
                    if profile_error:
                        last_error = f"profile_trigger_invalid: {profile_error}"
                    else:
                        return {
                            "prediction": parsed,
                            "raw_prediction": content,
                            "telemetry": _telemetry(
                                attempts=attempts,
                                latency_seconds=total_latency,
                                usage_totals=usage_totals,
                                usage_reported=usage_reported,
                            ),
                            "error": None,
                        }
            else:
                last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                if not _is_retryable_status(response.status_code):
                    break
        except Exception as exc:
            if response is None:
                total_latency += time.perf_counter() - started
            last_error = repr(exc)
        if attempt < max_retries:
            time.sleep(_retry_delay(response, attempt))
    return {
        "prediction": last_response,
        "raw_prediction": "",
        "telemetry": _telemetry(
            attempts=attempts,
            latency_seconds=total_latency,
            usage_totals=usage_totals,
            usage_reported=usage_reported,
        ),
        "error": last_error or "prediction failed",
    }


def predicted_gap(task: SearchTask, prediction: dict[str, Any]) -> EvidenceGap:
    """Convert free-form predicted obligations into planner-visible typed requirements."""

    items: list[EvidenceRequirement] = []
    for index, raw in enumerate(prediction.get("obligations", []), 1):
        items.append(
            EvidenceRequirement(
                requirement_id=f"predicted_{index:02d}",
                kind=raw["kind"],
                concept=str(raw["concept"]),
                description=str(raw["claim"]),
                search_terms=tuple(str(term) for term in raw.get("search_terms", [])),
                hard=False,
                priority=int(raw.get("priority", 1)),
            )
        )
    return EvidenceGap(
        core_requirements=_core_gap(task).core_requirements,
        learner_requirements=tuple(items),
    )


def prediction_matches_gold(
    predicted: EvidenceGap,
    gold: EvidenceGap,
) -> dict[str, Any]:
    """Use gold labels only for evaluation, never as predictor input."""

    matched: list[str] = []
    for item in predicted.learner_requirements:
        predicted_text = " ".join((item.concept, item.description, *item.search_terms)).lower().replace(" ", "")
        best = None
        for gold_item in gold.learner_requirements:
            gold_terms = [gold_item.concept, gold_item.description, *gold_item.search_terms]
            if any(term.lower().replace(" ", "") in predicted_text for term in gold_terms if term):
                best = gold_item.requirement_id
                break
        if best:
            matched.append(best)
    return {
        "predicted_count": len(predicted.learner_requirements),
        "gold_count": len(gold.learner_requirements),
        "matched_gold_ids": matched,
        "recall": len(set(matched)) / len(gold.learner_requirements) if gold.learner_requirements else None,
    }


def _load_tasks(path: Path) -> list[SearchTask]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def _run_case(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    repeat: int,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    gold = KnowledgeStateGapPlanner().plan(task, profile)
    prediction_result = predict_obligations(
        api_key=api_key,
        base_url=base_url,
        model=model,
        task=task,
        profile=profile,
        timeout=timeout,
        max_retries=max_retries,
    )
    if prediction_result["error"] or not prediction_result["prediction"]:
        return {
            "task_id": task.task_id,
            "student_id": profile.student_id,
            "repeat": repeat,
            "prediction": prediction_result,
            "planner": None,
            "gold_gap": gold.to_dict(),
            "error": prediction_result["error"],
        }

    predicted = predicted_gap(task, prediction_result["prediction"])
    planner_result = _request(
        api_key=api_key,
        base_url=base_url,
        model=model,
        task=task,
        profile=profile,
        variant="gap_planner",
        gap=predicted,
        visible_requirement_ids=tuple(item.requirement_id for item in predicted.all_requirements),
        timeout=timeout,
        max_retries=max_retries,
    )
    planner_result["evaluation_gap"] = gold.to_dict()
    planner_result["predicted_gap"] = predicted.to_dict()
    planner_result["prediction_matches"] = prediction_matches_gold(predicted, gold)
    planner_result["repeat"] = repeat
    return {
        "task_id": task.task_id,
        "student_id": profile.student_id,
        "repeat": repeat,
        "prediction": prediction_result,
        "planner": planner_result,
        "gold_gap": gold.to_dict(),
        "error": planner_result["error"],
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""

    parser = argparse.ArgumentParser(description="Probe predicted learner obligations.")
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--api-key-env", default="PROFILE_EVAL_API_KEY")
    parser.add_argument("--base-url", default=os.environ.get("PROFILE_EVAL_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", default=os.environ.get("PROFILE_EVAL_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--limit-tasks", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=2)
    return parser


def main() -> int:
    """Run the predictor/planner probe."""

    _load_env()
    args = build_parser().parse_args()
    api_key = os.environ.get(args.api_key_env) or os.environ.get("MIMO_API_KEY") or os.environ.get("JUDGE_API_KEY")
    if not api_key:
        print(f"API key not found. Set {args.api_key_env}.", file=sys.stderr)
        return 2
    tasks = _load_tasks(Path(args.data))[: max(1, args.limit_tasks)]
    jobs = [
        (task, profile, repeat)
        for task in tasks
        for profile in controlled_profiles(task)
        for repeat in range(1, max(1, args.repeats) + 1)
    ]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        futures = {
            executor.submit(
                _run_case,
                api_key=api_key,
                base_url=args.base_url,
                model=args.model,
                task=task,
                profile=profile,
                repeat=repeat,
                timeout=args.timeout,
                max_retries=args.max_retries,
            ): (task.task_id, profile.student_id, repeat)
            for task, profile, repeat in jobs
        }
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            print(
                f"[{index}/{len(futures)}] {result['task_id']} "
                f"{result['student_id']} repeat={result['repeat']} "
                f"{'ok' if result['error'] is None else 'error'}"
            )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment": "predicted_learner_obligation_probe_v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "task_count": len(tasks),
                "result_count": len(results),
                "config": {
                    "repeats": args.repeats,
                    "base_url": args.base_url.rstrip("/"),
                    "model": args.model,
                },
                "results": sorted(
                    results,
                    key=lambda item: (item["task_id"], item["student_id"], item["repeat"]),
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved {len(results)} results to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
