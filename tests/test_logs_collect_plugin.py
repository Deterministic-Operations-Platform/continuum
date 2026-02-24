import json
import unittest
from pathlib import Path

from continuum.plugins import LogsCollectPlugin
from tests._tmpdir import make_temp_dir, remove_temp_dir


class LogsCollectPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_temp_dir("continuum-logs")
        self.addCleanup(lambda: remove_temp_dir(self.tmp))

    def _ctx(self) -> dict:
        def _step_dir(index: int, name: str) -> str:
            return str(self.tmp / "runs" / "r1" / "evidence" / f"{index + 1:02d}-{name.replace(' ', '_')}")

        def _write_json(step_path: str, filename: str, payload: dict) -> str:
            out = Path(step_path) / filename
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(out)

        return {"step_dir": _step_dir, "write_json": _write_json, "vars": {"traceId": "trace-123"}, "run_id": "r1"}

    def test_collects_snippets_and_redacts_tokens(self) -> None:
        log = self.tmp / "app.log"
        log.write_text(
            "\n".join(
                [
                    "2026-01-01 00:00:01 INFO startup",
                    "2026-01-01 00:00:02 INFO trace=trace-123 token=secret-value",
                    "2026-01-01 00:00:03 ERROR RuntimeException: boom for trace-123",
                    "  at service.main(line 10)",
                    "  at service.run(line 99)",
                    "",
                    "2026-01-01 00:00:04 INFO done",
                ]
            ),
            encoding="utf-8",
        )

        result = LogsCollectPlugin().run(
            step_name="Collect logs for trace",
            step_with={
                "traceId": "trace-123",
                "maxLines": 500,
                "sources": [{"name": "core-service", "type": "file", "path": str(log)}],
                "match": {"include": ["trace-123", "ERROR", "Exception"]},
            },
            ctx=self._ctx(),
            step_index=0,
        )

        self.assertTrue(result.ok)
        step_dir = self.tmp / "runs" / "r1" / "evidence" / "01-Collect_logs_for_trace"
        snippets_json = json.loads((step_dir / "snippets.json").read_text(encoding="utf-8"))
        snippets_txt = (step_dir / "snippets.txt").read_text(encoding="utf-8")

        self.assertGreater(snippets_json["found"], 0)
        self.assertIn("RuntimeException", snippets_txt)
        self.assertIn("[REDACTED]", snippets_txt)
        self.assertNotIn("secret-value", snippets_txt)

    def test_deterministic_source_ordering(self) -> None:
        logs_dir = self.tmp / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "b.log").write_text("2026-01-01 ERROR trace-123 second", encoding="utf-8")
        (logs_dir / "a.log").write_text("2026-01-01 ERROR trace-123 first", encoding="utf-8")

        LogsCollectPlugin().run(
            step_name="Collect logs",
            step_with={
                "traceId": "trace-123",
                "sources": [{"name": "outbound-service", "type": "dir_glob", "glob": str(logs_dir / "*.log")}],
                "match": {"include": ["trace-123"]},
            },
            ctx=self._ctx(),
            step_index=1,
        )

        step_dir = self.tmp / "runs" / "r1" / "evidence" / "02-Collect_logs"
        sources_json = json.loads((step_dir / "sources.json").read_text(encoding="utf-8"))
        resolved_paths = [item["path"] for item in sources_json["sources"]]
        self.assertEqual(resolved_paths, sorted(resolved_paths))


if __name__ == "__main__":
    unittest.main()
