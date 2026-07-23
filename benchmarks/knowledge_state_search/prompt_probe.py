"""Batch prompt probe for generic, profile-prompt, and gap-planner variants."""

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

from benchmarks.knowledge_state_search.gap_planner import KnowledgeStateGapPlanner
from benchmarks.knowledge_state_search.model_retry import is_retryable_status, retry_delay
from benchmarks.knowledge_state_search.models import EvidenceGap, SearchTask, StudentProfile

DEFAULT_DATA = Path("benchmarks/data/knowledge_state_search_probe_v1.json")
DEFAULT_OUTPUT = Path("var/artifacts/knowledge_state_search/probe_v1.json")
DEFAULT_BASE_URL = "http://model.mify.ai.srv/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"
VARIANTS = (
    "generic",
    "profile_at_answer",
    "profile_prompt",
    "profile_mastery_only",
    "profile_weak_only",
    "profile_misconception_only",
    "profile_goal_only",
    "gap_planner",
    "shuffled_gap",
)
DEFAULT_VARIANTS = ("generic", "profile_at_answer", "profile_prompt", "gap_planner")

SYSTEM_PROMPT = """你是一个课程联网搜索规划器。
你的任务不是写最终答案，而是规划最多 3 个可执行的搜索动作。
只输出 JSON，不要 Markdown，不要输出隐藏思维链。

输出格式：
{
  "actions": [
    {
      "type": "SEARCH|REFINE|FINISH",
      "query": "搜索 query；FINISH 时为空",
      "purpose": "一句可验证的目的",
      "target_requirements": ["输入中给出的 requirement_id"]
    }
  ],
  "stop_reason": "为什么当前证据足够或为什么达到预算"
}

规则：
1. SEARCH/REFINE 必须有具体 query；FINISH 不得虚构 query。
2. 不要编造网页 URL；本阶段只规划搜索，不执行 FETCH。
3. 不要输出完整思维链，只输出结构化、可检查的行动理由。
4. 如果输入包含 core evidence requirements，不能因为学生已掌握某前置知识而删除核心事实证据。
"""


def _load_env() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from a strict or fenced model response."""

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


def _profile_text(profile: StudentProfile) -> str:
    """Render only explicit profile facts, avoiding hidden state conventions."""

    return json.dumps(
        {
            "level": profile.level,
            "mastered_concepts": list(profile.mastered_concepts),
            "weak_concepts": list(profile.weak_concepts),
            "misconceptions": list(profile.misconceptions),
            "learning_goal": profile.learning_goal,
        },
        ensure_ascii=False,
        indent=2,
    )


def _profile_view(profile: StudentProfile, variant: str) -> dict[str, Any]:
    """Expose exactly one profile factor for controlled field ablations."""

    fields = {
        "profile_mastery_only": {"mastered_concepts": list(profile.mastered_concepts)},
        "profile_weak_only": {"weak_concepts": list(profile.weak_concepts)},
        "profile_misconception_only": {"misconceptions": list(profile.misconceptions)},
        "profile_goal_only": {"learning_goal": profile.learning_goal},
    }
    if variant not in fields:
        raise ValueError(f"Unknown profile ablation variant: {variant}")
    return fields[variant]


def _requirements_text(gap: EvidenceGap) -> str:
    return json.dumps(gap.to_dict(), ensure_ascii=False, indent=2)


def _core_gap(task: SearchTask) -> EvidenceGap:
    """Build the shared core contract visible to every planner variant."""

    return EvidenceGap(
        core_requirements=tuple(item for item in task.evidence_requirements if item.kind == "core"),
    )


def _planner_gap(task: SearchTask, profile: StudentProfile, variant: str, gap: EvidenceGap) -> EvidenceGap:
    """Return the obligations visible to one planner variant."""

    if variant == "shuffled_gap":
        return KnowledgeStateGapPlanner().plan(task, _shuffled_profile(profile))
    if variant == "gap_planner":
        return gap
    return _core_gap(task)


def _visible_requirement_ids(
    task: SearchTask,
    profile: StudentProfile,
    *,
    variant: str,
    gap: EvidenceGap,
) -> tuple[str, ...]:
    """Return requirement IDs legally visible to a planner variant."""

    visible_gap = _planner_gap(task, profile, variant, gap)
    return tuple(item.requirement_id for item in visible_gap.all_requirements)


def _validate_plan_output(
    payload: dict[str, Any],
    visible_requirement_ids: tuple[str, ...],
    *,
    required_target_ids: tuple[str, ...] = (),
    required_query_terms: dict[str, tuple[str, ...]] | None = None,
    query_language: str = "",
) -> str | None:
    """Validate the shared planner contract before counting a result as valid."""

    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions or len(actions) > 3:
        return "actions must be a non-empty list of at most 3 items"

    visible = set(visible_requirement_ids)
    required = set(required_target_ids)
    required_terms = required_query_terms or {}
    if not required.issubset(visible):
        return "required target IDs must be visible to the planner"
    targeted: set[str] = set()
    targeted_queries: dict[str, list[str]] = {}
    valid_types = {"SEARCH", "REFINE", "FINISH"}
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            return f"actions[{index}] must be an object"
        action_type = str(action.get("type", "")).upper()
        if action_type not in valid_types:
            return f"actions[{index}] has invalid type: {action_type!r}"
        query = str(action.get("query", "")).strip()
        if action_type in {"SEARCH", "REFINE"} and not query:
            return f"actions[{index}] {action_type} requires a query"
        if action_type in {"SEARCH", "REFINE"} and query_language == "英文":
            if re.search(r"[\u4e00-\u9fff]", query) or not re.search(r"[A-Za-z]", query):
                return f"actions[{index}] query must be English"
        if action_type == "FINISH" and query:
            return f"actions[{index}] FINISH must not contain a query"
        target_ids = action.get("target_requirements", [])
        if not isinstance(target_ids, list) or any(str(item) not in visible for item in target_ids):
            return f"actions[{index}] contains requirement IDs outside planner contract"
        if action_type in {"SEARCH", "REFINE"}:
            for item in target_ids:
                target_id = str(item)
                targeted.add(target_id)
                targeted_queries.setdefault(target_id, []).append(query)
    missing = required - targeted
    if missing:
        return f"planner omitted required target IDs: {sorted(missing)}"
    for target_id in required:
        terms = required_terms.get(target_id, ())
        if terms and not any(_query_overlaps_terms(query, terms) for query in targeted_queries.get(target_id, ())):
            return f"planner query does not reflect learner search terms: {target_id}"
    return None


def _query_overlaps_terms(query: str, terms: tuple[str, ...]) -> bool:
    """Return whether a query uses at least one content token from search hints."""

    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    term_tokens = {token for term in terms for token in re.findall(r"[a-z0-9]+", term.lower()) if len(token) > 2}
    return bool(query_tokens & term_tokens)


def build_user_prompt(
    task: SearchTask,
    profile: StudentProfile,
    *,
    variant: str,
    gap: EvidenceGap,
    query_language: str = "",
    enforce_target_contract: bool = True,
) -> str:
    """Build one variant-specific planner prompt."""

    core_gap = _core_gap(task)
    base = f"""问题：
{task.question}

所有方法共享的核心证据契约：
{_requirements_text(core_gap)}
"""
    if query_language:
        base += f"\n所有 SEARCH/REFINE action 的 query 必须使用{query_language}。\n"
    if variant in {"generic", "profile_at_answer"}:
        return base + "\n请像一个不读取学生画像的通用搜索规划器一样行动。"
    if variant == "profile_prompt":
        return (
            base
            + f"""

学生画像：
{_profile_text(profile)}

请直接使用学生画像调整搜索 query、证据角度和停止时机。
"""
        )
    if variant.startswith("profile_"):
        return (
            base
            + f"""

受控学生状态字段（只允许使用这一类信息）：
{json.dumps(_profile_view(profile, variant), ensure_ascii=False, indent=2)}

请只根据这一个状态字段调整搜索 query、证据角度和停止时机；
不要猜测或补充输入中没有提供的其他学生信息。
"""
        )
    if variant in {"gap_planner", "shuffled_gap"}:
        effective_gap = _planner_gap(task, profile, variant, gap)
        target_contract = (
            "每个 learner_requirements 中的 requirement_id 都必须至少出现在一个 SEARCH/REFINE action 的\n"
            "target_requirements 中，并且对应 query 必须体现该 requirement 的英文 search_terms。"
            if enforce_target_contract
            else "target_requirements 是可选的；请根据搜索动作自行决定是否标注其覆盖的 evidence requirement。"
        )
        return (
            base
            + f"""

结构化证据义务：
{_requirements_text(effective_gap)}

请只根据这些结构化证据义务规划搜索。core_requirements 是所有学生都必须满足的事实证据；
learner_requirements 是当前学生需要的补充教学证据。不要把已满足的 prerequisite 重新当作缺口。
{target_contract}
"""
        )
    raise ValueError(f"Unknown variant: {variant}")


def _shuffled_profile(profile: StudentProfile) -> StudentProfile:
    """Create a deliberately mismatched profile for the causal control."""

    return StudentProfile(
        student_id=f"{profile.student_id}_shuffled",
        level=profile.level,
        mastered_concepts=profile.weak_concepts,
        weak_concepts=profile.mastered_concepts,
        misconceptions=(),
        learning_goal=profile.learning_goal,
    )


def _request(
    *,
    api_key: str,
    base_url: str,
    model: str,
    task: SearchTask,
    profile: StudentProfile,
    variant: str,
    gap: EvidenceGap,
    visible_requirement_ids: tuple[str, ...],
    timeout: float,
    max_retries: int,
    query_language: str = "",
    required_target_ids: tuple[str, ...] = (),
    required_query_terms: dict[str, tuple[str, ...]] | None = None,
    enforce_target_contract: bool = True,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    task,
                    profile,
                    variant=variant,
                    gap=gap,
                    query_language=query_language,
                    enforce_target_contract=enforce_target_contract,
                ),
            },
        ],
        "temperature": 0.0,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
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
                parsed = _extract_json(content)
                last_response = parsed
                validation_error = _validate_plan_output(
                    parsed,
                    visible_requirement_ids,
                    required_target_ids=required_target_ids,
                    required_query_terms=required_query_terms,
                    query_language=query_language,
                )
                if validation_error:
                    last_error = f"schema_invalid: {validation_error}"
                    if attempt < max_retries:
                        time.sleep(min(2**attempt, 8))
                        continue
                    break
                return {
                    "task_id": task.task_id,
                    "student_id": profile.student_id,
                    "variant": variant,
                    "profile": profile.to_dict(),
                    "gap": gap.to_dict(),
                    "visible_requirement_ids": list(visible_requirement_ids),
                    "request": {
                        "base_url": base_url.rstrip("/"),
                        "model": model,
                        "temperature": 0.0,
                        "target_contract_enforced": enforce_target_contract,
                    },
                    "response": parsed,
                    "raw_response": content,
                    "telemetry": _telemetry(
                        attempts=attempts,
                        latency_seconds=total_latency,
                        usage_totals=usage_totals,
                        usage_reported=usage_reported,
                    ),
                    "error": None,
                }
            last_error = f"HTTP {response.status_code}: {response.text[:500]}"
            if not is_retryable_status(response.status_code):
                break
        except Exception as exc:
            if response is None:
                total_latency += time.perf_counter() - started
            last_error = repr(exc)
        if attempt < max_retries:
            time.sleep(
                retry_delay(
                    status_code=response.status_code if response is not None else None,
                    retry_after=response.headers.get("Retry-After") if response is not None else None,
                    attempt=attempt,
                )
            )
    return {
        "task_id": task.task_id,
        "student_id": profile.student_id,
        "variant": variant,
        "profile": profile.to_dict(),
        "gap": gap.to_dict(),
        "visible_requirement_ids": list(visible_requirement_ids),
        "request": {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "temperature": 0.0,
            "target_contract_enforced": enforce_target_contract,
        },
        "response": last_response,
        "raw_response": "",
        "telemetry": _telemetry(
            attempts=attempts,
            latency_seconds=total_latency,
            usage_totals=usage_totals,
            usage_reported=usage_reported,
        ),
        "error": last_error or "unknown request failure",
    }


def _accumulate_usage(totals: dict[str, int], usage: Any) -> bool:
    """Accumulate provider token usage when the endpoint reports it."""

    if not isinstance(usage, dict):
        return False
    reported = False
    for field in totals:
        value = usage.get(field)
        if isinstance(value, int) and value >= 0:
            totals[field] += value
            reported = True
    return reported


def _telemetry(
    *,
    attempts: int,
    latency_seconds: float,
    usage_totals: dict[str, int],
    usage_reported: bool,
) -> dict[str, int | float | None]:
    """Build request telemetry without inventing token counts."""

    return {
        "attempts": attempts,
        "latency_seconds": latency_seconds,
        "prompt_tokens": usage_totals["prompt_tokens"] if usage_reported else None,
        "completion_tokens": usage_totals["completion_tokens"] if usage_reported else None,
        "total_tokens": usage_totals["total_tokens"] if usage_reported else None,
    }


def _dry_run(
    *,
    tasks: list[SearchTask],
    variants: tuple[str, ...],
    planner: KnowledgeStateGapPlanner,
) -> list[dict[str, Any]]:
    """Render prompts without making network calls."""

    results: list[dict[str, Any]] = []
    for task in tasks:
        for profile in task.profiles:
            gap = planner.plan(task, profile)
            for variant in variants:
                results.append(
                    {
                        "task_id": task.task_id,
                        "student_id": profile.student_id,
                        "variant": variant,
                        "prompt": build_user_prompt(task, profile, variant=variant, gap=gap),
                        "gap": gap.to_dict(),
                    }
                )
    return results


def _load_tasks(path: Path) -> list[SearchTask]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SearchTask.from_dict(item) for item in payload["tasks"]]


def run_probe(
    *,
    api_key: str,
    base_url: str,
    model: str,
    tasks: list[SearchTask],
    variants: tuple[str, ...],
    timeout: float,
    max_retries: int,
    concurrency: int,
) -> list[dict[str, Any]]:
    """Run the paired LLM probe with bounded concurrency."""

    planner = KnowledgeStateGapPlanner()
    jobs: list[tuple[SearchTask, StudentProfile, str, EvidenceGap]] = []
    for task in tasks:
        canonical_profile = task.profiles[0]
        canonical_gap = planner.plan(task, canonical_profile)
        if any(variant in {"generic", "profile_at_answer"} for variant in variants):
            # One shared search trajectory is reused across profiles and both
            # no-profile controls. This removes unnecessary model sampling
            # variance from the answer-only comparison.
            jobs.append((task, canonical_profile, "generic", canonical_gap))
        for variant in variants:
            if variant in {"generic", "profile_at_answer"}:
                continue
            jobs.extend((task, profile, variant, planner.plan(task, profile)) for profile in task.profiles)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = {
            executor.submit(
                _request,
                api_key=api_key,
                base_url=base_url,
                model=model,
                task=task,
                profile=profile,
                variant=variant,
                gap=gap,
                visible_requirement_ids=_visible_requirement_ids(
                    task,
                    profile,
                    variant=variant,
                    gap=gap,
                ),
                timeout=timeout,
                max_retries=max_retries,
            ): (task.task_id, profile.student_id, variant)
            for task, profile, variant, gap in jobs
        }
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result["variant"] == "generic":
                task = next(item for item in tasks if item.task_id == result["task_id"])
                shared_variants = [variant for variant in variants if variant in {"generic", "profile_at_answer"}]
                for shared_variant in shared_variants:
                    for profile in task.profiles:
                        clone = dict(result)
                        clone["variant"] = shared_variant
                        clone["student_id"] = profile.student_id
                        clone["profile"] = profile.to_dict()
                        clone["gap"] = planner.plan(task, profile).to_dict()
                        results.append(clone)
            else:
                results.append(result)
            status = "ok" if result["error"] is None else "error"
            print(f"[{index}/{len(futures)}] {result['task_id']} {result['student_id']} {result['variant']} {status}")
    return sorted(results, key=lambda item: (item["task_id"], item["student_id"], item["variant"]))


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""

    parser = argparse.ArgumentParser(description="Run the knowledge-state search prompt probe.")
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--api-key-env", default="PROFILE_EVAL_API_KEY")
    parser.add_argument("--base-url", default=os.environ.get("PROFILE_EVAL_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", default=os.environ.get("PROFILE_EVAL_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--variant", action="append", choices=VARIANTS)
    parser.add_argument("--limit-tasks", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    """Run the probe and save a reproducible artifact."""

    _load_env()
    args = build_parser().parse_args()
    tasks = _load_tasks(Path(args.data))
    if args.limit_tasks > 0:
        tasks = tasks[: args.limit_tasks]
    variants = tuple(args.variant or DEFAULT_VARIANTS)
    planner = KnowledgeStateGapPlanner()

    if args.dry_run:
        results = _dry_run(tasks=tasks, variants=variants, planner=planner)
        metadata = {"mode": "dry_run"}
    else:
        api_key = os.environ.get(args.api_key_env) or os.environ.get("MIMO_API_KEY") or os.environ.get("JUDGE_API_KEY")
        if not api_key:
            print(
                f"API key not found. Set {args.api_key_env}, MIMO_API_KEY, or JUDGE_API_KEY.",
                file=sys.stderr,
            )
            return 2
        results = run_probe(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            tasks=tasks,
            variants=variants,
            timeout=args.timeout,
            max_retries=args.max_retries,
            concurrency=args.concurrency,
        )
        metadata = {
            "mode": "api",
            "base_url": args.base_url.rstrip("/"),
            "model": args.model,
            "variant": list(variants),
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment": "knowledge_state_search_probe_v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "task_count": len(tasks),
                "result_count": len(results),
                "metadata": metadata,
                "results": results,
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
