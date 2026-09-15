"""Generate candidate closed-loop trajectories without mutating the frozen dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import requests

from benchmarks.personalized_closed_loop_schema import (
    Dataset,
    canonical_sha256,
    current_course_kc_ids,
    validate_dataset,
)

SYSTEM_PROMPT = """你是《数据科学导论》个性化教学闭环评测集生成器。
只输出 JSON，不要 Markdown。只使用用户提供的 course_kc_ids，必须生成符合指定 schema 的轨迹。
每条轨迹从空学生开始，步骤只能是 open_session/chat/submit_assessment/checkpoint/retry_last_action。
不要写入真实学生信息，不要编造课程 KC。
"""


def build_prompt(*, count: int, course_kc_ids: set[str]) -> str:
    return json.dumps(
        {
            "task": "generate closed-loop benchmark candidates",
            "count": count,
            "course_kc_ids": sorted(course_kc_ids),
            "coverage": {
                "kc_routing": 4,
                "profile_stratification": 5,
                "history_utilization": 5,
                "assessment_loop": 4,
                "student_isolation": 4,
                "lifecycle_idempotency": 2,
            },
            "required_top_level_schema": "personalized-closed-loop/1.0",
        },
        ensure_ascii=False,
    )


def generate_candidate(*, api_key: str, base_url: str, model: str, count: int = 24) -> Dataset:
    """Request one structured JSON candidate and validate it before returning."""

    kc_ids = current_course_kc_ids()
    prompt = build_prompt(count=count, course_kc_ids=kc_ids)
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    dataset = Dataset.model_validate_json(content)
    if dataset.generation.source != "llm":
        raise ValueError("generated candidate must declare generation.source=llm")
    return dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://model.mify.ai.srv/v1"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", ""))
    parser.add_argument("--output", type=Path, default=Path("var/artifacts/personalized_closed_loop_candidates.json"))
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("--api-key or API_KEY is required")
    dataset = generate_candidate(api_key=args.api_key, base_url=args.base_url, model=args.model)
    # Revalidate against the repository graph, then write only to the artifact area.
    temp = args.output
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(json.dumps(dataset.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_dataset(temp)
    print(
        json.dumps(
            {
                "output": str(temp),
                "model": args.model,
                "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
                "dataset_sha256": canonical_sha256(dataset),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
