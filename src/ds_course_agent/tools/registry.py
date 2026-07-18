"""Tool registry and metadata for the teaching agent."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """Operational metadata for one callable tool.

    ``read_only`` describes whether the tool mutates application/domain state.
    ``side_effect`` marks writes or externally visible effects. Token/cost usage is
    captured separately via ``cost_class`` so retrieval+LLM tools can remain
    read-only while still being observable as expensive.

    ``exclusive`` marks tools that must never be grouped into safe parallel
    batches even if they are otherwise read-only.

    ``result_policy`` is a registry contract for normalization/offload decisions.
    Use ``apply_tool_result_policy`` at tool-return boundaries to persist/trace
    large results for tools marked ``offload_candidate`` or ``offload``.
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
    exclusive: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        actual_name = getattr(self.tool, "name", None)
        if actual_name and actual_name != self.name:
            raise ValueError(f"ToolSpec name mismatch: spec={self.name!r}, tool.name={actual_name!r}")
        if self.read_only and self.side_effect:
            raise ValueError(f"Tool {self.name!r} cannot be both read_only and side_effect")
        if not self.progress_label:
            raise ValueError(f"Tool {self.name!r} must define a progress_label")
        if self.result_policy not in {"inline", "offload_candidate", "offload"}:
            raise ValueError(f"Unsupported result_policy for {self.name!r}: {self.result_policy!r}")

    @property
    def can_run_in_parallel(self) -> bool:
        """Whether the framework may run this tool concurrently with other safe tools."""

        return self.read_only and not self.side_effect and self.concurrency_safe and not self.exclusive

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
            "exclusive": self.exclusive,
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

    def as_langchain_tools_for(self, names: Iterable[str]) -> list[Any]:
        """Return the concrete tools for a named subset.

        ``names`` must resolve to registered, agent-exposed tools. This keeps the
        agent-side tool gate structural rather than prompt-driven.
        """

        tools = []
        for name in names:
            spec = self.get(name)
            if not spec.expose_to_agent:
                raise ValueError(f"Tool {name!r} is not exposed to the generic agent")
            tools.append(spec.tool)
        return tools

    def metadata(self, *, exposed_only: bool = False) -> list[dict[str, Any]]:
        return [spec.to_metadata() for spec in self.specs(exposed_only=exposed_only)]

    def progress_label_for(self, name: str, default: str = "正在使用工具...") -> str:
        spec = self.maybe_get(name)
        return spec.progress_label if spec else default

    def can_run_in_parallel(self, name: str) -> bool:
        """Return whether a named tool is safe to batch with other read-only tools.

        Unknown tools are treated conservatively as not parallelizable.
        """

        spec = self.maybe_get(name)
        return bool(spec and spec.can_run_in_parallel)

    def plan_parallel_groups(self, names: Iterable[str]) -> list[list[str]]:
        """Build conservative execution groups from tool metadata.

        Consecutive read-only/concurrency-safe/non-exclusive tools are grouped
        together. Unknown, side-effecting, or exclusive tools become their own
        serial groups. The input order is preserved.
        """

        groups: list[list[str]] = []
        current_parallel: list[str] = []

        def flush_parallel() -> None:
            if current_parallel:
                groups.append(list(current_parallel))
                current_parallel.clear()

        for name in names:
            if self.can_run_in_parallel(name):
                current_parallel.append(name)
                continue
            flush_parallel()
            groups.append([name])

        flush_parallel()
        return groups

    def apply_result_policy(
        self,
        name: str,
        result: Any,
        *,
        payload_type: str = "tool_result",
        location: str | None = None,
        **metadata: Any,
    ) -> dict[str, Any] | None:
        """Apply the named tool's result normalization/offload policy.

        ``inline`` and unknown tools are no-ops. ``offload_candidate`` and
        ``offload`` delegate to ``shared.tool_result_store``. Telemetry failures
        must not break tool execution, so exceptions are swallowed.
        """

        spec = self.maybe_get(name)
        if spec is None or spec.result_policy == "inline":
            return None

        try:
            from ds_course_agent.shared.tool_result_store import maybe_store_large_text_payload

            return maybe_store_large_text_payload(
                result,
                location=location or f"tool.{name}.result",
                payload_type=payload_type,
                tool=name,
                result_policy=spec.result_policy,
                **metadata,
            )
        except Exception:
            return None


def build_default_tool_registry() -> ToolRegistry:
    """Build the default registry from split one-tool modules."""

    from ds_course_agent.tools.course_rag import course_rag_tool
    from ds_course_agent.tools.course_schedule import course_schedule_tool
    from ds_course_agent.tools.datetime_tool import current_datetime_tool
    from ds_course_agent.tools.knowledge_base_status import check_knowledge_base_status
    from ds_course_agent.tools.misconception import record_misconception_event
    from ds_course_agent.tools.python_exec import python_exec_tool
    from ds_course_agent.tools.web_fetch import web_fetch_tool
    from ds_course_agent.tools.web_search import web_search_tool

    return ToolRegistry(
        [
            ToolSpec(
                name="course_rag_tool",
                tool=course_rag_tool,
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
                tool=check_knowledge_base_status,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="retrieval",
                progress_label="正在检查知识库状态...",
                description="检查课程知识库是否可检索。",
            ),
            ToolSpec(
                name="course_schedule_tool",
                tool=course_schedule_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="cheap",
                progress_label="正在查询课程安排...",
                description="查询上课时间、教室、周次等课程安排。",
            ),
            ToolSpec(
                name="current_datetime_tool",
                tool=current_datetime_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="cheap",
                progress_label="正在读取当前时间...",
                description="读取当前日期、星期和本地时间。",
            ),
            ToolSpec(
                name="python_exec_tool",
                tool=python_exec_tool,
                read_only=False,
                side_effect=True,
                concurrency_safe=False,
                cost_class="sandbox",
                progress_label="正在执行 Python 代码...",
                result_policy="offload_candidate",
                description="在受限 sandbox 中执行 Python 代码。",
            ),
            ToolSpec(
                name="web_search_tool",
                tool=web_search_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="network",
                progress_label="正在联网搜索...",
                expose_to_agent=False,
                result_policy="offload_candidate",
                description="用户显式开启联网搜索时，检索外部网页并返回压缩证据摘要。",
            ),
            ToolSpec(
                name="web_fetch_tool",
                tool=web_fetch_tool,
                read_only=True,
                side_effect=False,
                concurrency_safe=True,
                cost_class="network",
                progress_label="正在读取网页内容...",
                expose_to_agent=False,
                result_policy="offload_candidate",
                description="显式联网搜索后的深度网页阅读工具，抓取并压缩网页正文。",
            ),
            ToolSpec(
                name="record_misconception_event",
                tool=record_misconception_event,
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


def get_rag_tool_registry() -> ToolRegistry:
    """Return the operational registry for all known course-agent tools."""

    return build_default_tool_registry()


def get_rag_tool_spec(name: str) -> ToolSpec:
    """Return metadata for a named tool."""

    return get_rag_tool_registry().get(name)


def get_rag_tool_metadata(*, exposed_only: bool = False) -> list[dict[str, Any]]:
    """Return JSON-serializable tool metadata for traces/UI/tests."""

    return get_rag_tool_registry().metadata(exposed_only=exposed_only)


def get_rag_tools() -> list[Any]:
    """Return the LangChain tools exposed to the generic agent."""

    return get_rag_tool_registry().as_langchain_tools(exposed_only=True)


def apply_tool_result_policy(
    name: str,
    result: Any,
    *,
    registry: ToolRegistry | None = None,
    payload_type: str = "tool_result",
    location: str | None = None,
    **metadata: Any,
) -> dict[str, Any] | None:
    """Apply result policy using the default or supplied registry."""

    active_registry = registry or get_rag_tool_registry()
    return active_registry.apply_result_policy(
        name,
        result,
        payload_type=payload_type,
        location=location,
        **metadata,
    )


__all__ = [
    "ToolRegistry",
    "ToolSpec",
    "build_default_tool_registry",
    "apply_tool_result_policy",
    "get_rag_tool_registry",
    "get_rag_tool_spec",
    "get_rag_tool_metadata",
    "get_rag_tools",
]
