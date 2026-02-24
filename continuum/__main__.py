import argparse
import functools
import http.server
import json
from pathlib import Path
import socketserver
import tempfile
from typing import Any

try:
    from rich import print as rich_print
except ModuleNotFoundError:
    rich_print = print

from continuum import __version__, ContinuumError, DeterministicRuntime, EvidenceCollector, PluginRegistry, load_scenario
from continuum.publish import publish_run
from continuum.runtime import build_plan, validate_scenario
from continuum.scenario import load_scenario_document
from continuum.schema import validate_scenario_schema
from continuum.signing import verify_bundle_signature


def _status_payload() -> dict[str, Any]:
    runs_dir = Path("runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    writable = False
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=runs_dir, prefix=".health-", delete=True) as handle:
            handle.write("ok")
            handle.flush()
        writable = True
    except OSError:
        writable = False

    return {
        "status": "ready" if writable else "degraded",
        "version": __version__,
        "cwd": str(Path.cwd()),
        "runs_dir": str(runs_dir.resolve()),
        "runs_dir_writable": writable,
        "commands": ["status", "run", "golden-run", "validate", "plan", "publish", "verify", "ci", "serve"],
        "plugins": sorted(PluginRegistry().available_plugin_names()),
    }


def cmd_verify(run_id: str, runs_dir: str) -> int:
    run_dir = Path(runs_dir) / run_id
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        print(f"run not found: {run_dir}")
        return 2

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    policy_payload = summary.get("policy") if isinstance(summary.get("policy"), dict) else {}
    if "ok" in policy_payload:
        policy_ok = bool(policy_payload.get("ok", False))
        missing = policy_payload.get("missing")
        if not isinstance(missing, list):
            missing = []
    else:
        post = policy_payload.get("post") if isinstance(policy_payload.get("post"), dict) else {}
        policy_ok = bool(post.get("ok", False))
        missing = post.get("violations")
        if not isinstance(missing, list):
            missing = []
    ok_sig, sig_msg = verify_bundle_signature(run_dir)

    print(f"policy.ok={policy_ok} missing={missing}")
    print(f"signature.ok={ok_sig} msg={sig_msg}")
    return 0 if (policy_ok and ok_sig) else 2


def main() -> None:
    parser = argparse.ArgumentParser(prog="continuum", description="Continuum deterministic orchestrator")
    sub = parser.add_subparsers(dest="cmd")

    status = sub.add_parser("status", help="Show current status / health")
    status.add_argument("--json", dest="as_json", action="store_true", help="Output health payload as JSON")

    run = sub.add_parser("run", help="Run a scenario from a YAML/JSON file")
    run.add_argument("scenario", help="Path to scenario YAML/JSON")
    run.add_argument("--run-id", dest="run_id", default=None, help="Optional run id for deterministic replay")
    run.add_argument("--from", dest="from_selector", default=None, help="First step selector to include")
    run.add_argument("--to", dest="to_selector", default=None, help="Last step selector to include")
    run.add_argument("--only", dest="only_selectors", action="append", default=[], help="Selector to include")
    run.add_argument("--skip", dest="skip_selectors", action="append", default=[], help="Selector to skip")
    run.add_argument("--no-cleanup", dest="no_cleanup", action="store_true", help="Do not run cleanup_steps")
    run.add_argument("--resume", dest="resume_run_id", default=None, help="Resume from a previous run id")
    run.add_argument("--rerun", dest="rerun_selectors", action="append", default=[], help="Step selector to force rerun")
    run.add_argument("--from-failure", dest="from_failure", action="store_true", help="Start execution from first failed step in resumed run")
    run.add_argument("--no-services", dest="no_services", action="store_true", help="Skip automatic scenario-level services orchestration")
    run.add_argument("--stop-services", dest="stop_services", action="store_true", help="Stop scenario services at end of run")
    run.add_argument("--reuse-sessions", dest="reuse_sessions", action="store_true", default=True, help="Allow service session reuse (default)")
    run.add_argument("--no-reuse-sessions", dest="reuse_sessions", action="store_false", help="Disable service session reuse")
    run.add_argument("--max-parallel", dest="max_parallel", type=int, default=1, help="Maximum parallel step workers")
    run.add_argument("--actor", dest="actor", default=None, help="Actor identity for RBAC checks")
    run.add_argument("--role", dest="roles", action="append", default=[], help="Actor role (can be repeated)")
    run.add_argument("--approval-file", dest="approval_file", default=None, help="Path to approval file for governance checks")
    run.add_argument("--policy-file", dest="policy_file", default=None, help="Path to policy.yaml for evidence gate checks")

    golden = sub.add_parser("golden-run", help="Run the FedNow/RTPay golden scenario and publish report")
    golden.add_argument("--scenario", dest="scenario", default="scenarios/fednow/rtpay-golden.yaml", help="Golden scenario path")
    golden.add_argument("--run-id", dest="run_id", default=None, help="Optional run id for deterministic replay")
    golden.add_argument("--max-parallel", dest="max_parallel", type=int, default=4, help="Maximum parallel step workers")
    golden.add_argument("--actor", dest="actor", default=None, help="Actor identity for RBAC checks")
    golden.add_argument("--role", dest="roles", action="append", default=["release-manager"], help="Actor role (can be repeated)")
    golden.add_argument("--approval-file", dest="approval_file", default=None, help="Path to approval file for governance checks")
    golden.add_argument("--policy-file", dest="policy_file", default=None, help="Path to policy.yaml for evidence gate checks")
    golden.add_argument("--no-publish", dest="no_publish", action="store_true", help="Run scenario without publishing static report")
    golden.add_argument("--site-dir", dest="site_dir", default="site", help="Directory where static site is generated")

    validate = sub.add_parser("validate", help="Validate scenario without executing")
    validate.add_argument("scenario", help="Path to scenario YAML/JSON")

    plan = sub.add_parser("plan", help="Generate deterministic execution plan without executing")
    plan.add_argument("scenario", help="Path to scenario YAML/JSON")
    plan.add_argument("--run-id", dest="run_id", default=None, help="Run id used for deterministic plan output")

    publish = sub.add_parser("publish", help="Publish a run bundle to a static site folder")
    publish.add_argument("--run-id", dest="run_id", required=True, help="Run id to publish from runs/<run-id>")
    publish.add_argument("--runs-dir", dest="runs_dir", default="runs", help="Directory containing run bundles")
    publish.add_argument("--site-dir", dest="site_dir", default="site", help="Directory where static site is generated")
    publish.add_argument("--keep-runs", dest="keep_runs", type=int, default=25, help="How many published runs to keep")

    verify = sub.add_parser("verify", help="Verify policy + signature for a run bundle")
    verify.add_argument("--run-id", dest="run_id", required=True, help="Run id to verify from runs/<run-id>")
    verify.add_argument("--runs-dir", dest="runs_dir", default="runs", help="Directory containing run bundles")

    ci = sub.add_parser("ci", help="Validate + run + publish in CI mode")
    ci.add_argument("scenario", help="Path to scenario YAML/JSON")
    ci.add_argument("--run-id", dest="run_id", default=None, help="Optional run id for deterministic replay")
    ci.add_argument("--site-dir", dest="site_dir", default="site", help="Directory where static site is generated")
    ci.add_argument("--keep-runs", dest="keep_runs", type=int, default=25, help="How many published runs to keep")
    ci.add_argument("--max-parallel", dest="max_parallel", type=int, default=4, help="Maximum parallel step workers")
    ci.add_argument("--policy-file", dest="policy_file", default=None, help="Path to policy.yaml for evidence gate checks")

    serve = sub.add_parser("serve", help="Serve published site assets locally")
    serve.add_argument("--site-dir", dest="site_dir", default="site", help="Directory containing published site output")
    serve.add_argument("--host", dest="host", default="127.0.0.1", help="Host interface to bind")
    serve.add_argument("--port", dest="port", type=int, default=8080, help="Port to bind")

    args = parser.parse_args()

    if args.cmd == "status":
        payload = _status_payload()
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return
        style = "green" if payload["status"] == "ready" else "yellow"
        rich_print(f"[{style}]Continuum[/{style}] deterministic runtime ready")
        rich_print(f"Version: [bold]{payload['version']}[/bold]")
        rich_print(f"Runs dir: [bold]{payload['runs_dir']}[/bold] (writable={payload['runs_dir_writable']})")
        rich_print(f"Commands: [bold]{', '.join(payload['commands'])}[/bold]")
        rich_print(f"Plugins ({len(payload['plugins'])}): [bold]{', '.join(payload['plugins'])}[/bold]")
        return

    if args.cmd == "run":
        scenario_path = Path(args.scenario)
        try:
            scenario_text = scenario_path.read_text(encoding="utf-8")
            scenario = load_scenario(scenario_path)
            runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
            summary = runtime.execute(
                scenario=scenario,
                scenario_source=scenario_path,
                scenario_text=scenario_text,
                run_id=args.run_id,
                no_services=args.no_services,
                stop_services=args.stop_services,
                reuse_sessions=args.reuse_sessions,
                resume_run_id=args.resume_run_id,
                from_selector=args.from_selector,
                to_selector=args.to_selector,
                only_selectors=tuple(args.only_selectors),
                skip_selectors=tuple(args.skip_selectors),
                no_cleanup=args.no_cleanup,
                rerun_selectors=tuple(args.rerun_selectors),
                from_failure=args.from_failure,
                max_parallel=int(args.max_parallel),
                actor=args.actor,
                actor_roles=tuple(args.roles),
                approval_file=args.approval_file,
                cli_vars={"policyFile": args.policy_file} if args.policy_file else None,
            )
            status_style = "bold green" if summary["status"] == "succeeded" else "bold red"
            rich_print(
                f"Run [bold]{summary['run_id']}[/bold] finished with "
                f"[{status_style}]{summary['status']}[/{status_style}]"
            )
            rich_print(f"Evidence: [bold]{summary['evidence_dir']}[/bold]")
            if summary["failure"]:
                rich_print(f"Failure: [bold red]{summary['failure']['message']}[/bold red]")
                raise SystemExit(1)
        except ContinuumError as err:
            rich_print(f"[bold red]Execution error[/bold red]: {err} ({err.failure_class.value})")
            raise SystemExit(1) from err
        return

    if args.cmd == "golden-run":
        scenario_path = Path(args.scenario)
        try:
            scenario_text = scenario_path.read_text(encoding="utf-8")
            scenario = load_scenario(scenario_path)
            runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
            summary = runtime.execute(
                scenario=scenario,
                scenario_source=scenario_path,
                scenario_text=scenario_text,
                run_id=args.run_id,
                max_parallel=int(args.max_parallel),
                actor=args.actor,
                actor_roles=tuple(args.roles),
                approval_file=args.approval_file,
                cli_vars={"policyFile": args.policy_file} if args.policy_file else None,
            )
            status_style = "bold green" if summary["status"] == "succeeded" else "bold red"
            rich_print(
                f"Golden run [bold]{summary['run_id']}[/bold] finished with "
                f"[{status_style}]{summary['status']}[/{status_style}]"
            )
            rich_print(f"Evidence: [bold]{summary['evidence_dir']}[/bold]")
            if not args.no_publish:
                target = publish_run(run_id=summary["run_id"], runs_dir=Path("runs"), site_dir=Path(args.site_dir), keep_runs=25)
                rich_print(f"[green]Published[/green] golden run to [bold]{target}[/bold]")
                rich_print(f"[green]Index[/green]: [bold]{Path(args.site_dir) / 'index.html'}[/bold]")
            if summary["failure"]:
                rich_print(f"Failure: [bold red]{summary['failure']['message']}[/bold red]")
                raise SystemExit(1)
        except ContinuumError as err:
            rich_print(f"[bold red]Execution error[/bold red]: {err} ({err.failure_class.value})")
            raise SystemExit(1) from err
        return

    if args.cmd == "validate":
        document = load_scenario_document(args.scenario)
        if not isinstance(document, dict):
            rich_print("[red]ERROR[/red] scenario document must be a mapping")
            raise SystemExit(1)
        schema_errors = validate_scenario_schema(document)
        if schema_errors:
            for error in schema_errors:
                rich_print(f"[red]ERROR[/red] schema: {error}")
            raise SystemExit(1)

        scenario = load_scenario(args.scenario)
        errors, warnings = validate_scenario(scenario, plugin_registry=PluginRegistry())
        for warning in warnings:
            rich_print(f"[yellow]WARN[/yellow] {warning}")
        if errors:
            for error in errors:
                rich_print(f"[red]ERROR[/red] {error}")
            raise SystemExit(1)
        rich_print("[green]OK[/green] scenario validates against schema and runtime checks")
        return

    if args.cmd == "plan":
        scenario_path = Path(args.scenario)
        scenario = load_scenario(scenario_path)
        run_id = args.run_id or "plan"
        run_dir = Path("runs") / run_id
        plan_payload = build_plan(scenario, run_id=run_id, run_dir=run_dir)
        print(json.dumps(plan_payload, indent=2, sort_keys=True))
        if args.run_id:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "plan.json").write_text(json.dumps(plan_payload, indent=2, sort_keys=True), encoding="utf-8")
            rich_print(f"[green]Wrote[/green] {run_dir / 'plan.json'}")
        return

    if args.cmd == "publish":
        target = publish_run(
            run_id=args.run_id,
            runs_dir=Path(args.runs_dir),
            site_dir=Path(args.site_dir),
            keep_runs=args.keep_runs,
        )
        rich_print(f"[green]Published[/green] run [bold]{args.run_id}[/bold] to [bold]{target}[/bold]")
        rich_print(f"[green]Index[/green]: [bold]{Path(args.site_dir) / 'index.html'}[/bold]")
        return

    if args.cmd == "verify":
        raise SystemExit(cmd_verify(run_id=args.run_id, runs_dir=args.runs_dir))

    if args.cmd == "ci":
        scenario_path = Path(args.scenario)
        document = load_scenario_document(scenario_path)
        if not isinstance(document, dict):
            rich_print("[red]CI FAIL[/red] scenario document must be a mapping")
            raise SystemExit(1)
        schema_errors = validate_scenario_schema(document)
        if schema_errors:
            for error in schema_errors:
                rich_print(f"[red]CI FAIL[/red] schema: {error}")
            raise SystemExit(1)

        scenario = load_scenario(scenario_path)
        errors, warnings = validate_scenario(scenario, plugin_registry=PluginRegistry())
        for warning in warnings:
            rich_print(f"[yellow]WARN[/yellow] {warning}")
        if errors:
            for error in errors:
                rich_print(f"[red]CI FAIL[/red] {error}")
            raise SystemExit(1)

        try:
            scenario_text = scenario_path.read_text(encoding="utf-8")
            runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
            summary = runtime.execute(
                scenario=scenario,
                scenario_source=scenario_path,
                scenario_text=scenario_text,
                run_id=args.run_id,
                max_parallel=int(args.max_parallel),
                cli_vars={"policyFile": args.policy_file} if args.policy_file else None,
            )
            target = publish_run(run_id=summary["run_id"], runs_dir=Path("runs"), site_dir=Path(args.site_dir), keep_runs=args.keep_runs)
            rich_print(f"[green]CI published[/green] {target}")
            if summary["failure"]:
                rich_print(f"[red]CI FAIL[/red] {summary['failure']['message']}")
                raise SystemExit(1)
            rich_print(f"[green]CI PASS[/green] run {summary['run_id']}")
        except ContinuumError as err:
            rich_print(f"[bold red]CI FAIL[/bold red]: {err} ({err.failure_class.value})")
            raise SystemExit(1) from err

    if args.cmd == "serve":
        site_dir = Path(args.site_dir).resolve()
        if not site_dir.is_dir():
            rich_print(f"[bold red]Site directory not found[/bold red]: {site_dir}")
            raise SystemExit(1)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.ThreadingTCPServer((args.host, int(args.port)), handler) as server:
            url = f"http://{args.host}:{int(args.port)}/"
            rich_print(f"[green]Serving[/green] {site_dir} at [bold]{url}[/bold]")
            rich_print("Press Ctrl+C to stop.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return

    parser.print_help()


if __name__ == "__main__":
    main()
