"""隔离目录中验证同步边界、删除策略和后台进程生命周期。"""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from sync_agent import AgentMirror, contained_path

TOOLS = Path(__file__).resolve().parent
CONFIG = json.loads((TOOLS / "sync-config.json").read_text(encoding="utf-8-sig"))
AGENT = "cinema-ticketing-backend/cinema-ai"
GATEWAY = "cinema-ticketing-backend/cinema-ai-gateway"


class AgentSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cinema-agent-sync-")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        (self.root / AGENT / "app").mkdir(parents=True)
        (self.root / GATEWAY / "app").mkdir(parents=True)
        self.mirror = AgentMirror(self.root, CONFIG)

    def write(self, relative: str, data: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def wait_until(self, predicate) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        self.fail("后台同步未在 15 秒内完成")

    def test_source_boundaries_include_new_java_and_exclude_credentials_and_runtime(self) -> None:
        self.write(f"{AGENT}/app/new_module.py", b"print('agent')\r\n")
        self.write(f"{GATEWAY}/app/main.py", b"# gateway\n")
        self.write(f"{AGENT}/.env.example", b"API_KEY=\n")
        for relative in [f"{AGENT}/.env", f"{AGENT}/.env.local", f"{AGENT}/data/memory.json",
                         f"{AGENT}/.venv/lib/private.py", f"{AGENT}/secrets/key.txt"]:
            self.write(relative, b"private")
        java = "cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiNewService.java"
        self.write(java, b"class AiNewService {}")
        self.mirror.sync()
        paths = set(self.mirror.source_files())
        self.assertIn(java, paths)
        self.assertEqual((self.mirror.mirror / f"{AGENT}/app/new_module.py").read_bytes(), b"print('agent')\r\n")
        self.assertIn(f"{AGENT}/.env.example", paths)
        self.assertFalse(any("private" in file.read_text() for file in self.mirror.mirror.rglob("*") if file.is_file()))

    def test_modification_rename_and_deletion_manage_only_synced_files(self) -> None:
        source = self.write(f"{AGENT}/app/old.py", b"v1")
        self.mirror.sync()
        unmanaged = self.mirror.mirror / "personal-note.md"
        unmanaged.write_text("keep", encoding="utf-8")
        source.write_bytes(b"v2")
        self.mirror.sync()
        self.assertEqual((self.mirror.mirror / f"{AGENT}/app/old.py").read_bytes(), b"v2")
        source.rename(source.with_name("new.py"))
        self.mirror.sync()
        self.assertFalse((self.mirror.mirror / f"{AGENT}/app/old.py").exists())
        self.assertEqual((self.mirror.mirror / f"{AGENT}/app/new.py").read_bytes(), b"v2")
        self.assertEqual(unmanaged.read_text(), "keep")
        # 重启后仍从清单识别已管理文件，删除能继续传播。
        source.with_name("new.py").unlink()
        AgentMirror(self.root, CONFIG).sync()
        self.assertFalse((self.mirror.mirror / f"{AGENT}/app/new.py").exists())

    def test_missing_source_root_does_not_clear_existing_backup(self) -> None:
        self.write(f"{AGENT}/app/main.py", b"saved")
        self.mirror.sync()
        (self.root / AGENT).rename(self.root / "temporarily-moved")
        with self.assertRaises(FileNotFoundError):
            self.mirror.sync()
        self.assertEqual((self.mirror.mirror / f"{AGENT}/app/main.py").read_bytes(), b"saved")

    def test_unsafe_manifest_path_is_rejected_before_deletion(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        self.mirror.manifest.write_text('Path,Bytes,SHA256\n../../outside.txt,4,x\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            AgentMirror(self.root, CONFIG)
        self.assertEqual(outside.read_text(), "keep")
        with self.assertRaises(ValueError):
            contained_path(self.mirror.mirror, str(outside.resolve()))

    def test_watcher_updates_files_rejects_duplicate_and_stops_cleanly(self) -> None:
        source = self.write(f"{AGENT}/app/main.py", b"first")
        command = [sys.executable, str(TOOLS / "sync_agent.py"), "--project-root", str(self.root)]
        process = subprocess.Popen(command + ["--watch", "--interval", "0.1"], stdout=subprocess.DEVNULL)
        try:
            target = self.mirror.mirror / f"{AGENT}/app/main.py"
            self.wait_until(lambda: target.exists() and target.read_bytes() == b"first")
            source.write_bytes(b"updated")
            self.wait_until(lambda: target.read_bytes() == b"updated")
            duplicate = subprocess.run(command + ["--watch"], capture_output=True, timeout=10)
            self.assertEqual(duplicate.returncode, 0)
            state = subprocess.run(command + ["--status"], capture_output=True, timeout=10)
            self.assertTrue(json.loads(state.stdout)["running"])
            subprocess.run(command + ["--stop"], check=True, capture_output=True, timeout=10)
            self.assertEqual(process.wait(timeout=10), 0)
            state = subprocess.run(command + ["--status"], capture_output=True, timeout=10)
            self.assertFalse(json.loads(state.stdout)["running"])
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
