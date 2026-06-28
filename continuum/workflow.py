"""Standalone deterministic workflow engine for Continuum v0.1."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib, json, shutil, uuid
from pathlib import Path
from typing import Any

import yaml

class WorkflowError(ValueError):
    pass

@dataclass(frozen=True)
class Contract:
    required_fields: tuple[str, ...] = ()
    equals: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class WorkflowStep:
    id: str
    name: str
    action: str
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outputs: Contract = field(default_factory=Contract)
    evidence: tuple[str, ...] = ()
    validation_gates: tuple[str, ...] = ()

@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    version: str
    inputs: dict[str, Any]
    expected_outputs: dict[str, Any]
    evidence_requirements: tuple[str, ...]
    validation_gates: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)

def _canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()

def sha256_data(data: Any) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()

def load_workflow_document(path: str | Path) -> Any:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        return json.loads(text)
    if p.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    raise WorkflowError("workflow must be .json, .yaml, or .yml")

def _contract(raw: Any) -> Contract:
    if raw is None: raw = {}
    if not isinstance(raw, dict): raise WorkflowError("expected_outputs must be a mapping")
    req = raw.get("required_fields", [])
    eq = raw.get("equals", {})
    if not isinstance(req, list) or not all(isinstance(v, str) and v for v in req):
        raise WorkflowError("expected_outputs.required_fields must be an array of strings")
    if not isinstance(eq, dict): raise WorkflowError("expected_outputs.equals must be a mapping")
    return Contract(tuple(req), dict(eq))

def parse_workflow(path: str | Path) -> Workflow:
    data = load_workflow_document(path)
    if not isinstance(data, dict): raise WorkflowError("workflow document must be a mapping")
    wid = data.get("workflow_id") or data.get("id")
    if not isinstance(wid, str) or not wid.strip(): raise WorkflowError("workflow_id is required")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps: raise WorkflowError("steps must be a non-empty array")
    steps: list[WorkflowStep] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict): raise WorkflowError(f"step {i} must be a mapping")
        sid = raw.get("id") or raw.get("key")
        if not isinstance(sid, str) or not sid.strip(): raise WorkflowError(f"step {i} id is required")
        if sid in seen: raise WorkflowError(f"duplicate step id: {sid}")
        seen.add(sid)
        deps = raw.get("depends_on", raw.get("dependsOn", [])) or []
        evidence = raw.get("evidence", raw.get("evidence_requirements", [])) or []
        gates = raw.get("validation_gates", raw.get("gates", [])) or []
        for label, value in {"depends_on": deps, "evidence": evidence, "validation_gates": gates}.items():
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise WorkflowError(f"step {sid} {label} must be an array of strings")
        steps.append(WorkflowStep(sid, str(raw.get("name") or sid), str(raw.get("action") or "mock"), tuple(deps), dict(raw.get("inputs") or {}), _contract(raw.get("expected_outputs")), tuple(evidence), tuple(gates)))
    unknown = sorted({d for s in steps for d in s.depends_on} - seen)
    if unknown: raise WorkflowError(f"unknown dependencies: {', '.join(unknown)}")
    inputs = data.get("inputs") or {}
    expected = data.get("expected_outputs") or {}
    evidence = data.get("evidence_requirements") or []
    gates = data.get("validation_gates") or []
    if not isinstance(inputs, dict) or not isinstance(expected, dict): raise WorkflowError("inputs and expected_outputs must be mappings")
    if not isinstance(evidence, list) or not isinstance(gates, list): raise WorkflowError("evidence_requirements and validation_gates must be arrays")
    return Workflow(wid.strip(), str(data.get("version") or "0.1"), inputs, expected, tuple(map(str, evidence)), tuple(map(str, gates)), tuple(steps))

def validate_workflow(workflow: Workflow) -> tuple[bool, list[str]]:
    errors: list[str] = []
    step_ids = {s.id for s in workflow.steps}
    for step in workflow.steps:
        for dep in step.depends_on:
            if dep not in step_ids: errors.append(f"{step.id} depends on unknown step {dep}")
        if "evidence-required" in (*workflow.validation_gates, *step.validation_gates) and not (*workflow.evidence_requirements, *step.evidence):
            errors.append(f"{step.id} requires evidence but declares none")
    return not errors, errors

def _topo(steps: tuple[WorkflowStep, ...]) -> list[WorkflowStep]:
    done: set[str] = set(); out: list[WorkflowStep] = []
    remaining = list(steps)
    while remaining:
        ready = [s for s in remaining if set(s.depends_on) <= done]
        if not ready: raise WorkflowError("cyclic dependency detected")
        for s in ready:
            out.append(s); done.add(s.id); remaining.remove(s)
    return out

def _execute_step(step: WorkflowStep, workflow_inputs: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    merged = {"workflow": workflow_inputs, "inputs": step.inputs, "prior": prior}
    output = dict(step.inputs.get("output") or {})
    if step.action in {"mock.approve", "mock.validate", "mock.capture", "mock.settle", "mock"}:
        output.setdefault("status", "approved" if step.action == "mock.approve" else "ok")
        output.setdefault("step_id", step.id)
        output.setdefault("decision", "deterministic")
    else:
        output.setdefault("status", "ok")
    output["input_hash"] = sha256_data(merged)
    return output

def run_workflow(workflow_path: str | Path, *, run_id: str | None = None, runs_dir: Path = Path("runs")) -> dict[str, Any]:
    workflow = parse_workflow(workflow_path)
    ok, errors = validate_workflow(workflow)
    if not ok: raise WorkflowError("; ".join(errors))
    rid = run_id or f"{workflow.workflow_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = runs_dir / rid
    if run_dir.exists(): shutil.rmtree(run_dir)
    (run_dir / "logs").mkdir(parents=True); (run_dir / "inputs").mkdir(); (run_dir / "outputs").mkdir(); (run_dir / "evidence").mkdir()
    source_text = Path(workflow_path).read_text(encoding="utf-8")
    (run_dir / "inputs" / "workflow.yaml").write_text(source_text, encoding="utf-8")
    (run_dir / "inputs_snapshot.json").write_text(_json(workflow.inputs), encoding="utf-8")
    prior: dict[str, Any] = {}; validation = {"ok": True, "errors": []}; evidence_index = []
    chain = []; prev = ""
    started = datetime.now(timezone.utc).isoformat()
    for step in _topo(workflow.steps):
        out = _execute_step(step, workflow.inputs, prior)
        errs = [f"{step.id} missing output field {f}" for f in step.expected_outputs.required_fields if f not in out]
        errs += [f"{step.id} expected {k}={v!r}, got {out.get(k)!r}" for k,v in step.expected_outputs.equals.items() if out.get(k) != v]
        ev_files=[]
        for ev in (*workflow.evidence_requirements, *step.evidence):
            ep = run_dir / "evidence" / f"{step.id}-{ev}.json"; ep.write_text(_json({"step_id": step.id, "type": ev, "output_hash": sha256_data(out)}), encoding="utf-8"); ev_files.append(str(ep.relative_to(run_dir)))
        if "evidence-required" in (*workflow.validation_gates, *step.validation_gates) and not ev_files: errs.append(f"{step.id} missing required evidence")
        if errs: validation["ok"] = False; validation["errors"].extend(errs)
        (run_dir / "outputs" / f"{step.id}.json").write_text(_json(out), encoding="utf-8")
        (run_dir / "logs" / f"{step.id}.log").write_text(f"step={step.id} action={step.action} status={out.get('status')}\n", encoding="utf-8")
        evidence_index.extend({"step_id": step.id, "path": p, "sha256": hashlib.sha256((run_dir/p).read_bytes()).hexdigest()} for p in ev_files)
        record = {"step_id": step.id, "output_sha256": sha256_data(out), "evidence": ev_files, "prev_hash": prev}
        prev = sha256_data(record); record["hash"] = prev; chain.append(record); prior[step.id]=out
        if not validation["ok"]: break
    ended = datetime.now(timezone.utc).isoformat()
    manifest = {"schema":"continuum.run_manifest.v1","run_id":rid,"workflow_id":workflow.workflow_id,"version":workflow.version,"status":"succeeded" if validation["ok"] else "failed","started_at":started,"ended_at":ended,"workflow_source":str(workflow_path),"inputs_sha256":sha256_data(workflow.inputs),"outputs_sha256":sha256_data(prior),"hash_chain_head":prev,"steps":[{"id":s.id,"depends_on":list(s.depends_on)} for s in workflow.steps]}
    for name, payload in {"manifest.json":manifest,"outputs_snapshot.json":prior,"validation_result.json":validation,"evidence_index.json":evidence_index,"hash_chain.json":chain,"summary.json":{"runId":rid,"status":manifest["status"],"startedAt":started,"endedAt":ended}}.items(): (run_dir/name).write_text(_json(payload), encoding="utf-8")
    return {"run_id": rid, "run_dir": str(run_dir), "status": manifest["status"], "validation": validation}

def replay_workflow(run_dir: str | Path) -> dict[str, Any]:
    rd = Path(run_dir)
    manifest = json.loads((rd/"manifest.json").read_text())
    workflow_path = rd/"inputs"/"workflow.yaml"
    current = run_workflow(workflow_path, run_id=f"replay-{manifest['run_id']}", runs_dir=rd.parent)
    prev = json.loads((rd/"outputs_snapshot.json").read_text())
    now = json.loads((Path(current["run_dir"])/"outputs_snapshot.json").read_text())
    drift = prev != now
    report = {"ok": not drift, "source_run_id": manifest["run_id"], "replay_run_id": current["run_id"], "drift": drift, "previous_outputs_sha256": sha256_data(prev), "current_outputs_sha256": sha256_data(now)}
    (Path(current["run_dir"])/"replay_report.json").write_text(_json(report), encoding="utf-8")
    return report
