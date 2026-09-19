from ds_course_agent.api.request_quota import ApiRequestQuota


def test_authenticated_business_router_enforces_student_quota(client, monkeypatch):
    import ds_course_agent.api.request_quota as request_quota
    import ds_course_agent.shared.config as config

    monkeypatch.setattr(config, "API_PER_STUDENT_REQUESTS_PER_WINDOW", 1)
    monkeypatch.setattr(config, "API_REQUEST_QUOTA_WINDOW_SECONDS", 3600)
    monkeypatch.setattr(request_quota, "_api_request_quota", ApiRequestQuota())

    first = client.get("/api/sessions", headers={"x-test-student-id": "student-a"})
    blocked = client.get("/api/sessions", headers={"x-test-student-id": "student-a"})
    other_student = client.get("/api/sessions", headers={"x-test-student-id": "student-b"})

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "3600"
    assert other_student.status_code == 200
