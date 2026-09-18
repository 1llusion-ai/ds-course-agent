from ds_course_agent.api.auth import models
from ds_course_agent.api.auth.service import hash_password, verify_password
from scripts import reset_user_password


def _seed_user(monkeypatch, tmp_path):
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr("ds_course_agent.api.auth.models.config.AUTH_DB_PATH", str(db_path))
    models.create_or_update_user(
        username="alice",
        password_hash=hash_password("old-password"),
        student_id="alice",
        display_name="alice",
    )


def test_reset_password_requires_username_confirmation(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "wrong")

    assert reset_user_password.main(["alice"]) == 1
    user = models.get_user_by_username("alice")
    assert user is not None
    assert verify_password("old-password", str(user["password_hash"]))


def test_reset_password_updates_hash_after_confirmation(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "alice")
    passwords = iter(["new-password", "new-password"])
    monkeypatch.setattr(reset_user_password.getpass, "getpass", lambda _prompt: next(passwords))

    assert reset_user_password.main(["alice"]) == 0
    user = models.get_user_by_username("alice")
    assert user is not None
    assert verify_password("new-password", str(user["password_hash"]))
    assert not verify_password("old-password", str(user["password_hash"]))
