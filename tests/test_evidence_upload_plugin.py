import json
import unittest
from pathlib import Path

from tests._tmpdir import make_temp_dir, remove_temp_dir
from continuum.plugins import EvidenceUploadPlugin
from continuum.signing import sha256_file


class EvidenceUploadPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("vault")
        self.addCleanup(lambda: remove_temp_dir(self.root))
        self.run_dir = self.root / "runs" / "vault-001"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "manifest.json").write_text(json.dumps({"run": "vault-001"}), encoding="utf-8")
        (self.run_dir / "summary.json").write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
        (self.run_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")

    def _ctx(self) -> dict:
        def step_dir(i: int, name: str) -> str:
            return str(self.run_dir / "evidence" / f"{i+1:02d}-{name.replace(' ', '_')}")

        def write_json(step_path: str, filename: str, payload: dict) -> str:
            p = Path(step_path) / filename
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(p)

        return {
            "run_id": "vault-001",
            "run_dir": str(self.run_dir),
            "vars": {},
            "env": {},
            "step_dir": step_dir,
            "write_json": write_json,
        }

    def test_upload_copies_run_to_vault_by_manifest_sha(self) -> None:
        vault_dir = self.root / "vault"
        result = EvidenceUploadPlugin().run(
            step_name="upload evidence",
            step_with={"vaultDir": str(vault_dir)},
            ctx=self._ctx(),
            step_index=0,
        )
        self.assertTrue(result.ok)
        manifest_sha = sha256_file(self.run_dir / "manifest.json")
        target = vault_dir / manifest_sha
        self.assertTrue(target.is_dir())
        self.assertTrue((target / "manifest.json").is_file())
        self.assertTrue((target / "summary.json").is_file())
        self.assertTrue((target / "report.html").is_file())
        payload = json.loads(Path(result.evidence_paths[0]).read_text(encoding="utf-8"))
        self.assertEqual(payload["manifestSha256"], manifest_sha)
        self.assertIn("vaultUri", payload)

    def test_upload_is_idempotent_without_overwrite(self) -> None:
        vault_dir = self.root / "vault"
        ctx = self._ctx()
        EvidenceUploadPlugin().run(step_name="upload evidence", step_with={"vaultDir": str(vault_dir)}, ctx=ctx, step_index=0)
        result2 = EvidenceUploadPlugin().run(step_name="upload evidence", step_with={"vaultDir": str(vault_dir)}, ctx=ctx, step_index=1)
        self.assertTrue(result2.ok)
        payload2 = json.loads(Path(result2.evidence_paths[0]).read_text(encoding="utf-8"))
        self.assertTrue(payload2.get("skipped"))


if __name__ == "__main__":
    unittest.main()
