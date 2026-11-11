"""Compose content-free usage facts from their owning repositories."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ds_course_agent.api.auth import models, registration
from ds_course_agent.api.auth.contracts import User
from ds_course_agent.api.course_context import course_catalog
from ds_course_agent.api.session_statistics import ChatFact, ChatFacts, read_chat_facts
from ds_course_agent.assessment.statistics import AssessmentFact, read_assessment_facts

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class StatisticsWindow:
    start: datetime
    end: datetime
    as_of: datetime

    def includes(self, value: str | None) -> bool:
        if value is None:
            return False
        instant = registration.parse_time(value)
        return self.start <= instant < self.end and instant <= self.as_of


def make_window(start: date, end: date) -> StatisticsWindow:
    return StatisticsWindow(
        datetime.combine(start, time.min, LOCAL_TZ),
        datetime.combine(end + timedelta(days=1), time.min, LOCAL_TZ),
        datetime.now(timezone.utc),
    )


def _day(value: str) -> str:
    return registration.parse_time(value).astimezone(LOCAL_TZ).date().isoformat()


def _deduplicate(messages: tuple[ChatFact, ...]) -> tuple[ChatFact, ...]:
    unique = {}
    for fact in messages:
        unique[(fact.student_id, fact.course_id, fact.session_id, fact.turn_id, fact.role)] = fact
    return tuple(unique.values())


def _usage(chat: ChatFacts, assessments: tuple[AssessmentFact, ...], window: StatisticsWindow) -> tuple[dict, set[str]]:
    messages = _deduplicate(tuple(f for f in chat.messages if window.includes(f.created_at)))
    questions = [fact for fact in messages if fact.role == "user"]
    submitted = [fact for fact in assessments if window.includes(fact.submitted_at)]
    assigned = [fact for fact in assessments if window.includes(fact.assigned_at)]
    cohort_completed = sum(
        bool(f.submitted_at and registration.parse_time(f.submitted_at) <= window.as_of) for f in assigned
    )
    active = {fact.student_id for fact in questions} | {fact.student_id for fact in submitted}
    answer_count = sum(f.answered_count for f in submitted)
    return {
        "active_users": len(active),
        "questions": len(questions),
        "sessions": sum(window.includes(f.created_at) for f in chat.sessions),
        "assessments_assigned": len(assigned),
        "assessments_submitted": len(submitted),
        "completion_rate": cohort_completed / len(assigned) if assigned else None,
        "accuracy": sum(f.correct_count for f in submitted) / answer_count if answer_count else None,
        **{
            f"answers_{state}": sum(f.role == "assistant" and f.generation_status == state for f in messages)
            for state in ("completed", "stopped", "error")
        },
    }, active


def _course_name(course_id: str) -> str:
    names = {str(course.course_id): course.display_name for course in course_catalog().list()}
    return names.get(course_id, course_id)


def user_usage(student_id: str) -> tuple[dict, list[dict]]:
    """Account detail totals across retained history, limited to this identity."""
    now = datetime.now(timezone.utc)
    window = StatisticsWindow(datetime(1970, 1, 1, tzinfo=timezone.utc), now + timedelta(microseconds=1), now)
    chat = read_chat_facts(start=window.start.isoformat(), end=window.end.isoformat(), student_id=student_id)
    assessments = read_assessment_facts(
        start=window.start.isoformat(), end=window.end.isoformat(), student_id=student_id
    )
    course_ids = {f.course_id for f in chat.messages} | {f.course_id for f in assessments}
    courses = []
    for course_id in sorted(course_ids):
        messages = tuple(f for f in _deduplicate(chat.messages) if f.course_id == course_id and f.role == "user")
        submitted = tuple(f for f in assessments if f.course_id == course_id and window.includes(f.submitted_at))
        instants = [registration.parse_time(f.created_at) for f in messages] + [
            registration.parse_time(f.submitted_at) for f in submitted
        ]
        courses.append(
            {
                "course_id": course_id,
                "display_name": _course_name(course_id),
                "questions": len(messages),
                "submissions": len(submitted),
                "last_learning_at": max(instants).isoformat() if instants else None,
            }
        )
    instants = [c["last_learning_at"] for c in courses if c["last_learning_at"]]
    return {
        "questions": sum(c["questions"] for c in courses),
        "submissions": sum(c["submissions"] for c in courses),
        "last_learning_at": max(instants, key=registration.parse_time) if instants else None,
    }, courses


def project_user(user: User) -> dict:
    usage, _ = user_usage(user.student_id)
    fields = {
        key: value
        for key, value in asdict(user).items()
        if key not in {"password_hash", "session_version", "invitation_id"}
    }
    return {**fields, "invite_name": registration.invitation_names().get(user.invitation_id), **usage}


def build_statistics(start: date, end: date, course_id: str | None = None) -> dict:
    window = make_window(start, end)
    chat = read_chat_facts(start=window.start.isoformat(), end=window.end.isoformat(), course_id=course_id)
    assessments = read_assessment_facts(start=window.start.isoformat(), end=window.end.isoformat(), course_id=course_id)
    users = models.all_users()
    usage, active = _usage(chat, assessments, window)
    messages = _deduplicate(chat.messages)
    daily = []
    day = start
    while day <= end:
        key = day.isoformat()
        questions = [
            f for f in messages if f.role == "user" and _day(f.created_at) == key and window.includes(f.created_at)
        ]
        submissions = [f for f in assessments if window.includes(f.submitted_at) and _day(f.submitted_at) == key]
        daily.append(
            {
                "date": key,
                "questions": len(questions),
                "submissions": len(submissions),
                "active_users": len({f.student_id for f in questions} | {f.student_id for f in submissions}),
                "new_users": sum(window.includes(u.created_at) and _day(u.created_at) == key for u in users),
            }
        )
        day += timedelta(days=1)
    names = {str(c.course_id): c.display_name for c in course_catalog().list()}
    course_ids = set(names) | {f.course_id for f in chat.messages} | {f.course_id for f in assessments}
    courses = []
    for key in sorted(course_ids):
        if course_id and key != course_id:
            continue
        facts = ChatFacts(
            tuple(f for f in chat.messages if f.course_id == key), tuple(f for f in chat.sessions if f.course_id == key)
        )
        metrics, _ = _usage(facts, tuple(f for f in assessments if f.course_id == key), window)
        courses.append({"course_id": key, "display_name": names.get(key, key), **metrics})
    invite_names = registration.invitation_names()
    sources = {}
    for user in users:
        if not window.includes(user.created_at):
            continue
        source_key = (user.registration_source, user.invitation_id)
        name = invite_names.get(user.invitation_id) or {
            "manual": "管理员创建",
            "open": "开放注册",
            "legacy": "历史来源未知",
        }.get(user.registration_source, "历史来源未知")
        entry = sources.setdefault(source_key, {"name": name, "registered_users": 0, "active_users": 0})
        entry["registered_users"] += 1
        entry["active_users"] += int(user.student_id in active)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - (end - start)
    previous_window = make_window(previous_start, previous_end)
    previous_chat = read_chat_facts(
        start=previous_window.start.isoformat(), end=previous_window.end.isoformat(), course_id=course_id
    )
    previous_assessments = read_assessment_facts(
        start=previous_window.start.isoformat(), end=previous_window.end.isoformat(), course_id=course_id
    )
    previous_usage, _ = _usage(previous_chat, previous_assessments, previous_window)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "Asia/Shanghai",
        "as_of": window.as_of.isoformat(),
        "coverage_note": "统计基于当前保留记录，删除或未持久化的数据不计入。账号数量及新增账号为全站口径；课程筛选作用于学习行为。来源活跃为所选周期新增账号在同周期内的活跃人数。完成率按周期内发布的练习统计截至当前的提交比例。",
        "accounts": {
            "total": len(users),
            "active": sum(u.status == "active" for u in users),
            "disabled": sum(u.status == "disabled" for u in users),
            "new_users": sum(window.includes(u.created_at) for u in users),
            "roles": {role: sum(u.role == role for u in users) for role in ("student", "observer", "admin")},
        },
        "usage": usage,
        "previous": {
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
            "new_users": sum(previous_window.includes(u.created_at) for u in users),
            **{
                key: previous_usage[key]
                for key in ("active_users", "questions", "assessments_submitted", "completion_rate")
            },
        },
        "daily": daily,
        "courses": courses,
        "sources": list(sources.values()),
    }


def build_signals() -> dict:
    """Administrator attention signals composed from persisted facts; never loads message content."""
    now = datetime.now(timezone.utc)
    policy = registration.get_policy()
    total_users = len(models.all_users())
    recent = StatisticsWindow(now - timedelta(days=7), now, now)
    previous = StatisticsWindow(now - timedelta(days=14), now - timedelta(days=7), now)
    messages = _deduplicate(read_chat_facts(start=previous.start.isoformat(), end=recent.end.isoformat()).messages)

    def answers(window: StatisticsWindow, state: str) -> int:
        return sum(
            fact.role == "assistant" and fact.generation_status == state and window.includes(fact.created_at)
            for fact in messages
        )

    return {
        "capacity": {
            "max_users": policy.max_users,
            "total_users": total_users,
            "remaining": max(0, policy.max_users - total_users) if policy.max_users else None,
        },
        "invitations": registration.invitation_summary(),
        "answers": {
            "days": 7,
            "errors": answers(recent, "error"),
            "previous_errors": answers(previous, "error"),
            "completed": answers(recent, "completed"),
        },
    }


def statistics_csv(report: dict) -> str:
    """Export the exact displayed aggregates; escape spreadsheet formula cells."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)

    def row(*values):
        writer.writerow(
            [
                "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v
                for v in values
            ]
        )

    row("section", "item", "metric", "value")
    for key in ("start", "end", "timezone", "as_of", "coverage_note"):
        row("metadata", "", key, report[key])
    for section in ("accounts", "usage"):
        for key, value in report[section].items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    row(section, key, subkey, subvalue)
            else:
                row(section, "", key, value)
    for section, identity in (("daily", "date"), ("courses", "course_id"), ("sources", "name")):
        for entry in report[section]:
            for key, value in entry.items():
                if key != identity:
                    row(section, entry[identity], key, value)
    return "\ufeff" + buffer.getvalue()
