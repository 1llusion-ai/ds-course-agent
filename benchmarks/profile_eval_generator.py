"""Batch-generate learning-profile benchmark cases with an OpenAI-compatible LLM."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from benchmarks.profile_eval_dataset import (
    PROFILE_EVAL_CATEGORIES,
    validate_profile_eval_dataset,
)

DEFAULT_BASE_URL = "http://model.mify.ai.srv/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5-pro"
DEFAULT_OUTPUT_PATH = Path("var") / "artifacts" / "eval_generation" / "profile_eval_v1.generated.json"
DEFAULT_CATEGORIES = (
    "profile_reading",
    "personalized_explanation",
    "learning_path",
    "weak_spot_update",
    "resolved_regression",
    "history_filter",
    "multi_turn_evolution",
    "profile_hallucination_guard",
)
CATEGORY_SPECS = {
    "profile_reading": "检查助教是否准确读取 current_chapter、covered_chapters、recent_concepts、pending/active/resolved weak spots，并只使用相关画像事实。",
    "personalized_explanation": "同一概念解释要因学生画像而改变深度、类比和补救重点，尤其测试 pending_weak_spots 与偏好。",
    "learning_path": "检查学习路线是否按当前章节、前置概念、薄弱点、可用时间排序，并避免跳过前置知识。",
    "weak_spot_update": "检查重复困惑、错误前提、追问后是否应该新增 pending 或 active weak spot，且 delta 可客观判断。",
    "resolved_regression": "检查 resolved_weak_spots 不应被误判回活跃薄弱点；只有出现新证据时才提示复盘。",
    "history_filter": "检查无关历史、很久以前或其他章节概念不会被硬套到当前问题。",
    "multi_turn_evolution": "连续多轮从误解到澄清到掌握，测试上下文利用和画像状态演化。",
    "profile_hallucination_guard": "检查画像没有记录时不编造“你之前学过/混淆过”，并透明说明依据。",
}
CONCEPT_IDS = (
    "data_science",
    "data_cleaning",
    "supervised_learning",
    "unsupervised_learning",
    "decision_tree",
    "random_forest",
    "logistic_regression",
    "svm",
    "kernel_function",
    "k_means",
    "pca",
    "covariance_matrix",
    "overfitting",
    "generalization",
    "regularization",
    "cross_validation",
    "gradient_descent",
    "learning_rate",
    "confusion_matrix",
    "precision",
    "recall",
    "f1",
)

SYSTEM_PROMPT = """你是“数据科学导论”课程 RAG 教学助教的评测集设计助手。
只输出可解析 JSON，不要 Markdown，不要注释。
评测目标是学习画像：正确读取、使用、过滤、更新 StudentProfile，而不只是回答知识点。
画像结构必须贴合：student_id, recent_concepts, progress, pending_weak_spots, weak_spot_candidates, resolved_weak_spots, stats。
禁止编造教材页码或 source_id。expected_behavior 必须是可客观检查的要求。
"""

SCHEMA_PROMPT = r"""输出 JSON 对象：
{
  "cases": [
    {
      "id": "临时id，后处理会重写",
      "category": "__CATEGORY__",
      "difficulty": "easy|medium|hard",
      "profile_fixture": {
        "student_id": "...",
        "progress": {"current_chapter": "第X章", "covered_chapters": ["第X章"]},
        "recent_concepts": {"concept_id": {"concept_id": "...", "display_name": "...", "chapter": "第X章", "mention_count": 1, "evidence": ["..."], "first_mentioned_at": 1.0, "last_mentioned_at": 2.0, "last_question_type": "..."}},
        "pending_weak_spots": [],
        "weak_spot_candidates": [],
        "resolved_weak_spots": [],
        "stats": {"total_questions": 3, "total_concepts": 2, "pending_weak_spots": 0, "active_weak_spots": 0, "resolved_weak_spots": 0, "total_resolved_weak_spots": 0}
      },
      "turns": ["学生输入1", "可选学生输入2"],
      "expected_route": "grounded_rag|learning_path_skill|personalized_explanation_skill|misconception_skill|generic_agent",
      "expected_profile_usage": {
        "must_reference": ["画像中必须利用的事实"],
        "must_not_reference": ["不应硬套的无关历史"]
      },
      "expected_behavior": ["至少3条可客观检查点"],
      "expected_profile_delta": {
        "recent_concepts_add": [],
        "pending_weak_spots_add": [],
        "weak_spot_candidates_add": [],
        "resolved_weak_spots_add": [],
        "must_not_change": []
      },
      "scoring_rubric": {"route": 1, "profile_usage": 2, "pedagogy": 2, "grounding": 1, "profile_delta": 2},
      "tags": ["profile", "..."],
      "notes": "为什么这个样例有区分度"
    }
  ]
}
"""


def _load_local_env() -> None:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env", override=False)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(raw[start : end + 1])


def _build_category_prompt(category: str, cases_per_category: int) -> str:
    schema = SCHEMA_PROMPT.replace("__CATEGORY__", category)
    return f"""为 category={category} 生成 {cases_per_category} 条学习画像评测样例。
类别目标：{CATEGORY_SPECS[category]}
可用概念 id：{", ".join(CONCEPT_IDS)}

要求：
1. 每条 profile_fixture 必须包含完整字段，不要省略空列表/空 dict。
2. 每条 expected_behavior 至少 3 点，且可以由关键词、路由或状态检查验证。
3. 至少一半样例是多轮 turns（2-3轮）。
4. 如果 category 是 profile_hallucination_guard 或 history_filter，must_not_reference 必须非空，expected_profile_delta 以 must_not_change 为主。
5. 如果 category 是 weak_spot_update 或 multi_turn_evolution，expected_profile_delta 至少有一个 add 列表非空。
6. 不要所有样例都围绕 PCA/过拟合，概念要分散。

{schema}"""


def _request_cases(
    *,
    api_key: str,
    base_url: str,
    model: str,
    category: str,
    cases_per_category: int,
    timeout: float,
    max_retries: int,
    raw_dir: Path | None,
) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_category_prompt(category, cases_per_category)},
        ],
        "temperature": 0.45,
        "max_tokens": 9000,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, max_retries + 1):
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        if not response.ok:
            print(f"[{category}] attempt {attempt}/{max_retries}: HTTP {response.status_code}")
            time.sleep(min(2 * attempt, 8))
            continue

        content = response.json()["choices"][0]["message"].get("content") or ""
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{category}.raw.txt").write_text(content, encoding="utf-8")

        try:
            parsed = _extract_json_object(content)
        except json.JSONDecodeError as exc:
            print(f"[{category}] attempt {attempt}/{max_retries}: JSON parse failed: {exc}")
            time.sleep(min(2 * attempt, 8))
            continue

        cases = parsed.get("cases") or []
        if len(cases) >= cases_per_category:
            return cases[:cases_per_category]
        print(f"[{category}] attempt {attempt}/{max_retries}: expected {cases_per_category}, got {len(cases)}")
        time.sleep(min(2 * attempt, 8))

    raise RuntimeError(f"Failed to generate enough cases for category={category}")


def generate_dataset(
    *,
    api_key: str,
    base_url: str,
    model: str,
    categories: list[str],
    cases_per_category: int,
    timeout: float,
    max_retries: int,
    raw_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate and merge category batches into a profile evaluation dataset."""
    all_cases: list[dict[str, Any]] = []
    for category in categories:
        if category not in PROFILE_EVAL_CATEGORIES:
            raise ValueError(f"Unknown profile eval category: {category}")
        print(f"[generate] {category}")
        batch = _request_cases(
            api_key=api_key,
            base_url=base_url,
            model=model,
            category=category,
            cases_per_category=cases_per_category,
            timeout=timeout,
            max_retries=max_retries,
            raw_dir=raw_dir,
        )
        for index, case in enumerate(batch, 1):
            normalized = dict(case)
            normalized["id"] = f"{category}_{index:03d}"
            normalized["category"] = category
            normalized["enabled"] = bool(normalized.get("enabled", True))
            tags = list(normalized.get("tags") or [])
            normalized["tags"] = tags if "profile" in tags else ["profile", *tags]
            all_cases.append(normalized)

    return {
        "schema_version": 1,
        "dataset_name": "profile_eval_v1",
        "version": "v1.0",
        "created_at": datetime.now(timezone.utc).date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": "Learning-profile benchmark cases for the Data Science course teaching assistant.",
        "categories": [{"name": name, "description": CATEGORY_SPECS[name]} for name in categories],
        "generation": {
            "method": "llm_assisted_batch",
            "endpoint": base_url.rstrip("/"),
            "model": model,
            "manual_review_required": True,
        },
        "cases": all_cases,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate learning-profile benchmark cases with an LLM")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Where to write the generated JSON dataset")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PROFILE_EVAL_BASE_URL") or os.environ.get("MIFY_BASE_URL") or DEFAULT_BASE_URL,
    )
    parser.add_argument("--model", default=os.environ.get("PROFILE_EVAL_MODEL") or DEFAULT_MODEL)
    parser.add_argument(
        "--api-key-env", default="PROFILE_EVAL_API_KEY", help="Environment variable that stores the API key"
    )
    parser.add_argument("--cases-per-category", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--raw-dir", default=None, help="Optional directory for raw LLM responses")
    parser.add_argument("--skip-validate", action="store_true", help="Write output even if schema validation fails")
    parser.add_argument(
        "--category",
        action="append",
        choices=sorted(PROFILE_EVAL_CATEGORIES),
        help="Generate only this category. Can be provided multiple times.",
    )
    return parser


def main() -> int:
    _load_local_env()
    args = build_arg_parser().parse_args()
    api_key = os.environ.get(args.api_key_env) or os.environ.get("MIMO_API_KEY") or os.environ.get("JUDGE_API_KEY")
    if not api_key:
        print(f"API key not found. Set {args.api_key_env}, MIMO_API_KEY, or JUDGE_API_KEY.", file=sys.stderr)
        return 2

    categories = args.category or list(DEFAULT_CATEGORIES)
    dataset = generate_dataset(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        categories=categories,
        cases_per_category=args.cases_per_category,
        timeout=args.timeout,
        max_retries=args.max_retries,
        raw_dir=Path(args.raw_dir) if args.raw_dir else None,
    )

    issues = validate_profile_eval_dataset(dataset)
    if issues and not args.skip_validate:
        print(f"Generated dataset failed validation with {len(issues)} issue(s).", file=sys.stderr)
        for issue in issues[:20]:
            print(f"- {issue['id']} {issue['field']}: {issue['message']}", file=sys.stderr)
        return 3

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(dataset['cases'])} cases to {output}")
    if issues:
        print(f"Validation issues ignored: {len(issues)}")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
