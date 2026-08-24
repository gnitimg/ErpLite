from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import DEFAULT_MYSQL_PASSWORD, resolve_database_url
from run import backend_environment


CONFIG_KEYS = (
    "ERP_DATABASE_URL",
    "ERP_MYSQL_HOST",
    "ERP_MYSQL_PORT",
    "ERP_MYSQL_DATABASE",
    "ERP_MYSQL_USER",
    "ERP_MYSQL_PASSWORD",
    "ERP_BUNDLED_LOCAL_MYSQL",
)


@pytest.fixture()
def production_env(monkeypatch):
    monkeypatch.setenv("ERP_ENV", "production")
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_production_without_database_password_fails(production_env):
    with pytest.raises(RuntimeError, match="ERP_MYSQL_PASSWORD"):
        resolve_database_url()


def test_production_external_default_field_password_fails(production_env, monkeypatch):
    monkeypatch.setenv("ERP_MYSQL_PASSWORD", DEFAULT_MYSQL_PASSWORD)
    with pytest.raises(RuntimeError, match="默认"):
        resolve_database_url()


def test_production_strong_field_password_passes(production_env, monkeypatch):
    monkeypatch.setenv("ERP_MYSQL_PASSWORD", "StrongFieldPassword!")
    assert "StrongFieldPassword%21" in resolve_database_url()


def test_production_strong_database_url_passes_without_field_password(production_env, monkeypatch):
    configured = "mysql+pymysql://real_user:StrongUrlPassword%21@db.example/lite_erp"
    monkeypatch.setenv("ERP_DATABASE_URL", configured)
    assert resolve_database_url() == configured


def test_production_default_password_in_external_url_fails(production_env, monkeypatch):
    monkeypatch.setenv(
        "ERP_DATABASE_URL",
        "mysql+pymysql://user:LiteErp%402026%21@db.example/lite_erp",
    )
    with pytest.raises(RuntimeError, match="默认"):
        resolve_database_url()


def test_bundled_loopback_mode_allows_internal_default_password(production_env, monkeypatch):
    monkeypatch.setenv("ERP_BUNDLED_LOCAL_MYSQL", "1")
    monkeypatch.setenv("ERP_MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("ERP_MYSQL_PORT", "3307")
    monkeypatch.setenv("ERP_MYSQL_PASSWORD", DEFAULT_MYSQL_PASSWORD)
    assert "127.0.0.1:3307" in resolve_database_url()


def test_bundled_flag_never_allows_remote_default_password(production_env, monkeypatch):
    monkeypatch.setenv("ERP_BUNDLED_LOCAL_MYSQL", "1")
    monkeypatch.setenv("ERP_MYSQL_HOST", "db.example")
    monkeypatch.setenv("ERP_MYSQL_PASSWORD", DEFAULT_MYSQL_PASSWORD)
    with pytest.raises(RuntimeError, match="默认"):
        resolve_database_url()


def test_run_py_marks_only_its_loopback_mysql_as_bundled(monkeypatch):
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("ERP_ENV", raising=False)
    env = backend_environment(dev=False)
    assert env["ERP_ENV"] == "production"
    assert env["ERP_BUNDLED_LOCAL_MYSQL"] == "1"
    assert env["ERP_MYSQL_HOST"] == "127.0.0.1"
    assert env["ERP_MYSQL_PORT"] == "3307"
    assert env["ERP_MYSQL_PASSWORD"] == DEFAULT_MYSQL_PASSWORD


def test_run_py_does_not_mark_explicit_database_url_as_bundled(monkeypatch):
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "ERP_DATABASE_URL",
        "mysql+pymysql://user:StrongPassword%21@db.example/lite_erp",
    )
    env = backend_environment(dev=False)
    assert "ERP_BUNDLED_LOCAL_MYSQL" not in env
