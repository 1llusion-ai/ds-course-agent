"""Rule-based clarification/mastery detection.

These rules used to live directly on AgentService.  Keeping them in a hook-style
object makes the teaching-specific signals reusable by LearningEventHook and the
future router/context hooks without expanding AgentService again.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any


def _normalize_query_text(text: str) -> str:
    from ds_course_agent.agent.routing.utils import normalize_query_text

    return normalize_query_text(text)


class ClarificationDetectorHook:
    """Pure rule detector for clarification and mastery signals."""

    def is_clarification_request(self, question: str) -> bool:
        normalized = _normalize_query_text(question)
        cues = [
            "没懂",
            "不懂",
            "没明白",
            "还是不懂",
            "还是没懂",
            "再讲",
            "再解释",
            "怎么理解",
            "看不懂",
            "有点混",
            "混淆",
            "通俗",
            "直观",
            "举个例子",
            "再说一遍",
            "梳理一下",
            "为什么",
            "为什么会",
        ]
        return any(cue in normalized for cue in cues)

    def is_mastery_signal(self, question: str) -> bool:
        normalized = _normalize_query_text(question)
        cues = [
            "懂了",
            "明白了",
            "会了",
            "清楚了",
            "知道了",
            "理解了",
            "学会了",
            "搞懂了",
        ]
        return any(cue in normalized for cue in cues)

    def infer_clarification_type(self, question: str) -> str:
        normalized = _normalize_query_text(question)
        if any(cue in normalized for cue in ["举个例子", "例子", "案例"]):
            return "example_request"
        if any(cue in normalized for cue in ["通俗", "直观", "看不懂", "怎么理解"]):
            return "simplify_request"
        if any(cue in normalized for cue in ["混淆", "区别", "分不清"]):
            return "distinction_request"
        return "clarification_request"

    def sanitize_distinction_fragment(self, fragment: str) -> str:
        value = re.sub(r"[，。？！,.!?；;：:（）()“”\"'《》【】\[\]]", "", fragment or "")
        value = re.sub(
            r"^(我感觉|我觉得|我有点|我还是|我总是|我老是|总是|老是|一直|就是|其实|搞不懂|分不清|不太懂|不懂|没懂|没明白)+",
            "",
            value,
        )
        value = re.sub(
            r"(到底|究竟|有什么|有啥|什么|之间|怎么|为何|为什么|的|区别|差别|不同|差异|怎么区分|怎么理解)+$",
            "",
            value,
        )
        return re.sub(r"\s+", "", value).strip("和与跟及、/-")

    def extract_distinction_labels(self, question: str, matched_concepts: list[Any]) -> list[str]:
        prefix = question
        for cue in [
            "有什么区别",
            "有什么差别",
            "区别是什么",
            "差别是什么",
            "区别",
            "差别",
            "分不清",
            "混淆",
            "对比",
            "比较",
            "区分",
        ]:
            idx = prefix.find(cue)
            if idx != -1:
                prefix = prefix[:idx]
                break

        parsed_labels = []
        for part in re.split(r"(?:和|与|跟|及|vs|VS|/)", prefix):
            cleaned = self.sanitize_distinction_fragment(part)
            if cleaned:
                parsed_labels.append(cleaned)

        if len(parsed_labels) >= 2:
            return parsed_labels[-2:]

        if len(matched_concepts) >= 2:
            return [matched_concepts[0].display_name, matched_concepts[1].display_name]

        if len(matched_concepts) == 1 and parsed_labels:
            labels = [matched_concepts[0].display_name]
            for label in parsed_labels:
                if _normalize_query_text(label) != _normalize_query_text(labels[0]):
                    labels.append(label)
                    break
            if len(labels) >= 2:
                return labels[:2]

        return []

    def build_distinction_learning_concept(
        self,
        question: str,
        matched_concepts: list[Any],
    ) -> dict[str, Any] | None:
        labels = self.extract_distinction_labels(question, matched_concepts)
        if len(labels) < 2:
            return None

        stable_labels = sorted(
            dict.fromkeys(labels),
            key=_normalize_query_text,
        )
        if len(stable_labels) < 2:
            return None

        related_ids = sorted({match.concept_id for match in matched_concepts[:2] if getattr(match, "concept_id", None)})
        chapter = next(
            (match.chapter for match in matched_concepts if getattr(match, "chapter", None)),
            "",
        )
        payload = {
            "labels": stable_labels,
            "chapter": chapter,
            "related_ids": related_ids,
        }
        encoded = (
            base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )

        return {
            "concept_id": f"distinction::{encoded}",
            "concept_name": " vs ".join(stable_labels),
            "chapter": chapter,
            "score": max((getattr(match, "score", 0.0) for match in matched_concepts[:2]), default=0.85),
            "source_event_id": None,
        }


__all__ = ["ClarificationDetectorHook"]
