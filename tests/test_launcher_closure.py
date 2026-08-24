import json
import os
from pathlib import Path
import sys

import pytest
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import run as launcher
import app.main as main_module


DATABASE_KEYS = (
    "ERP_DATABASE_URL",
    "ERP_MYSQL_HOST",
    "ERP_MYSQL_PORT",
    "ERP_MYSQL_DATABASE",
    "ERP_MYSQL_USER",
    "ERP_MYSQL_PASSWORD",
    "ERP_BUNDLED_LOCAL_MYSQL",
    "ERP_JWT_SECRET",
    "ERP_ENV",
)


@pytest.fixture()
def clean_launcher_env(monkeypatch):
    for key in DATABASE_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_bundled_jwt_secret_is_atomic_and_persistent(tmp_path):
    path = tmp_path / ".erp-runtime" / "jwt-secret"
    first = launcher.persistent_local_jwt_secret(path)
    second = launcher.persistent_local_jwt_secret(path)
    assert len(first) == 64
    assert second == first
    assert path.read_text(encoding="ascii") == first
    assert list(path.parent.glob("*.tmp")) == []


def test_backend_environment_prefers_explicit_jwt(clean_launcher_env, monkeypatch):
    monkeypatch.setenv("ERP_JWT_SECRET", "explicit-user-secret")
    monkeypatch.setattr(
        launcher,
        "persistent_local_jwt_secret",
        lambda: pytest.fail("persistent secret must not be read"),
    )
    env = launcher.backend_environment(dev=False)
    assert env["ERP_JWT_SECRET"] == "explicit-user-secret"


def test_backend_environment_persists_only_for_bundled(clean_launcher_env, monkeypatch):
    monkeypatch.setattr(launcher, "persistent_local_jwt_secret", lambda: "a" * 64)
    bundled = launcher.backend_environment(dev=False)
    assert bundled["ERP_JWT_SECRET"] == "a" * 64
    assert bundled["ERP_BUNDLED_LOCAL_MYSQL"] == "1"

    monkeypatch.setenv(
        "ERP_DATABASE_URL",
        "mysql+pymysql://user:StrongPassword%21@db.example/lite_erp",
    )
    external = launcher.backend_environment(dev=False)
    assert "ERP_JWT_SECRET" not in external
    assert "ERP_BUNDLED_LOCAL_MYSQL" not in external


def test_backend_environment_forces_utf8(clean_launcher_env, monkeypatch):
    monkeypatch.setattr(launcher, "persistent_local_jwt_secret", lambda: "b" * 64)
    env = launcher.backend_environment(dev=False)
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_remote_dotenv_skips_bundled_mysql(tmp_path, clean_launcher_env, monkeypatch):
    (tmp_path / ".env").write_text(
        "ERP_DATABASE_URL=mysql+pymysql://user:Strong%21@db.example/lite_erp\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    launcher.load_project_environment()
    assert launcher.uses_bundled_mysql() is False


def test_remote_field_host_skips_bundled_mysql(clean_launcher_env, monkeypatch):
    monkeypatch.setenv("ERP_MYSQL_HOST", "db.example")
    monkeypatch.setenv("ERP_MYSQL_PORT", "3306")
    assert launcher.uses_bundled_mysql() is False


def test_missing_external_config_uses_bundled_mysql(clean_launcher_env):
    assert launcher.uses_bundled_mysql() is True


def test_stale_frontend_dist_runs_checked_build(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    source = frontend / "src"
    dist = frontend / "dist"
    source.mkdir(parents=True)
    dist.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    (frontend / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")
    index = dist / "index.html"
    index.write_text("old", encoding="utf-8")
    source_file = source / "main.ts"
    source_file.write_text("new", encoding="utf-8")
    os.utime(index, (1, 1))
    os.utime(source_file, (2, 2))

    calls = []
    monkeypatch.setattr(launcher, "FRONTEND_DIR", frontend)
    monkeypatch.setattr(launcher, "FRONTEND_DIST", dist)
    monkeypatch.setattr(launcher, "which", lambda name: "pnpm.cmd" if name == "pnpm" else None)
    monkeypatch.setattr(launcher, "run", lambda command, **kwargs: calls.append(command))
    assert launcher.ensure_frontend_dist() is True
    assert calls == [
        ["pnpm.cmd", "install", "--frozen-lockfile"],
        ["pnpm.cmd", "run", "build:checked"],
    ]


def test_stale_frontend_dist_without_pnpm_fails(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    (frontend / "src").mkdir(parents=True)
    monkeypatch.setattr(launcher, "FRONTEND_DIR", frontend)
    monkeypatch.setattr(launcher, "FRONTEND_DIST", frontend / "dist")
    monkeypatch.setattr(launcher, "which", lambda _name: None)
    assert launcher.ensure_frontend_dist() is False


def test_existing_datadir_is_preserved_when_mysql_start_fails(tmp_path, monkeypatch):
    datadir = tmp_path / ".mysql-data"
    (datadir / "mysql").mkdir(parents=True)
    sentinel = datadir / "lite_erp" / "sentinel.ibd"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"business-data")
    undo = datadir / "undo_001"
    undo.write_bytes(b"crash-recovery-data")

    class FailedProcess:
        pid = 123

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 1

        def kill(self):
            return None

    monkeypatch.setattr(launcher, "MYSQL_DATA_DIR", datadir)
    monkeypatch.setattr(launcher, "MYSQL_PID_FILE", datadir / "mysql-local.pid")
    monkeypatch.setattr(launcher, "MYSQL_CONFIG", tmp_path / ".mysql-local.ini")
    monkeypatch.setattr(launcher, "MYSQL_INIT_CONFIG", tmp_path / ".mysql-init.ini")
    monkeypatch.setattr(launcher, "MYSQL_ERROR_LOG", tmp_path / "mysql.err.log")
    monkeypatch.setattr(launcher, "MYSQL_INITIALIZED_FLAG", tmp_path / ".missing-marker")
    monkeypatch.setattr(launcher, "find_mysql_binaries", lambda: ("mysqld", "mysql", "mysqladmin"))
    monkeypatch.setattr(launcher, "_mysql_running_pid", lambda: None)
    monkeypatch.setattr(launcher, "_port_listening", lambda *_args: False)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *_args, **_kwargs: FailedProcess())
    monkeypatch.setattr(launcher, "_wait_mysql", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="未执行任何自动重置"):
        launcher.start_mysql()
    assert sentinel.read_bytes() == b"business-data"
    assert undo.read_bytes() == b"crash-recovery-data"


def test_legacy_hidden_datadir_is_atomically_migrated_without_file_changes(tmp_path, monkeypatch):
    legacy = tmp_path / ".mysql-data"
    sentinel = legacy / "lite_erp" / "sentinel.ibd"
    undo = legacy / "undo_001"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"business-data")
    undo.write_bytes(b"crash-recovery-data")
    sentinel_time = sentinel.stat().st_ctime_ns
    undo_time = undo.stat().st_ctime_ns

    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "MYSQL_DATA_DIR", tmp_path / "mysql-data")
    launcher._migrate_legacy_mysql_datadir()

    assert not legacy.exists()
    assert (tmp_path / "mysql-data" / "lite_erp" / "sentinel.ibd").read_bytes() == b"business-data"
    assert (tmp_path / "mysql-data" / "undo_001").read_bytes() == b"crash-recovery-data"
    assert (tmp_path / "mysql-data" / "lite_erp" / "sentinel.ibd").stat().st_ctime_ns == sentinel_time
    assert (tmp_path / "mysql-data" / "undo_001").stat().st_ctime_ns == undo_time


def test_backend_startup_failure_never_reports_ready(monkeypatch):
    class FailedProcess:
        pid = 456
        stdout = []

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 1

        def kill(self):
            self.terminated = True

    process = FailedProcess()
    stop_commands = []
    monkeypatch.setattr(launcher, "ensure_venv", lambda: Path("python"))
    monkeypatch.setattr(launcher, "backend_environment", lambda _dev: {})
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **_kwargs: stop_commands.append(command),
    )
    monkeypatch.setattr(launcher.threading.Thread, "start", lambda _self: None)
    monkeypatch.setattr(
        launcher,
        "_wait_http",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("migration failed")),
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        launcher.start_backend(dev=False)
    if os.name == "nt":
        assert stop_commands == [["taskkill", "/PID", "456", "/T", "/F"]]
    else:
        assert process.terminated is True


def test_health_reports_ready_only_after_live_database_probe(monkeypatch):
    class HealthyConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return 1

    class HealthyEngine:
        def connect(self):
            return HealthyConnection()

    monkeypatch.setattr(main_module, "engine", HealthyEngine())
    main_module.app.state.database_ready = True
    response = main_module.health()
    assert response == {"status": "ok", "service": "lite-erp", "database": "ready"}


def test_health_returns_503_when_startup_failed():
    main_module.app.state.database_ready = False
    response = main_module.health()
    assert response.status_code == 503
    assert json.loads(response.body)["database"] == "unavailable"


def test_health_returns_503_when_database_drops(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise OperationalError("SELECT 1", {}, Exception("offline"))

    main_module.app.state.database_ready = True
    monkeypatch.setattr(main_module, "engine", BrokenEngine())
    response = main_module.health()
    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "degraded",
        "service": "lite-erp",
        "database": "unavailable",
    }
