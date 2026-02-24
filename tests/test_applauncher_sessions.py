import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from continuum.plugins import PluginRegistry
from continuum.sessions import load_sessions
from tests._fakeproc import fake_kill_tree, fake_pid_alive, fake_popen
from tests._tmpdir import make_temp_dir, remove_temp_dir


class AppLauncherSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = make_temp_dir("applauncher")
        self.addCleanup(lambda: remove_temp_dir(self._tmp))
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp)
        self.addCleanup(lambda: os.chdir(self._old_cwd))

        self.run_dir = Path("runs") / "test-appl-session"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.registry = PluginRegistry()

        patches = [
            patch("continuum.plugins.subprocess.Popen", side_effect=fake_popen),
            patch("continuum.plugins.pid_alive", side_effect=fake_pid_alive),
            patch("continuum.plugins.kill_tree", side_effect=fake_kill_tree),
            patch("continuum.sessions.pid_alive", side_effect=fake_pid_alive),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

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
            step_with={"session": "fednow-rof", "command": "python", "args": ["-c", "x"], "verifyTimeoutSec": 1},
            ctx=ctx,
            step_index=0,
        )
        second = ensure.run(
            step_name="ensure-again",
            step_with={"session": "fednow-rof", "command": "python", "args": ["-c", "x"], "verifyTimeoutSec": 1},
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

        stopped = stop.run(
            step_name="stop-session",
            step_with={"session": "fednow-rof"},
            ctx=ctx,
            step_index=2,
        )
        self.assertTrue(stopped.ok)
        self.assertTrue(stopped.details["stopped"])
        self.assertNotIn("fednow-rof", load_sessions())
        self.assertFalse(fake_pid_alive(first.exports["applauncherPid"]))

    def test_ensure_restarts_on_fingerprint_change(self) -> None:
        ensure = self.registry.resolve("applauncher.ensure")
        ctx = self._ctx()

        first = ensure.run(
            step_name="ensure",
            step_with={"session": "fednow-rof", "command": "python", "args": ["-c", "sleep60"]},
            ctx=ctx,
            step_index=0,
        )
        second = ensure.run(
            step_name="ensure-new",
            step_with={"session": "fednow-rof", "command": "python", "args": ["-c", "sleep61"]},
            ctx=ctx,
            step_index=1,
        )

        self.assertNotEqual(first.exports["applauncherPid"], second.exports["applauncherPid"])
        self.assertFalse(second.exports["applauncherReused"])
        self.assertFalse(fake_pid_alive(first.exports["applauncherPid"]))


if __name__ == "__main__":
    unittest.main()
