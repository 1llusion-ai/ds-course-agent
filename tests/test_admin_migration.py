"""One-shot registration and identity migration preserve historical account identity."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from ds_course_agent.api.auth import models, registration
from ds_course_agent.api.auth.contracts import AuthOperationError, RegistrationMode, Role
from ds_course_agent.api.auth.database import AUTH_MIGRATIONS
from ds_course_agent.shared.database import SQLiteMigrationRunner
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
    assert registration.get_registration_mode() == RegistrationMode.CLOSED
    registration.import_legacy_policy(mode=RegistrationMode.INVITE, code="old-invite", expires_at=None)
    assert registration.get_registration_mode() == RegistrationMode.INVITE
    assert registration.list_invitations()[1] == 1
    assert models.get_user_by_username("old").invitation_id is None
    with pytest.raises(AuthOperationError):
        registration.import_legacy_policy(mode=RegistrationMode.OPEN, code="", expires_at=None)
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT code_digest FROM invitations").fetchone()
        assert row[0] != "old-invite"
    with pytest.raises(AuthOperationError):
        models.create_or_update_user(username="old", password_hash="newhash", student_id="other", display_name="Other")
    assert models.get_user_by_username("old").password_hash == "oldhash"


def test_existing_invitation_remains_usable_and_can_restore_display_code(monkeypatch, tmp_path):
    import ds_course_agent.shared.config as config

    path = tmp_path / "auth.db"
    monkeypatch.setattr(config, "AUTH_DB_PATH", str(path))
    SQLiteMigrationRunner(path).apply(AUTH_MIGRATIONS[:2])
    code = "old-invite"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE registration_policy SET mode='invite'")
        conn.execute(
            """INSERT INTO invitations(id,name,note,code_digest,code_hint,max_uses,used_count,created_at)
               VALUES(1,'迁移的原邀请码','历史注册来源未知',?,'••••',1,1,CURRENT_TIMESTAMP)""",
            (registration.code_digest(code),),
        )
        conn.execute(
            """INSERT INTO users(id,username,password_hash,student_id,display_name,registration_source,invitation_id)
               VALUES(1,'old','unused','old','Old','invite',1)"""
        )
        conn.execute("INSERT INTO invitation_uses VALUES(1,1,CURRENT_TIMESTAMP)")

    models.init_db()
    assert models.get_user(1).invitation_id == 1
    invitation = registration.list_invitations()[0][0]
    assert invitation.code is None
    assert invitation.name == "迁移的原注册码"
    assert invitation.used_count == 1 and registration.invitation_status(invitation) == "active"
    user = registration.register_user(username="new", password_hash="unused", invite_code=code)
    assert user.invitation_id == invitation.id
    uses, count = registration.list_uses(invitation.id)
    assert count == registration.list_invitations()[0][0].used_count == 2
    assert {use.username for use in uses} == {"old", "new"}

    admin = models.bootstrap_admin("old")
    with pytest.raises(AuthOperationError, match="与原码不一致"):
        registration.edit_invitation(actor_id=admin.id, invitation_id=invitation.id, code="different")
    assert registration.list_invitations()[0][0].code is None
    registration.edit_invitation(actor_id=admin.id, invitation_id=invitation.id, code=f" {code} ")
    restored = registration.list_invitations()[0][0]
    assert restored.id == invitation.id and restored.code == code and restored.used_count == 2


def test_observer_migrates_to_student_and_cannot_be_reassigned(monkeypatch, tmp_path):
    import ds_course_agent.shared.config as config

    path = tmp_path / "auth.db"
    monkeypatch.setattr(config, "AUTH_DB_PATH", str(path))
    SQLiteMigrationRunner(path).apply(AUTH_MIGRATIONS[:6])
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            """INSERT INTO users(username,password_hash,student_id,display_name,role,session_version)
               VALUES('reader','oldhash','student-1','Reader','observer',4),
                     ('manager','adminhash','student-2','Manager','admin',2)"""
        )

    models.init_db()
    models.init_db()
    reader = models.get_user_by_username("reader")
    assert reader.role == Role.STUDENT and reader.session_version == 5
    assert reader.student_id == "student-1" and reader.password_hash == "oldhash"
    manager = models.get_user_by_username("manager")
    assert manager.role == Role.ADMIN and manager.session_version == 2
    with closing(sqlite3.connect(path)) as conn, conn:
        with pytest.raises(sqlite3.IntegrityError, match="unsupported account role"):
            conn.execute("UPDATE users SET role='observer' WHERE username='reader'")
        with pytest.raises(sqlite3.IntegrityError, match="unsupported account role"):
            conn.execute(
                """INSERT INTO users(username,password_hash,student_id,display_name,role)
                   VALUES('another','hash','student-3','Another','observer')"""
            )


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
    assert registration.get_registration_mode() == RegistrationMode.INVITE
    assert registration.list_invitations()[1] == 1
    assert admin.main(["import-registration", "--confirm", "import-registration"]) == 1
