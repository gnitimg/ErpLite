"""Destructive-process tests for an isolated bundled MySQL datadir.

Run explicitly with ERP_LOCAL_MYSQL_SAFETY=1. The test never touches the project's
normal .mysql-data directory or port 3307.
"""

import os
from pathlib import Path
import signal
import subprocess
import time

import pymysql
import pytest

import run as launcher


pytestmark = pytest.mark.skipif(
    os.getenv("ERP_LOCAL_MYSQL_SAFETY") != "1",
    reason="requires an explicitly isolated local MySQL crash-recovery run",
)


def _wait_port_closed(host: str, port: int, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not launcher._port_listening(host, port):
            return
        time.sleep(0.2)
    raise AssertionError(f"port {port} remained open")


def _connect(port: int):
    return pymysql.connect(
        host="127.0.0.1",
        port=port,
        user="lite_erp",
        password="LiteErp@2026!",
        database="lite_erp",
        autocommit=False,
    )


def test_isolated_mysql_crash_restart_and_marker_loss_preserve_data(tmp_path, monkeypatch):
    mysqld = Path(r"E:\MySQL Server 8.4\bin\mysqld.exe")
    mysql = Path(r"E:\MySQL Server 8.4\bin\mysql.exe")
    mysqladmin = Path(r"E:\MySQL Server 8.4\bin\mysqladmin.exe")
    if not all(path.exists() for path in (mysqld, mysql, mysqladmin)):
        pytest.skip("MySQL 8.4 binaries are not installed at the audit location")

    root = tmp_path / "isolated-erp"
    datadir = root / "mysql-data"
    port = 3317
    root.mkdir()
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "MYSQL_PORT", port)
    monkeypatch.setattr(launcher, "MYSQL_DATA_DIR", datadir)
    monkeypatch.setattr(launcher, "MYSQL_PID_FILE", datadir / "mysql-local.pid")
    monkeypatch.setattr(launcher, "MYSQL_CONFIG", root / ".mysql-local.ini")
    monkeypatch.setattr(launcher, "MYSQL_INIT_CONFIG", root / ".mysql-init.ini")
    monkeypatch.setattr(launcher, "MYSQL_INITIALIZED_FLAG", root / ".mysql-initialized")
    monkeypatch.setattr(launcher, "MYSQL_ERROR_LOG", root / "logs" / "mysql.err.log")
    monkeypatch.setattr(
        launcher,
        "find_mysql_binaries",
        lambda: (str(mysqld), str(mysql), str(mysqladmin)),
    )

    assert launcher.start_mysql() is True
    with _connect(port) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE closure_sentinel (id INT PRIMARY KEY, value VARCHAR(40)) ENGINE=InnoDB"
            )
            cursor.execute("INSERT INTO closure_sentinel VALUES (1, 'COMMITTED_A')")
        connection.commit()

    pending = _connect(port)
    with pending.cursor() as cursor:
        cursor.execute("INSERT INTO closure_sentinel VALUES (2, 'UNCOMMITTED_B')")

    undo_before = {
        path.name: path.stat().st_ctime_ns
        for path in datadir.glob("undo_*")
    }
    assert undo_before
    pid = int((datadir / "mysql-local.pid").read_text().strip())
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=True,
            capture_output=True,
        )
    else:
        os.kill(pid, signal.SIGKILL)
    _wait_port_closed("127.0.0.1", port)
    pending.close()

    assert launcher.start_mysql() is True
    with _connect(port) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, value FROM closure_sentinel ORDER BY id")
            assert cursor.fetchall() == ((1, "COMMITTED_A"),)
    assert {
        path.name: path.stat().st_ctime_ns
        for path in datadir.glob("undo_*")
    } == undo_before

    launcher.stop_mysql()
    _wait_port_closed("127.0.0.1", port)
    marker = root / ".mysql-initialized"
    marker.unlink()
    sentinel_file = datadir / "lite_erp" / "closure_sentinel.ibd"
    assert sentinel_file.exists()

    real_wait_mysql = launcher._wait_mysql
    monkeypatch.setattr(
        launcher,
        "_wait_mysql",
        lambda timeout=40: (_ for _ in ()).throw(RuntimeError("injected startup failure")),
    )
    with pytest.raises(RuntimeError, match="未执行任何自动重置"):
        launcher.start_mysql()
    assert datadir.exists()
    assert sentinel_file.exists()

    monkeypatch.setattr(launcher, "_wait_mysql", real_wait_mysql)
    assert launcher.start_mysql() is True
    with _connect(port) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, value FROM closure_sentinel ORDER BY id")
            assert cursor.fetchall() == ((1, "COMMITTED_A"),)
    launcher.stop_mysql()
    _wait_port_closed("127.0.0.1", port)
