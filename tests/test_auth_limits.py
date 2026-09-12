"""Login capacity must hold across accounts, peers, and changing identities."""

from __future__ import annotations

from ds_course_agent.api.auth.limits import LoginLimit, LoginRateLimiter


def test_login_limits_share_account_across_peers_and_peer_across_accounts():
    now = [0.0]
    limiter = LoginRateLimiter(clock=lambda: now[0])
    limits = LoginLimit(window_seconds=60, per_account=2, per_ip=3)
    assert limiter.retry_after("alice", "peer1", limits) == 0
    assert limiter.retry_after("alice", "peer2", limits) == 0
    assert limiter.retry_after("alice", "peer3", limits) == 60
    assert limiter.retry_after("bob", "peer1", limits) == 0
    assert limiter.retry_after("carol", "peer1", limits) == 0
    assert limiter.retry_after("dave", "peer1", limits) == 60
    now[0] = 60.0
    assert limiter.retry_after("alice", "peer1", limits) == 0


def test_login_identity_churn_cannot_evict_active_limits():
    now = [0.0]
    limiter = LoginRateLimiter(clock=lambda: now[0], max_keys=2)
    limits = LoginLimit(window_seconds=60, per_account=1, per_ip=1)
    assert limiter.retry_after("alice", "peer1", limits) == 0
    assert limiter.retry_after("bob", "peer2", limits) == 60
    assert limiter.retry_after("alice", "peer1", limits) == 60
    now[0] = 61.0
    assert limiter.retry_after("bob", "peer2", limits) == 0
