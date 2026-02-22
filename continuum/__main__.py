import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from rich import print

from continuum.scenario_loader import ScenarioLoader


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


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
        loader = ScenarioLoader()
        try:
            scenario = loader.load(args.workflow)
        except (OSError, ValueError) as err:
            print(f"[bold red]Scenario parse error[/bold red]: {err}")
            raise SystemExit(1) from err

        run_id = _new_run_id()
        run_dir = Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        scenario_file = run_dir / "scenario.yaml"
        summary_file = run_dir / "summary.json"

        scenario_file.write_text(Path(args.workflow).read_text(encoding="utf-8"), encoding="utf-8")
        summary = {
            "run_id": run_id,
            "scenario": {
                "name": scenario.name,
                "rail": scenario.rail,
                "lifecycle": {"start": scenario.lifecycle_start},
                "steps": len(scenario.steps),
                "evidence": {"export": scenario.evidence_export},
            },
            "source": str(Path(args.workflow)),
            "created_at": datetime.now(UTC).isoformat(),
        }
        summary_file.write_text(f"{json.dumps(summary, indent=2)}\n", encoding="utf-8")

        print(f"Scenario: [bold]{scenario.name}[/bold]")
        print(f"Run artifacts: [bold]{run_dir}[/bold]")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
