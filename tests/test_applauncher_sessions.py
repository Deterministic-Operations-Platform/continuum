import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from continuum.plugins import PluginRegistry
from continuum.sessions import load_sessions, pid_alive


def _wait_dead(pid: int, timeout_sec: float = 3.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return not pid_alive(pid)


class AppLauncherSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(lambda: os.chdir(self._old_cwd))
        self.run_dir = Path("runs") / "test-appl-session"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.registry = PluginRegistry()

    def _ctx(self) -> dict:
        return {
            "run_id": "rof-005",
            "run_dir": str(self.run_dir),
            "vars": {},
            "env": dict(os.environ),
            "step_dir": lambda i, n: str(self.run_dir / "evidence" / f"{i + 1:02d}-{n}"),
            "write_json": self._write_json,
        }

    def _write_json(self, step_dir: str, filename: str, payload: dict) -> str:
        p = Path(step_dir) / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload), encoding="utf-8")
        return str(p)

    def test_ensure_reuse_and_stop_session(self) -> None:
        ensure = self.registry.resolve("applauncher.ensure")
        stop = self.registry.resolve("applauncher.session.stop")
        ctx = self._ctx()

        first = ensure.run(
            step_name="ensure",
            step_with={
                "session": "fednow-rof",
                "command": "python",
                "args": ["-c", "import time; time.sleep(60)"],
                "verifyTimeoutSec": 1,
            },
            ctx=ctx,
            step_index=0,
        )
        second = ensure.run(
            step_name="ensure-again",
            step_with={
                "session": "fednow-rof",
                "command": "python",
                "args": ["-c", "import time; time.sleep(60)"],
                "verifyTimeoutSec": 1,
            },
            ctx=ctx,
            step_index=1,
        )

        self.assertTrue(first.ok)
        self.assertFalse(first.exports["applauncherReused"])
        self.assertTrue(second.ok)
        self.assertTrue(second.exports["applauncherReused"])
        self.assertEqual(first.exports["applauncherPid"], second.exports["applauncherPid"])

        sessions = load_sessions()
        self.assertIn("fednow-rof", sessions)
        self.assertEqual(int(sessions["fednow-rof"]["pid"]), first.exports["applauncherPid"])

        stopped = stop.run(
            step_name="stop-session",
            step_with={"session": "fednow-rof"},
            ctx=ctx,
            step_index=2,
        )

        self.assertTrue(stopped.ok)
        self.assertTrue(stopped.details["stopped"])
        self.assertTrue(_wait_dead(first.exports["applauncherPid"]))
        self.assertNotIn("fednow-rof", load_sessions())

    def test_ensure_restarts_on_fingerprint_change(self) -> None:
        ensure = self.registry.resolve("applauncher.ensure")
        stop = self.registry.resolve("applauncher.session.stop")
        ctx = self._ctx()

        first = ensure.run(
            step_name="ensure",
            step_with={
                "session": "fednow-rof",
                "command": "python",
                "args": ["-c", "import time; time.sleep(60)"],
            },
            ctx=ctx,
            step_index=0,
        )
        second = ensure.run(
            step_name="ensure-new",
            step_with={
                "session": "fednow-rof",
                "command": "python",
                "args": ["-c", "import time; time.sleep(61)"],
            },
            ctx=ctx,
            step_index=1,
        )

        self.assertNotEqual(first.exports["applauncherPid"], second.exports["applauncherPid"])
        self.assertFalse(second.exports["applauncherReused"])
        self.assertTrue(_wait_dead(first.exports["applauncherPid"]))

        stop.run(
            step_name="stop-session",
            step_with={"session": "fednow-rof"},
            ctx=ctx,
            step_index=2,
        )


if __name__ == "__main__":
    unittest.main()
