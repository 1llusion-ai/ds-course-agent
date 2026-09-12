"""Stream-worker coordination and persisted progress projection."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from ds_course_agent.api import chat_sessions
from ds_course_agent.api.admission import ChatLease
from ds_course_agent.api.schemas.chat import ChatMessage
from ds_course_agent.api.stream_jobs import ActiveStreamJob, stream_job_registry

logger = logging.getLogger(__name__)
_PROGRESS_DETAIL_STRING_LIMIT = 500
_PROGRESS_DETAIL_LIST_LIMIT = 5
_PROGRESS_DETAIL_DICT_LIMIT = 24
_PROGRESS_DETAIL_JSON_LIMIT = 6000

StreamEventSource = Callable[[], Iterator[dict[str, Any]]]


def _compact_progress_detail_value(value, *, depth: int = 0):
    """Bound progress event details before persisting them to chat history."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _PROGRESS_DETAIL_STRING_LIMIT:
            return value
        return value[: _PROGRESS_DETAIL_STRING_LIMIT - 1].rstrip() + "…"
    if depth >= 3:
        return str(value)[:_PROGRESS_DETAIL_STRING_LIMIT]
    if isinstance(value, list):
        compacted = [
            _compact_progress_detail_value(item, depth=depth + 1) for item in value[:_PROGRESS_DETAIL_LIST_LIMIT]
        ]
        if len(value) > _PROGRESS_DETAIL_LIST_LIMIT:
            compacted.append({"_truncated_items": len(value) - _PROGRESS_DETAIL_LIST_LIMIT})
        return compacted
    if isinstance(value, dict):
        compacted: dict = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _PROGRESS_DETAIL_DICT_LIMIT:
                compacted["_truncated_keys"] = len(value) - _PROGRESS_DETAIL_DICT_LIMIT
                break
            compacted[str(key)] = _compact_progress_detail_value(item, depth=depth + 1)
        return compacted
    return str(value)[:_PROGRESS_DETAIL_STRING_LIMIT]


def compact_progress_details_for_history(details: Any) -> Any:
    """Bound progress details before storing them in persistent history."""

    if details is None:
        return None
    compacted = _compact_progress_detail_value(details)
    try:
        encoded = json.dumps(compacted, ensure_ascii=False)
    except TypeError:
        return str(compacted)[:_PROGRESS_DETAIL_JSON_LIMIT]
    if len(encoded) <= _PROGRESS_DETAIL_JSON_LIMIT:
        return compacted
    return {
        "truncated": True,
        "preview": encoded[: _PROGRESS_DETAIL_JSON_LIMIT - 1].rstrip() + "…",
    }


def _progress_phase_exists(progress_events: list[dict] | None, phase: str) -> bool:
    return any(str(event.get("phase") or "") == phase for event in progress_events or [] if isinstance(event, dict))


def _query_trace_has_stage(query_trace: dict | None, stage: str) -> bool:
    events = query_trace.get("events", []) if isinstance(query_trace, dict) else []
    return any(isinstance(event, dict) and event.get("stage") == stage for event in events)


def _query_trace_stage_has_status(query_trace: dict | None, stage: str, status: str) -> bool:
    events = query_trace.get("events", []) if isinstance(query_trace, dict) else []
    return any(
        isinstance(event, dict) and event.get("stage") == stage and event.get("status") == status for event in events
    )


def _sources_from_progress_events(progress_events: list[dict] | None) -> list[dict]:
    """Collect typed source snapshots emitted before stream completion."""

    sources: list[dict] = []
    seen: set[str] = set()
    for event in progress_events or []:
        details = event.get("details") if isinstance(event, dict) else None
        event_sources = details.get("sources") if isinstance(details, dict) else None
        for source in event_sources or []:
            if not isinstance(source, dict):
                continue
            key = str(source.get("url") or source.get("href") or source.get("reference") or "")
            if not key or key in seen:
                continue
            sources.append(dict(source))
            seen.add(key)
    return sources


def _routing_fields_from_progress_events(progress_events: list[dict] | None) -> dict[str, str | None]:
    """Return the latest typed routing fields established by the active stream."""

    routing_fields: dict[str, str | None] = {
        "family": None,
        "intent": None,
        "execution_mode": None,
    }
    for event in reversed(progress_events or []):
        if not isinstance(event, dict):
            continue
        for field_name in routing_fields:
            if routing_fields[field_name] is None and event.get(field_name):
                routing_fields[field_name] = str(event[field_name])
        if all(routing_fields.values()):
            break
    return routing_fields


def _retrieval_fields_from_progress_events(progress_events: list[dict] | None) -> dict[str, bool]:
    """Return explicit retrieval facts emitted by typed retrieval events."""

    fields = {
        "retrieval_attempted": False,
        "used_retrieval": False,
        "degraded": False,
    }
    for event in progress_events or []:
        details = event.get("details") if isinstance(event, dict) else None
        if not isinstance(details, dict):
            continue
        for field_name in fields:
            fields[field_name] = fields[field_name] or bool(details.get(field_name, False))
    return fields


def web_search_turn_fields(
    *,
    requested: bool,
    used_retrieval: bool | None,
    progress_events: list[dict] | None = None,
    query_trace: dict | None = None,
    sources: list[dict] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build explicit per-turn web-search state for the frontend."""

    if not requested:
        return {
            "web_search_requested": False,
            "web_search_used": False,
            "web_search_status": "not_requested",
            "web_search_reason": None,
        }

    used = bool(used_retrieval) or chat_sessions.has_web_source(sources)
    if used:
        return {
            "web_search_requested": True,
            "web_search_used": True,
            "web_search_status": "used",
            "web_search_reason": None,
        }

    if _progress_phase_exists(progress_events, "web_search_scope") or _query_trace_has_stage(
        query_trace,
        "web_search.scope_blocked",
    ):
        status = "blocked_by_scope"
        reason = "问题超出课程助教范围，本轮未进行通用联网搜索。"
    elif (
        _progress_phase_exists(progress_events, "web_search_error")
        or _query_trace_stage_has_status(query_trace, "web_search.no_results", "error")
        or error
        or _query_trace_stage_has_status(query_trace, "execute.web_search_tool", "error")
    ):
        status = "error"
        reason = str(error or "联网搜索暂时不可用。")
    elif _progress_phase_exists(progress_events, "web_search_results") and not chat_sessions.has_web_source(sources):
        status = "no_results"
        reason = "本轮联网搜索未获得可用结果。"
    elif _query_trace_has_stage(query_trace, "web_search.no_results"):
        status = "no_results"
        reason = "本轮联网搜索未获得可用结果。"
    else:
        status = "not_used"
        reason = "本轮未实际使用联网搜索。"

    return {
        "web_search_requested": True,
        "web_search_used": False,
        "web_search_status": status,
        "web_search_reason": reason,
    }


def active_stream_snapshot(session_id: str, student_id: str) -> dict[str, Any] | None:
    """Return the owned active stream snapshot for history restoration."""

    job = stream_job_registry.get_for_owner(session_id, student_id, active_only=True)
    if not job:
        return None
    return job.snapshot().to_dict()


def launch_stream_worker(
    *,
    session_id: str,
    student_id: str,
    operation_lock: threading.Lock,
    event_source: StreamEventSource,
    message_timestamp: datetime,
    web_search: bool,
    admission_lease: ChatLease | None = None,
    initial_content: str = "",
    initial_progress_events: list[dict[str, Any]] | None = None,
    replace_message_item: dict[str, Any] | None = None,
    base_message: ChatMessage | None = None,
) -> ActiveStreamJob:
    """Run one blocking agent stream independently from connected SSE clients."""

    stop_event = threading.Event()
    job = stream_job_registry.register(
        session_id=session_id,
        student_id=student_id,
        cancel_event=stop_event,
        message_timestamp=message_timestamp,
        initial_content=initial_content,
        initial_progress_events=initial_progress_events,
    )
    job.publish(
        {
            "type": "snapshot",
            **job.snapshot().to_dict(),
            "resuming": False,
        }
    )
    persist_lock = threading.Lock()
    persisted_final = threading.Event()

    def _persist_message_once(message: ChatMessage) -> ChatMessage | None:
        with persist_lock:
            if persisted_final.is_set():
                return None
            if replace_message_item is None:
                chat_sessions.append_message_locked(session_id, message, save=False)
            elif not chat_sessions.replace_message_by_identity(
                session_id,
                replace_message_item,
                message,
                save=False,
            ):
                raise RuntimeError("被续写的回答已不存在")
            chat_sessions.update_session_metadata(session_id, message.timestamp.isoformat(), save=False)
            chat_sessions.save_state()
            persisted_final.set()
            return message

    def _build_message(
        event: dict,
        *,
        generation_status: str,
        generation_error: str | None = None,
    ) -> ChatMessage:
        snapshot = job.snapshot()
        content = str(event.get("content") or snapshot.content)
        base_metadata = dict(base_message.metadata or {}) if base_message else {}
        for control_field in ("retrieval_attempted", "used_retrieval", "degraded"):
            base_metadata.pop(control_field, None)
        progress_sources = _sources_from_progress_events(snapshot.progress_events)
        assistant_sources = (
            event.get("sources") or (base_message.sources if base_message else None) or progress_sources or None
        )
        progress_routing = _routing_fields_from_progress_events(snapshot.progress_events)
        family = (
            event.get("family")
            or (base_message.family.value if base_message and base_message.family else None)
            or progress_routing["family"]
        )
        intent = (
            event.get("intent")
            or (base_message.intent.value if base_message and base_message.intent else None)
            or progress_routing["intent"]
        )
        execution_mode = (
            event.get("execution_mode")
            or (base_message.execution_mode.value if base_message and base_message.execution_mode else None)
            or progress_routing["execution_mode"]
        )
        progress_retrieval = _retrieval_fields_from_progress_events(snapshot.progress_events)
        retrieval_attempted = bool(event.get("retrieval_attempted", False)) or progress_retrieval["retrieval_attempted"]
        used_retrieval = bool(event.get("used_retrieval", False)) or progress_retrieval["used_retrieval"]
        degraded = bool(event.get("degraded", False)) or progress_retrieval["degraded"]
        if base_message:
            retrieval_attempted = retrieval_attempted or base_message.retrieval_attempted
            used_retrieval = used_retrieval or base_message.used_retrieval
            degraded = degraded or base_message.degraded
        metadata = {
            **base_metadata,
            "web_search": bool(web_search),
        }

        if base_message:
            web_fields = {
                "web_search_requested": base_message.web_search_requested,
                "web_search_used": base_message.web_search_used,
                "web_search_status": base_message.web_search_status,
                "web_search_reason": base_message.web_search_reason,
            }
        else:
            web_fields = web_search_turn_fields(
                requested=bool(web_search),
                used_retrieval=used_retrieval,
                progress_events=snapshot.progress_events,
                query_trace=event.get("query_trace") if isinstance(event.get("query_trace"), dict) else None,
                sources=assistant_sources,
                error=generation_error,
            )

        return ChatMessage(
            role="assistant",
            content=content,
            timestamp=message_timestamp,
            sources=assistant_sources,
            family=family,
            intent=intent,
            execution_mode=execution_mode,
            retrieval_attempted=retrieval_attempted,
            used_retrieval=used_retrieval,
            degraded=degraded,
            progress=snapshot.progress,
            progress_events=snapshot.progress_events or None,
            generation_status=generation_status,
            generation_error=generation_error,
            metadata=metadata,
            **web_fields,
        )

    def _publish_final(
        event: dict,
        *,
        generation_status: str,
        generation_error: str | None = None,
    ) -> None:
        assistant_message = _build_message(
            event,
            generation_status=generation_status,
            generation_error=generation_error,
        )
        saved_message = _persist_message_once(assistant_message)
        if saved_message is None:
            return
        snapshot = job.snapshot()
        job.publish(
            {
                "type": "final",
                "session_id": session_id,
                "stream_id": event.get("stream_id") or snapshot.stream_id,
                "family": saved_message.family.value if saved_message.family else None,
                "intent": saved_message.intent.value if saved_message.intent else None,
                "execution_mode": saved_message.execution_mode.value if saved_message.execution_mode else None,
                "error": generation_error,
                "message": chat_sessions.message_to_dict(saved_message),
            }
        )

    def _publish_unpersisted_terminal_error() -> None:
        """Terminate replay even when the final history mutation cannot be saved."""

        if job.snapshot().terminal:
            return
        generation_error = "回答已结束，但最终状态无法保存，请刷新后重试。"
        try:
            message = chat_sessions.message_to_dict(
                _build_message(
                    {},
                    generation_status="error",
                    generation_error=generation_error,
                )
            )
        except Exception:
            message = None
        snapshot = job.snapshot()
        job.publish(
            {
                "type": "final",
                "session_id": session_id,
                "stream_id": snapshot.stream_id,
                "error": generation_error,
                "message": message,
            }
        )

    def worker() -> None:
        source = None
        try:
            source = iter(event_source())
            for event in source:
                if not isinstance(event, dict):
                    continue
                if stop_event.is_set():
                    break

                event_type = event.get("type")
                if event_type == "progress":
                    details = event.get("details") or None
                    base_progress_event = {
                        "phase": event.get("phase"),
                        "message": event.get("message", ""),
                        "family": event.get("family"),
                        "intent": event.get("intent"),
                        "execution_mode": event.get("execution_mode"),
                        "tool": event.get("tool"),
                        "stream_id": event.get("stream_id"),
                        "resuming": bool(event.get("resuming", False)),
                        "timestamp": datetime.now().isoformat(),
                    }
                    job.publish(
                        {
                            "type": "progress",
                            **base_progress_event,
                            "details": details,
                        },
                        snapshot_progress={
                            **base_progress_event,
                            "details": compact_progress_details_for_history(details),
                        },
                    )
                    continue

                if event_type == "delta" and event.get("delta"):
                    job.publish(
                        {
                            "type": "delta",
                            "delta": str(event["delta"]),
                            "stream_id": event.get("stream_id"),
                            "resuming": bool(event.get("resuming", False)),
                        }
                    )
                    continue

                if event_type == "final":
                    generation_error = str(event.get("error") or "") or None
                    _publish_final(
                        event,
                        generation_status="error" if generation_error else "completed",
                        generation_error=generation_error,
                    )
                    return

                if event_type == "error":
                    error_message = str(event.get("message") or event.get("error") or "发送失败")
                    _publish_final(
                        event,
                        generation_status="error",
                        generation_error=error_message,
                    )
                    return

            if stop_event.is_set():
                _publish_final({}, generation_status="stopped")
            else:
                _publish_final(
                    {},
                    generation_status="error",
                    generation_error="流式连接已结束，但未收到完整回答。",
                )
        except Exception as exc:
            logger.error("流式响应 worker 失败: %s", exc, exc_info=True)
            try:
                _publish_final(
                    {},
                    generation_status="error",
                    generation_error="回答暂时无法生成，请稍后重试。",
                )
            except Exception:
                logger.error("流式失败状态保存失败", exc_info=True)
                _publish_unpersisted_terminal_error()
        finally:
            try:
                close = getattr(source, "close", None)
                if callable(close):
                    close()
            except Exception:
                logger.exception("Failed to close upstream chat stream")
            finally:
                if admission_lease is not None:
                    admission_lease.release()
                operation_lock.release()

    try:
        threading.Thread(
            target=worker,
            name=f"chat-sse-{session_id[:16]}",
            daemon=True,
        ).start()
    except BaseException:
        stream_job_registry.discard(session_id, job)
        raise
    return job


__all__ = [
    "StreamEventSource",
    "active_stream_snapshot",
    "compact_progress_details_for_history",
    "launch_stream_worker",
    "web_search_turn_fields",
]
