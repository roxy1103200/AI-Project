"""单向同步 Agent 源码。只操作配置范围及清单中已管理的副本文件。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

BEIJING = timezone(timedelta(hours=8))
DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def timestamp() -> str:
    return datetime.now(BEIJING).isoformat(timespec="seconds")


def is_link(path: Path) -> bool:
    """Windows junctions也可能绕过目录边界，因此一并拒绝。"""
    details = path.lstat()
    return path.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def contained_path(base: Path, relative: str) -> Path:
    """在复制、覆盖、删除前验证完整路径，禁止链接及目录穿越。"""
    name = Path(relative)
    if name.is_absolute() or not name.parts or ".." in name.parts:
        raise ValueError(f"不安全的相对路径：{relative}")
    target = base / name
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"路径超出同步目录：{relative}")
    current = base
    for part in name.parts:
        current /= part
        if current.exists() or current.is_symlink():
            if is_link(current):
                raise ValueError(f"同步路径不能包含链接：{relative}")
    return target


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".agent-sync-", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


class WorkerLock:
    """进程退出时由操作系统释放，PID 文件失效不会阻止下一次启动。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)

    def acquire(self) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def close(self) -> None:
        self.stream.close()


class AgentMirror:
    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        self.root = root.resolve()
        self.config = config
        self.backup = contained_path(self.root, "内部agent")
        self.mirror = contained_path(self.backup, "源文件")
        self.runtime = contained_path(self.backup, ".sync")
        self.mirror.mkdir(parents=True, exist_ok=True)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.manifest = self.backup / "文件清单.csv"
        self.managed: set[str] = set()
        if self.manifest.exists():
            with self.manifest.open(encoding="utf-8-sig", newline="") as stream:
                self.managed = {row["Path"] for row in csv.DictReader(stream)}
        for relative in self.managed:
            contained_path(self.mirror, relative)
        self.last_sync: str | None = None

    def eligible(self, path: Path) -> bool:
        relative = path.relative_to(self.root)
        if any(part.lower() in self.config["excluded_directories"] for part in relative.parts[:-1]):
            return False
        name = path.name.lower()
        if is_link(path):
            return False
        if name.startswith(".env"):
            return name == ".env.example"
        if name in self.config["excluded_files"]:
            return False
        return path.suffix.lower() in self.config["extensions"] or name in self.config["filenames"]

    def source_files(self) -> dict[str, Path]:
        for required in self.config["required_directories"]:
            if not contained_path(self.root, required).is_dir():
                raise FileNotFoundError(f"源目录暂时缺失，保留现有副本：{required}")
        sources: dict[str, Path] = {}
        for directory in self.config["directories"]:
            source_root = contained_path(self.root, directory)
            if not source_root.exists():
                continue
            for current, folders, files in os.walk(source_root, onerror=self.walk_error, followlinks=False):
                current_path = Path(current)
                folders[:] = [name for name in folders if name.lower() not in self.config["excluded_directories"]
                              and not is_link(current_path / name)]
                for name in files:
                    path = current_path / name
                    if self.eligible(path):
                        sources[path.relative_to(self.root).as_posix()] = path
        for pattern in self.config["patterns"]:
            for path in self.root.glob(pattern):
                if path.is_file() and self.eligible(path):
                    relative = path.relative_to(self.root).as_posix()
                    sources[relative] = contained_path(self.root, relative)
        return sources

    @staticmethod
    def walk_error(error: OSError) -> None:
        raise error

    def sync(self) -> dict[str, Any]:
        sources = self.source_files()
        rows: list[dict[str, Any]] = []
        changed = 0
        # 先完成所有读取和复制，再处理删除；读取失败时不会清空旧副本。
        for relative, source in sorted(sources.items()):
            before = source.stat()
            data = source.read_bytes()
            after = source.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise OSError(f"源文件正在写入，下次重试：{relative}")
            digest = hashlib.sha256(data).hexdigest().upper()
            target = contained_path(self.mirror, relative)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest().upper() != digest:
                atomic_write(target, data)
                changed += 1
            rows.append({"Path": relative, "Bytes": len(data), "SHA256": digest})
        removed = self.managed - sources.keys()
        for relative in sorted(removed):
            target = contained_path(self.mirror, relative)
            if target.is_file():
                target.unlink()
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=["Path", "Bytes", "SHA256"], quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
        manifest_data = output.getvalue().encode("utf-8-sig")
        if not self.manifest.exists() or self.manifest.read_bytes() != manifest_data:
            atomic_write(self.manifest, manifest_data)
        self.managed = set(sources)
        self.last_sync = timestamp()
        return {"files": len(rows), "copied": changed, "removed": len(removed), "last_sync": self.last_sync}


def configure_logging(runtime: Path) -> None:
    handler = RotatingFileHandler(runtime / "sync.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def read_status(mirror: AgentMirror) -> dict[str, Any]:
    path = mirror.runtime / "status.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def background_python() -> Path:
    python = Path(sys.executable)
    if os.name != "nt":
        return python
    windowless = python.with_name("pythonw.exe")
    if not windowless.is_file():
        raise FileNotFoundError("当前 Python 安装缺少 pythonw.exe")
    return windowless


def configure_autostart(remove: bool) -> None:
    """仅登记当前用户的启动快捷方式，不更改 PowerShell 执行策略。"""
    if os.name != "nt":
        raise ValueError("登录自动启动安装仅支持 Windows")
    environment = dict(os.environ, AGENT_SYNC_PYTHON=str(background_python()), AGENT_SYNC_SCRIPT=str(Path(__file__).resolve()))
    command = """
    $ErrorActionPreference = 'Stop'
    $link = Join-Path ([Environment]::GetFolderPath('Startup')) 'AI-Project-InternalAgent-Sync.lnk'
    if ($env:AGENT_SYNC_REMOVE -eq '1') {
        if (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link }
    } else {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
        $shortcut.TargetPath = $env:AGENT_SYNC_PYTHON
        $shortcut.Arguments = '"' + $env:AGENT_SYNC_SCRIPT + '" --watch'
        $shortcut.WorkingDirectory = Split-Path $env:AGENT_SYNC_SCRIPT -Parent
        $shortcut.WindowStyle = 7
        $shortcut.Description = 'AI-Project internal Agent source synchronization'
        $shortcut.Save()
    }
    """
    environment["AGENT_SYNC_REMOVE"] = "1" if remove else "0"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], env=environment, check=True)
    print("已移除登录自动启动，当前进程可用 --stop 停止。" if remove else "已配置当前用户登录自动启动。")


def start_background(mirror: AgentMirror, args: argparse.Namespace) -> int:
    command = [str(background_python()), str(Path(__file__).resolve()), "--watch", "--project-root",
               str(mirror.root), "--config", str(args.config.resolve()), "--interval", str(args.interval)]
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = read_status(mirror)
        if state.get("pid") == process.pid and state.get("state") == "watching":
            print(json.dumps(state, ensure_ascii=False))
            return 0
        if process.poll() is not None:
            raise RuntimeError("同步进程提前退出，请查看 内部agent/.sync/sync.log")
        time.sleep(0.25)
    raise RuntimeError("同步进程启动超时，请查看 内部agent/.sync/sync.log")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--stop", action="store_true")
    mode.add_argument("--start", action="store_true")
    mode.add_argument("--install-autostart", action="store_true")
    mode.add_argument("--remove-autostart", action="store_true")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("sync-config.json"))
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval < 0.1:
        parser.error("检查间隔不能小于 0.1 秒")
    if args.install_autostart or args.remove_autostart:
        configure_autostart(args.remove_autostart)
        if args.remove_autostart:
            return 0
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    mirror = AgentMirror(args.project_root, config)
    lock = WorkerLock(mirror.runtime / "worker.lock")
    acquired = lock.acquire()
    try:
        if args.status:
            print(json.dumps({**read_status(mirror), "running": not acquired}, ensure_ascii=False))
            return 0
        if args.stop:
            if not acquired:
                atomic_write(mirror.runtime / "stop", b"stop")
            print("已请求停止同步。" if not acquired else "同步程序未运行。")
            return 0
        if not acquired:
            print("同步程序已经运行，无需重复启动。")
            return 0
        if args.start or args.install_autostart:
            lock.close()
            return start_background(mirror, args)
        configure_logging(mirror.runtime)
        stop = mirror.runtime / "stop"
        stop.unlink(missing_ok=True)
        state: dict[str, Any] = {"pid": os.getpid(), "started_at": timestamp(), "interval_seconds": args.interval}
        logging.info("启动同步 root=%s watch=%s", mirror.root, args.watch)
        last_heartbeat = 0.0
        while True:
            try:
                result = mirror.sync()
                state.update(result, error=None, state="watching" if args.watch else "completed")
                if result["copied"] or result["removed"]:
                    logging.info("同步 files=%s copied=%s removed=%s", result["files"], result["copied"], result["removed"])
            except (OSError, ValueError):
                logging.exception("本轮同步失败，将自动重试")
                state.update(error="同步失败，详见 .sync/sync.log", state="error")
                if not args.watch:
                    write_json(mirror.runtime / "status.json", state)
                    raise
            now = time.monotonic()
            if now - last_heartbeat >= 5 or state["state"] == "error" or not args.watch:
                state["heartbeat"] = timestamp()
                write_json(mirror.runtime / "status.json", state)
                last_heartbeat = now
            if not args.watch:
                print(json.dumps(state, ensure_ascii=False))
                return 0
            if stop.exists():
                state.update(state="stopped", heartbeat=timestamp())
                write_json(mirror.runtime / "status.json", state)
                stop.unlink(missing_ok=True)
                logging.info("已停止同步")
                return 0
            time.sleep(args.interval)
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
