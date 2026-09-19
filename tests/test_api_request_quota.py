from ds_course_agent.api import request_quota
from ds_course_agent.api.request_quota import ApiRequestQuota


def test_api_request_quota_is_per_student_and_expires(monkeypatch):
    quota = ApiRequestQuota()
    now = [100.0]
    monkeypatch.setattr(request_quota.time, "monotonic", lambda: now[0])

    assert quota.try_acquire(student_id="alice", limit=1, window_seconds=10).allowed
    blocked = quota.try_acquire(student_id="alice", limit=1, window_seconds=10)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 10
    assert quota.try_acquire(student_id="bob", limit=1, window_seconds=10).allowed

    now[0] = 110.0
    assert quota.try_acquire(student_id="alice", limit=1, window_seconds=10).allowed


def test_api_request_quota_disabled_does_not_reserve_requests():
    quota = ApiRequestQuota()

    for _ in range(3):
        assert quota.try_acquire(student_id="alice", limit=0, window_seconds=10).allowed
