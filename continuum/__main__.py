import argparse
import json
from pathlib import Path

from rich import print

from continuum import ContinuumError, DeterministicRuntime, EvidenceCollector, PluginRegistry, load_scenario
from continuum.runtime import build_plan, validate_scenario


def main() -> None:
    parser = argparse.ArgumentParser(prog="continuum", description="Continuum deterministic orchestrator")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show current status / health")

    run = sub.add_parser("run", help="Run a scenario from a YAML/JSON file")
    run.add_argument("scenario", help="Path to scenario YAML/JSON")
    run.add_argument("--run-id", dest="run_id", default=None, help="Optional run id for deterministic replay")
    run.add_argument("--from", dest="from_selector", default=None, help="First step selector to include")
    run.add_argument("--to", dest="to_selector", default=None, help="Last step selector to include")
    run.add_argument("--only", dest="only_selectors", action="append", default=[], help="Selector to include")
    run.add_argument("--skip", dest="skip_selectors", action="append", default=[], help="Selector to skip")
    run.add_argument("--no-cleanup", dest="no_cleanup", action="store_true", help="Do not run cleanup_steps")
    run.add_argument("--resume-id", dest="resume_id", default=None, help="Resume from a previous run id")
    run.add_argument("--from-failure", dest="from_failure", action="store_true", help="Resume from first previously failed step")
    run.add_argument("--rerun", dest="rerun_selectors", action="append", default=[], help="Force rerun selector while resuming")
    run.add_argument("--no-services", dest="no_services", action="store_true", help="Skip service provisioning")
    run.add_argument("--stop-services", dest="stop_services", action="store_true", help="Stop services at end of run")
    run.add_argument("--no-reuse-sessions", dest="reuse_sessions", action="store_false", help="Disable service session reuse")
    run.add_argument("--max-parallel", dest="max_parallel", type=int, default=4, help="Maximum concurrent runnable steps")
    run.add_argument("--no-parallel", dest="no_parallel", action="store_true", help="Force sequential step execution")

    validate = sub.add_parser("validate", help="Validate scenario without executing")
    validate.add_argument("scenario", help="Path to scenario YAML/JSON")

    plan = sub.add_parser("plan", help="Generate deterministic execution plan without executing")
    plan.add_argument("scenario", help="Path to scenario YAML/JSON")
    plan.add_argument("--run-id", dest="run_id", default=None, help="Run id used for deterministic plan output")

    args = parser.parse_args()
    if args.cmd == "status":
        print("[bold green]Continuum[/bold green] deterministic runtime ready ✅")
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
                resume_id=args.resume_id,
                from_selector=args.from_selector,
                to_selector=args.to_selector,
                only_selectors=tuple(args.only_selectors),
                skip_selectors=tuple(args.skip_selectors),
                rerun_selectors=tuple(args.rerun_selectors),
                from_failure=args.from_failure,
                no_cleanup=args.no_cleanup,
                max_parallel=args.max_parallel,
                no_parallel=args.no_parallel,
            )
            status_style = "bold green" if summary["status"] == "succeeded" else "bold red"
            print(f"Run [bold]{summary['run_id']}[/bold] finished with [{status_style}]{summary['status']}[/{status_style}]")
            print(f"Evidence: [bold]{summary['evidence_dir']}[/bold]")
            if summary["failure"]:
                print(f"Failure: [bold red]{summary['failure']['message']}[/bold red]")
                raise SystemExit(1)
        except ContinuumError as err:
            print(f"[bold red]Execution error[/bold red]: {err} ({err.failure_class.value})")
            raise SystemExit(1) from err
        return

    if args.cmd == "validate":
        scenario = load_scenario(args.scenario)
        errors, warnings = validate_scenario(scenario, plugin_registry=PluginRegistry())
        for warning in warnings:
            print(f"[yellow]WARN[/yellow] {warning}")
        if errors:
            for error in errors:
                print(f"[red]ERROR[/red] {error}")
            raise SystemExit(1)
        print("[green]OK[/green] scenario validates")
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
            print(f"[green]Wrote[/green] {run_dir / 'plan.json'}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
