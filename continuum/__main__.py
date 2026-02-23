import argparse
from pathlib import Path

try:
    from rich import print as rich_print
except ModuleNotFoundError:
    rich_print = print

from continuum import (
    ContinuumError,
    DeterministicRuntime,
    EvidenceCollector,
    PluginRegistry,
    load_scenario,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="continuum", description="Continuum deterministic orchestrator")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show current status / health")
    run = sub.add_parser("run", help="Run a scenario from a YAML/JSON file")
    run.add_argument("scenario", help="Path to scenario YAML/JSON")
    run.add_argument("--run-id", dest="run_id", default=None, help="Optional run id for deterministic replay")

    args = parser.parse_args()
    if args.cmd == "status":
        rich_print("[bold green]Continuum[/bold green] deterministic runtime ready")
        return

    if args.cmd == "run":
        scenario_path = Path(args.scenario)
        try:
            scenario = load_scenario(scenario_path)
            runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
            summary = runtime.execute(scenario=scenario, scenario_source=scenario_path, run_id=args.run_id)
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

    parser.print_help()


if __name__ == "__main__":
    main()
