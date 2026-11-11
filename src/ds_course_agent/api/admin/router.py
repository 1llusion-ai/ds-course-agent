"""Role-protected administration HTTP API over existing data owners."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ds_course_agent.api.auth import audit, models, registration
from ds_course_agent.api.auth.contracts import (
    AccountStatus,
    Invitation,
    RegistrationMode,
    RegistrationPolicy,
    Role,
    User,
)
from ds_course_agent.api.auth.deps import require_administrator, require_statistics_reader
from ds_course_agent.api.auth.service import hash_password
from ds_course_agent.api.course_context import course_catalog

from .schemas import (
    CreateUserRequest,
    EditInvitationRequest,
    EditUserRequest,
    InvitationRequest,
    PasswordRequest,
    PolicyRequest,
)
from .statistics import LOCAL_TZ, build_signals, build_statistics, project_user, statistics_csv, user_usage


async def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(private_response)])


def _page(items, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _invitation(invitation: Invitation) -> dict:
    return {**asdict(invitation), "status": registration.invitation_status(invitation)}


def _policy() -> dict:
    policy = registration.get_policy()
    total = len(models.all_users())
    return {
        **asdict(policy),
        "total_users": total,
        "remaining_capacity": max(0, policy.max_users - total) if policy.max_users else None,
    }


@router.get("/users")
async def users(
    q: str = Query("", max_length=128),
    role: Role | None = None,
    status: AccountStatus | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _actor: User = Depends(require_administrator),
):
    if created_from and created_to and created_from > created_to:
        raise HTTPException(422, "起始日期不能晚于结束日期")
    items, total = models.list_users(
        q=q,
        role=role,
        status=status,
        page=page,
        page_size=page_size,
        created_from=datetime.combine(created_from, time.min, LOCAL_TZ).isoformat() if created_from else None,
        created_to=datetime.combine(created_to + timedelta(days=1), time.min, LOCAL_TZ).isoformat()
        if created_to
        else None,
    )
    return _page([project_user(user) for user in items], total, page, page_size)


@router.post("/users", status_code=201)
async def create_user(data: CreateUserRequest, actor: User = Depends(require_administrator)):
    user = models.create_managed_user(
        actor_id=actor.id,
        username=data.username,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    return project_user(user)


@router.get("/users/{user_id}")
async def user_detail(user_id: int, _actor: User = Depends(require_administrator)):
    user = models.get_user(user_id)
    _, courses = user_usage(user.student_id)
    return {"user": project_user(user), "courses": courses}


@router.patch("/users/{user_id}")
async def edit_user(user_id: int, data: EditUserRequest, actor: User = Depends(require_administrator)):
    return project_user(models.edit_user(actor_id=actor.id, user_id=user_id, **data.model_dump()))


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, data: PasswordRequest, actor: User = Depends(require_administrator)):
    models.revoke_sessions(actor_id=actor.id, user_id=user_id, password_hash=hash_password(data.password))
    return {"ok": True}


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_sessions(user_id: int, actor: User = Depends(require_administrator)):
    models.revoke_sessions(actor_id=actor.id, user_id=user_id)
    return {"ok": True}


@router.get("/registration-policy")
async def policy(_actor: User = Depends(require_administrator)):
    return _policy()


@router.put("/registration-policy")
async def update_policy(data: PolicyRequest, actor: User = Depends(require_administrator)):
    registration.update_policy(
        actor_id=actor.id, policy=RegistrationPolicy(RegistrationMode(data.mode), data.max_users)
    )
    return _policy()


@router.get("/invitations")
async def invitations(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _actor: User = Depends(require_administrator)
):
    items, total = registration.list_invitations(page=page, page_size=page_size)
    return _page([_invitation(item) for item in items], total, page, page_size)


@router.post("/invitations", status_code=201)
async def create_invitation(data: InvitationRequest, actor: User = Depends(require_administrator)):
    invitation, code = registration.create_invitation(
        actor_id=actor.id,
        name=data.name,
        note=data.note,
        expires_at=data.expires_at.isoformat() if data.expires_at else None,
        max_uses=data.max_uses,
    )
    return {"invitation": _invitation(invitation), "code": code}


@router.patch("/invitations/{invitation_id}")
async def edit_invitation(
    invitation_id: int, data: EditInvitationRequest, actor: User = Depends(require_administrator)
):
    fields = data.model_dump(exclude={"expires_at"})
    invitation = registration.edit_invitation(
        actor_id=actor.id,
        invitation_id=invitation_id,
        **fields,
        change_expiry="expires_at" in data.model_fields_set,
        expires_at=data.expires_at.isoformat() if data.expires_at else None,
    )
    return _invitation(invitation)


@router.get("/invitations/{invitation_id}/uses")
async def invitation_uses(
    invitation_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _actor: User = Depends(require_administrator),
):
    items, total = registration.list_uses(invitation_id, page=page, page_size=page_size)
    return _page([asdict(item) for item in items], total, page, page_size)


@router.get("/audit")
async def audit_log(
    q: str = Query("", max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _actor: User = Depends(require_administrator),
):
    items, total = audit.list_audit(q=q, page=page, page_size=page_size)
    return _page([asdict(item) for item in items], total, page, page_size)


def validate_period(start: date | None, end: date | None, course_id: str | None) -> tuple[date, date]:
    end = end or datetime.now(LOCAL_TZ).date()
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 365:
        raise HTTPException(422, "请选择不超过 366 天的有效日期范围")
    if course_id and course_id not in {str(c.course_id) for c in course_catalog().list()}:
        raise HTTPException(422, "未知课程")
    return start, end


@router.get("/signals")
async def signals(_actor: User = Depends(require_administrator)):
    return build_signals()


@router.get("/statistics")
async def statistics(
    start: date | None = None,
    end: date | None = None,
    course_id: str | None = None,
    _actor: User = Depends(require_statistics_reader),
):
    start, end = validate_period(start, end, course_id)
    return build_statistics(start, end, course_id)


@router.get("/statistics/export")
async def export_statistics(
    start: date | None = None,
    end: date | None = None,
    course_id: str | None = None,
    _actor: User = Depends(require_statistics_reader),
):
    start, end = validate_period(start, end, course_id)
    return Response(
        statistics_csv(build_statistics(start, end, course_id)),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="statistics-{start}-{end}.csv"',
            "Cache-Control": "no-store",
        },
    )
