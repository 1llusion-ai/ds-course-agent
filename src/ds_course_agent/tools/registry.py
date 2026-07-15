"""Tool registry and metadata for the teaching agent.

This module is intentionally lightweight: existing LangChain tool callables stay in
``ds_course_agent.rag.tools`` for now, while this registry records operational
metadata that the agent/UI can use for progress events, safe parallelism, and
future tool-result offloading.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class ToolSpec:
    """Operational metadata for one callable tool.

    ``read_only`` describes whether the tool mutates application/domain state.
    ``side_effect`` marks writes or externally visible effects. Token/cost usage is
    captured separately via ``cost_class`` so retrieval+LLM tools can remain
    read-only while still being observable as expensive.
    """

    name: str
    tool: Any
    read_only: bool
    side_effect: bool
    concurrency_safe: bool
    cost_class: str = "cheap"
    progress_label: str = "正在使用工具..."
    expose_to_agent: bool = True
    result_policy: str = "inline"
    description: str = ""

    def __post_init__(self) -> None:
        actual_name = getattr(self.tool, "name", None)
        if actual_name and actual_name != self.name:
            raise ValueError(
                f"ToolSpec name mismatch: spec={self.name!r}, tool.name={actual_name!r}"
            )
        if self.read_only and self.side_effect:
            raise ValueError(f"Tool {self.name!r} cannot be both read_only and side_effect")
        if not self.progress_label:
            raise ValueError(f"Tool {self.name!r} must define a progress_label")
        if self.result_policy not in {"inline", "offload_candidate", "offload"}:
            raise ValueError(f"Unsupported result_policy for {self.name!r}: {self.result_policy!r}")

    @property
    def can_run_in_parallel(self) -> bool:
        """Whether the framework may run this tool concurrently with other safe tools."""

        return self.read_only and not self.side_effect and self.concurrency_safe

    def to_metadata(self) -> dict[str, Any]:
        """JSON-serializable metadata for traces/UI without exposing callables."""

        return {
            "name": self.name,
            "read_only": self.read_only,
            "side_effect": self.side_effect,
            "concurrency_safe": self.concurrency_safe,
            "can_run_in_parallel": self.can_run_in_parallel,
            "cost_class": self.cost_class,
            "progress_label": self.progress_label,
            "expose_to_agent": self.expose_to_agent,
            "result_policy": self.result_policy,
            "description": self.description,
        }


class ToolRegistry:
    """Ordered collection of ``ToolSpec`` objects."""

    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: OrderedDict[str, ToolSpec] = OrderedDict()
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._specs:
            raise ValueError(f"Duplicate tool registered: {spec.name}")
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def maybe_get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    @property
    def names(self) -> list[str]:
        return list(self._specs.keys())

    def specs(self, *, exposed_only: bool = False) -> list[ToolSpec]:
        values = list(self._specs.values())
        if exposed_only:
            return [spec for spec in values if spec.expose_to_agent]
        return values

    def as_langchain_tools(self, *, exposed_only: bool = True) -> list[Any]:
        return [spec.tool for spec in self.specs(exposed_only=exposed_only)]

    def metadata(self, *, exposed_only: bool = False) -> list[dict[str, Any]]:
        return [spec.to_metadata() for spec in self.specs(exposed_only=exposed_only)]

    def progress_label_for(self, name: str, default: str = "正在使用工具...") -> str:
        spec = self.maybe_get(name)
        return spec.progress_label if spec else default


def build_default_tool_registry() -> ToolRegistry:
    """Build the default registry from the existing tool implementations.

    Imports are deliberately lazy to avoid changing the current ``rag.tools``
    import graph while the directory split is still incremental.
    """

    rag_tools = import_module("ds_course_agent.rag.tools")

    return ToolRegistry(
        [
            ToolSpec(
                name="course_rag_tool",
                tool=rag_tools.course_rag_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="llm_retrieval",
                progress_label="正在检索课程资料...",
                result_policy="offload_candidate",
                description="检索课程资料并基于教材生成 grounded answer。",
            ),
            ToolSpec(
                name="check_knowledge_base_status",
                tool=rag_tools.check_knowledge_base_status,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="retrieval",
                progress_label="正在检查知识库状态...",
                description="检查课程知识库是否可检索。",
            ),
            ToolSpec(
                name="course_schedule_tool",
                tool=rag_tools.course_schedule_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="cheap",
                progress_label="正在查询课程安排...",
                description="查询上课时间、教室、周次等课程安排。",
            ),
            ToolSpec(
                name="current_datetime_tool",
                tool=rag_tools.current_datetime_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="cheap",
                progress_label="正在读取当前时间...",
                description="读取当前日期、星期和本地时间。",
            ),
            ToolSpec(
                name="python_exec_tool",
                tool=rag_tools.python_exec_tool,
                read_only=False,
                side_effect=True,
                concurrency_safe=False,
                cost_class="sandbox",
                progress_label="正在执行 Python 代码...",
                result_policy="offload_candidate",
                description="在受限 sandbox 中执行 Python 代码。",
            ),
            ToolSpec(
                name="record_misconception_event",
                tool=rag_tools.record_misconception_event,
                read_only=False,
                side_effect=True,
                concurrency_safe=False,
                cost_class="write",
                progress_label="正在记录学习事件...",
                expose_to_agent=False,
                description="写入学生 misconception 学习事件；当前由 skill executor 调用，不暴露给通用 agent。",
            ),
        ]
    )


__all__ = ["ToolRegistry", "ToolSpec", "build_default_tool_registry"]
