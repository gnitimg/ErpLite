#!/usr/bin/env python3
"""统一启动/初始化入口：python run.py

一条命令同时启动前端、后端与本地 MySQL 数据库服务。

默认（生产模式）：
  - 本地 MySQL  (127.0.0.1:3307)
  - FastAPI 后端 (http://localhost:8000，同时托管前端 dist)

开发模式：python run.py --dev
  - 本地 MySQL  (127.0.0.1:3307)
  - FastAPI 后端 (http://localhost:8000，仅 API)
  - Vite 前端开发服务器 (http://localhost:3333，代理 /api 到后端)

其他子命令：
  python run.py stop    停止本地 MySQL
  python run.py status  查看本地 MySQL 运行状态

环境要求：
  - Python 3.10+（建议使用项目根目录的 .venv）
  - 本机已安装 mysqld / mysql / mysqladmin 并加入 PATH
  - 开发模式需要 Node.js + pnpm（用于运行前端开发服务器）
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# ───────────────────────── 路径与常量 ─────────────────────────

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
VENV_DIR = ROOT / ".venv"
VENV_PY = VENV_DIR / (Path("Scripts") / "python.exe" if os.name == "nt" else Path("bin") / "python")
FRONTEND_DIST = FRONTEND_DIR / "dist"

MYSQL_PORT = 3307
MYSQL_HOST = "127.0.0.1"
MYSQL_DATA_DIR = ROOT / ".mysql-data"
MYSQL_UNDO_DIR = ROOT / ".mysql-undo"
MYSQL_INITIALIZED_FLAG = ROOT / ".mysql-initialized"
MYSQL_CONFIG = ROOT / ".mysql-local.ini"
MYSQL_INIT_CONFIG = ROOT / ".mysql-init.ini"
MYSQL_PID_FILE = MYSQL_DATA_DIR / "mysql-local.pid"
MYSQL_ERROR_LOG = ROOT / "logs" / "mysql.err.log"
INIT_SQL = ROOT / "database" / "init_mysql.sql"
ROOT_PASSWORD = "LocalRoot@2026!"

BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000
FRONTEND_DEV_PORT = 3333


# ───────────────────────── 工具函数 ─────────────────────────

class Color:
    HEADER = "\033[36m"
    OK = "\033[32m"
    WARN = "\033[33m"
    ERR = "\033[31m"
    RESET = "\033[0m"


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(text: str, color: str) -> str:
    return f"{color}{text}{Color.RESET}" if _supports_color() else text


def info(msg: str) -> None:
    print(_c(f"[ERP] {msg}", Color.HEADER))


def ok(msg: str) -> None:
    print(_c(f"[OK]   {msg}", Color.OK))


def warn(msg: str) -> None:
    print(_c(f"[WARN] {msg}", Color.WARN))


def err(msg: str) -> None:
    print(_c(f"[ERR]  {msg}", Color.ERR), file=sys.stderr)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """静默运行命令，失败时抛出并打印输出片段。"""
    kwargs.setdefault("cwd", str(ROOT))
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        err("命令执行失败: " + " ".join(cmd))
        if result.stdout:
            print(result.stdout[-2000:])
        if result.stderr:
            print(result.stderr[-2000:], file=sys.stderr)
        raise RuntimeError("命令执行失败")
    return result


def which(name: str) -> str | None:
    return shutil.which(name)


def ensure_venv() -> Path:
    """确保项目虚拟环境与后端依赖就绪，返回解释器路径。"""
    if not VENV_PY.exists():
        info("未检测到虚拟环境，正在创建 .venv ...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    info("校验后端依赖 ...")
    run([str(VENV_PY), "-m", "pip", "install", "-r", str(BACKEND_DIR / "requirements.txt")])
    ok("后端依赖就绪。")
    return VENV_PY


# ───────────────────────── 本地 MySQL ─────────────────────────

def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {pid} -ErrorAction SilentlyContinue"],
                capture_output=True, text=True,
            )
            return result.returncode == 0 and str(pid) in (result.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _mysql_running_pid() -> int | None:
    if not MYSQL_PID_FILE.exists():
        return None
    try:
        saved = int(MYSQL_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    return saved if _pid_alive(saved) else None


def _port_listening(host: str, port: int) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _wait_mysql(timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_listening(MYSQL_HOST, MYSQL_PORT):
            return
        time.sleep(0.5)
    raise RuntimeError(f"本地 MySQL 未在 {int(timeout)}s 内就绪，请检查日志：{MYSQL_ERROR_LOG}")


def find_mysql_binaries() -> tuple[str, str, str]:
    mysqld = which("mysqld")
    mysql = which("mysql")
    mysqladmin = which("mysqladmin")
    missing = [n for n, p in (("mysqld", mysqld), ("mysql", mysql), ("mysqladmin", mysqladmin)) if not p]
    if missing:
        err("未在 PATH 中找到 MySQL 可执行文件: " + ", ".join(missing))
        err("请确认本机已安装 MySQL Server 8 并将 bin 目录加入系统 PATH。")
        sys.exit(1)
    return mysqld, mysql, mysqladmin  # type: ignore[return-value]


def start_mysql() -> None:
    mysqld, mysql, _mysqladmin = find_mysql_binaries()
    if _mysql_running_pid():
        ok(f"本地 MySQL 已在运行 (127.0.0.1:{MYSQL_PORT})。")
        return

    MYSQL_DATA_DIR.mkdir(exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)

    base_dir = str(Path(mysqld).resolve().parents[1]).replace("\\", "/")
    # 注：不使用独立的 innodb-undo-directory，让 undo 表空间落在数据目录内，
    # 避免重启时出现 "Can't create UNDO tablespace ... already exists" 冲突。
    MYSQL_CONFIG.write_text(
        "\n".join([
            "[mysqld]",
            f"basedir={base_dir}",
            f"datadir={str(MYSQL_DATA_DIR).replace(chr(92), '/')}",
            f"port={MYSQL_PORT}",
            "bind-address=127.0.0.1",
            "mysqlx=0",
            "innodb_undo_log_truncate=OFF",
            "character-set-server=utf8mb4",
            "collation-server=utf8mb4_0900_ai_ci",
            f"pid-file={str(MYSQL_PID_FILE).replace(chr(92), '/')}",
            f"log-error={str(MYSQL_ERROR_LOG).replace(chr(92), '/')}",
        ]) + "\n",
        encoding="ascii",
    )
    MYSQL_INIT_CONFIG.write_text(
        "\n".join([
            "[mysqld]",
            f"basedir={base_dir}",
            f"datadir={str(MYSQL_DATA_DIR).replace(chr(92), '/')}",
            "innodb_undo_log_truncate=OFF",
        ]) + "\n",
        encoding="ascii",
    )

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    def _heal_undo_files() -> None:
        """清理数据目录内的 undo 文件，规避 MySQL 8.4 在此环境下的启动冲突。

        部分 MySQL 8.4 构建在启动时总是尝试“重新创建”undo 表空间，而非打开
        现有文件，导致报错 “Can't create UNDO tablespace ... ('.\\undo_001' already exists)”。
        undo 文件只存放回滚段，不含业务数据（业务数据在 *.ibd / mysql.ibd），
        因此在每次启动前删除它们、让 InnoDB 重新创建，可同时修复首次启动与后续重启。
        """
        for p in MYSQL_DATA_DIR.glob("undo_*"):
            try:
                p.unlink()
            except OSError:
                pass

    def _launch() -> subprocess.Popen:
        info("启动本地 MySQL ...")
        _heal_undo_files()
        return subprocess.Popen(
            [mysqld, f"--defaults-file={MYSQL_CONFIG}"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _ensure_initialized() -> None:
        if not (MYSQL_DATA_DIR / "mysql").exists():
            info("初始化 MySQL 数据目录（仅首次） ...")
            run([mysqld, f"--defaults-file={MYSQL_INIT_CONFIG}", "--initialize-insecure"])

    _ensure_initialized()
    proc = _launch()
    try:
        _wait_mysql()
    except RuntimeError:
        # 启动失败：若尚未成功初始化过（无标记文件），多为数据目录状态不一致
        # （如旧的独立 undo 目录残留），清空后重新初始化再启动一次。
        proc.wait(timeout=10)
        if not MYSQL_INITIALIZED_FLAG.exists():
            warn("MySQL 启动失败，正在重置数据目录并重新初始化 ...")
            shutil.rmtree(MYSQL_DATA_DIR, ignore_errors=True)
            shutil.rmtree(MYSQL_UNDO_DIR, ignore_errors=True)
            MYSQL_DATA_DIR.mkdir(exist_ok=True)
            _ensure_initialized()
            proc = _launch()
            _wait_mysql()
        else:
            raise

    if not MYSQL_INITIALIZED_FLAG.exists():
        info("导入 ERP 数据库结构（仅首次） ...")
        sql = INIT_SQL.read_text(encoding="utf-8")
        run([mysql, "--protocol=TCP", f"--host={MYSQL_HOST}", f"--port={MYSQL_PORT}", "--user=root", "-e", sql])
        MYSQL_INITIALIZED_FLAG.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")

    ok(f"本地 MySQL 已就绪 (PID {proc.pid}, 127.0.0.1:{MYSQL_PORT})。")


def stop_mysql() -> None:
    _mysqld, _mysql, mysqladmin = find_mysql_binaries()
    pid = _mysql_running_pid()
    if not pid:
        print("本地 MySQL 未运行。")
        return
    env = os.environ.copy()
    env["MYSQL_PWD"] = ROOT_PASSWORD
    try:
        subprocess.run(
            [mysqladmin, "--protocol=TCP", f"--host={MYSQL_HOST}", f"--port={MYSQL_PORT}", "--user=root", "shutdown"],
            env=env, check=False, capture_output=True, text=True,
        )
        ok("本地 MySQL 已停止。")
    except FileNotFoundError:
        warn("未找到 mysqladmin，无法优雅关闭 MySQL。")


def status_mysql() -> int:
    pid = _mysql_running_pid()
    if pid:
        print(_c(f"[OK]   本地 MySQL 正在运行 (PID {pid}, 127.0.0.1:{MYSQL_PORT})。", Color.OK))
        return 0
    print(_c("[WARN] 本地 MySQL 未运行。", Color.WARN))
    return 1


# ───────────────────────── 前端 ─────────────────────────

def ensure_frontend_dist() -> bool:
    """生产模式下构建前端 dist。返回是否成功。"""
    if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
        ok("前端 dist 已存在。")
        return True
    pnpm = which("pnpm") or which("npx")
    if not pnpm:
        err("未检测到 pnpm/npx，无法构建前端。请先安装 Node.js 与 pnpm。")
        return False
    info("构建前端 dist ...")
    try:
        run([pnpm, "install"], cwd=str(FRONTEND_DIR))
        run([pnpm, "run", "build"], cwd=str(FRONTEND_DIR))
        ok("前端构建完成。")
        return True
    except RuntimeError:
        return False


# ───────────────────────── 进程编排 ─────────────────────────

class ProcessGroup:
    """统一管理子进程，收到信号时优雅终止。"""

    def __init__(self) -> None:
        self._procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()
        self._stopped = False

    def add(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.append(proc)

    def stop_all(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            for proc in reversed(self._procs):
                self._terminate(proc)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _wait_http(url: str, timeout: float = 30.0, expect_lt_500: bool = True) -> None:
    import urllib.error
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if not expect_lt_500 or resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"等待 {url} 就绪超时：{last_error}")


def _stream(prefix: str, stream) -> None:
    """将子进程输出带前缀转发到控制台。"""
    try:
        for line in stream:
            text = line.decode(errors="replace").rstrip()
            if text:
                print(f"{prefix} {text}")
    except Exception:
        pass


def start_backend(dev: bool) -> ProcessGroup:
    py = ensure_venv()
    env = os.environ.copy()
    env.setdefault("ERP_MYSQL_HOST", MYSQL_HOST)
    env.setdefault("ERP_MYSQL_PORT", str(MYSQL_PORT))

    info(f"启动后端 (http://{BACKEND_HOST}:{BACKEND_PORT}) ...")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "app.main:app", "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        creationflags=creationflags,
    )
    group = ProcessGroup()
    group.add(proc)
    threading.Thread(target=_stream, args=(_c("[api]  ", Color.HEADER), proc.stdout), daemon=True).start()
    _wait_http(f"http://127.0.0.1:{BACKEND_PORT}/api/dashboard")
    ok("后端已就绪。")
    return group


def start_frontend_dev() -> ProcessGroup:
    group = ProcessGroup()
    pnpm = which("pnpm") or which("npx")
    if not pnpm:
        err("未检测到 pnpm/npx，跳过前端开发服务器。")
        return group
    info(f"启动前端开发服务器 (http://localhost:{FRONTEND_DEV_PORT}) ...")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        [pnpm, "run", "dev"],
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        creationflags=creationflags,
    )
    group.add(proc)
    threading.Thread(target=_stream, args=(_c("[web]  ", Color.HEADER), proc.stdout), daemon=True).start()
    _wait_http(f"http://localhost:{FRONTEND_DEV_PORT}/", expect_lt_500=False)
    ok("前端开发服务器已就绪。")
    return group


# ───────────────────────── 主流程 ─────────────────────────

def cmd_start(args: argparse.Namespace) -> int:
    if not args.dev:
        if not ensure_frontend_dist():
            warn("前端 dist 构建失败，将仅以 API 模式启动后端。")

    start_mysql()
    backend_group = start_backend(args.dev)
    frontend_group = start_frontend_dev() if args.dev else ProcessGroup()

    if args.dev:
        ok(f"开发模式已启动：前端 http://localhost:{FRONTEND_DEV_PORT}  |  后端 http://localhost:{BACKEND_PORT}")
    else:
        ok(f"生产模式已启动：访问 http://localhost:{BACKEND_PORT}")
    warn("按 Ctrl+C 停止全部服务。")

    stop_event = threading.Event()

    def _on_signal(_signum, _frame):
        warn("收到中断信号，正在关闭服务 ...")
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    if os.name != "nt":
        signal.signal(signal.SIGTERM, _on_signal)

    try:
        while not stop_event.is_set():
            if backend_group._procs and backend_group._procs[0].poll() is not None:
                err("后端进程已退出。")
                break
            if args.dev and frontend_group._procs and frontend_group._procs[0].poll() is not None:
                err("前端开发服务器已退出。")
                break
            stop_event.wait(1.0)
    finally:
        frontend_group.stop_all()
        backend_group.stop_all()
        warn("正在停止本地 MySQL ...")
        stop_mysql()
        ok("全部服务已停止。")
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    stop_mysql()
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    return status_mysql()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="ErpLite 统一启动入口：一条命令启动前端、后端与本地 MySQL。",
    )
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="启动数据库、后端与前端（默认生产模式）。")
    start_p.add_argument("--dev", action="store_true", help="开发模式：另起 Vite 前端开发服务器。")
    start_p.set_defaults(func=cmd_start)

    stop_p = sub.add_parser("stop", help="停止本地 MySQL。")
    stop_p.set_defaults(func=cmd_stop)

    status_p = sub.add_parser("status", help="查看本地 MySQL 运行状态。")
    status_p.set_defaults(func=cmd_status)

    # 兼容无子命令：python run.py 等价于 python run.py start
    parser.set_defaults(func=cmd_start, dev=False, command="start")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        err(str(exc))
        return 1
    except KeyboardInterrupt:
        warn("已中断。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


