import json
from pathlib import Path

from continuum.workflow import parse_workflow, replay_workflow, run_workflow, validate_workflow

DEMO = Path("examples/workflows/demo.yaml")

def test_workflow_parsing():
    wf = parse_workflow(DEMO)
    assert wf.workflow_id == "demo-payment-orchestration"
    assert [s.id for s in wf.steps] == ["intake", "risk-check", "approval", "settlement"]
    assert wf.steps[1].depends_on == ("intake",)

def test_validation():
    wf = parse_workflow(DEMO)
    ok, errors = validate_workflow(wf)
    assert ok
    assert errors == []

def test_run_manifest_creation(tmp_path):
    result = run_workflow(DEMO, run_id="unit-run", runs_dir=tmp_path)
    run_dir = tmp_path / "unit-run"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert result["status"] == "succeeded"
    assert manifest["workflow_id"] == "demo-payment-orchestration"
    assert (run_dir / "validation_result.json").exists()
    assert (run_dir / "evidence_index.json").exists()

def test_hash_chain_generation(tmp_path):
    run_workflow(DEMO, run_id="chain-run", runs_dir=tmp_path)
    chain = json.loads((tmp_path / "chain-run" / "hash_chain.json").read_text())
    assert len(chain) == 4
    assert chain[0]["prev_hash"] == ""
    assert chain[-1]["hash"]
    assert chain[1]["prev_hash"] == chain[0]["hash"]

def test_replay_comparison(tmp_path):
    run_workflow(DEMO, run_id="source", runs_dir=tmp_path)
    report = replay_workflow(tmp_path / "source")
    assert report["ok"] is True
    assert report["drift"] is False
