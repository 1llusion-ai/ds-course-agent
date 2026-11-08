"""One-shot registration and identity migration preserve historical account identity."""

from __future__ import annotations

import sqlite3

import pytest

from ds_course_agent.api.auth import models, registration
from ds_course_agent.api.auth.contracts import AuthOperationError, RegistrationMode, Role
from scripts import admin


def test_existing_accounts_migrate_and_old_registration_imports_only_once(monkeypatch, tmp_path):
    import ds_course_agent.shared.config as config

    path = tmp_path / "auth.db"
    monkeypatch.setattr(config, "AUTH_DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,
                        student_id TEXT NOT NULL,display_name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO users VALUES(1,'old','oldhash','student-1','Old','2025-01-01','2025-01-02')")
    models.init_db()
    models.init_db()
    user = models.get_user_by_username("old")
    assert user.student_id == "student-1" and user.password_hash == "oldhash"
    assert user.created_at == "2025-01-01T00:00:00+00:00"
    assert user.role == Role.STUDENT and user.registration_source == "legacy" and user.last_login_at is None
    assert registration.get_policy().mode == RegistrationMode.CLOSED
    registration.import_legacy_policy(mode=RegistrationMode.INVITE, code="old-invite", expires_at=None, max_users=60)
    assert registration.get_policy().max_users == 60
    assert registration.list_invitations()[1] == 1
    assert models.get_user_by_username("old").invitation_id is None
    with pytest.raises(AuthOperationError):
        registration.import_legacy_policy(mode=RegistrationMode.OPEN, code="", expires_at=None, max_users=0)
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT code_digest FROM invitations").fetchone()
        assert row[0] != "old-invite"
    with pytest.raises(AuthOperationError):
        models.create_or_update_user(username="old", password_hash="newhash", student_id="other", display_name="Other")
    assert models.get_user_by_username("old").password_hash == "oldhash"


def test_admin_command_defaults_to_no_mutation_and_can_read_explicit_legacy_env(monkeypatch, tmp_path):
    import ds_course_agent.shared.config as config

    path = tmp_path / "auth.db"
    monkeypatch.setattr(config, "AUTH_DB_PATH", str(path))
    assert admin.main(["bootstrap", "alice"]) == 0
    assert admin.main(["import-registration"]) == 0
    assert not path.exists()
    monkeypatch.setattr(admin, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("AUTH_REGISTRATION_MODE=invite\nAUTH_INVITE_CODE=legacy-secret\nAUTH_MAX_USERS=17\n")
    for key in ("AUTH_REGISTRATION_MODE", "AUTH_INVITE_CODE", "AUTH_MAX_USERS", "AUTH_INVITE_EXPIRES_AT"):
        monkeypatch.delenv(key, raising=False)
    assert admin.main(["import-registration", "--confirm", "import-registration"]) == 0
    assert registration.get_policy().max_users == 17
    assert registration.list_invitations()[1] == 1
    assert admin.main(["import-registration", "--confirm", "import-registration"]) == 1
