import argparse

from rich import print

from continuum import ContinuumError, load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(prog="continuum", description="Continuum Orchestrator (starter CLI)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show current status / health")
    run = sub.add_parser("run", help="Run a workflow from a YAML file")
    run.add_argument("workflow", help="Path to workflow YAML")

    args = parser.parse_args()
    if args.cmd == "status":
        print("[bold green]Continuum[/bold green] scaffold is ready ✅")
    elif args.cmd == "run":
        try:
            scenario = load_scenario(args.workflow)
            print(
                f"Loaded scenario [bold]{scenario.name}[/bold] on rail [bold]{scenario.rail}[/bold] "
                f"with {len(scenario.steps)} deterministic step(s)."
            )
        except ContinuumError as err:
            print(f"[bold red]Scenario error[/bold red]: {err} (classification={err.failure_class.value})")
            raise SystemExit(1) from err
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
