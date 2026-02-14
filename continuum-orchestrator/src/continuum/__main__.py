import argparse
from rich import print

def main():
    parser = argparse.ArgumentParser(prog="continuum", description="Continuum Orchestrator (starter CLI)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show current status / health")
    run = sub.add_parser("run", help="Run a workflow from a YAML file")
    run.add_argument("workflow", help="Path to workflow YAML")

    args = parser.parse_args()
    if args.cmd == "status":
        print("[bold green]Continuum[/bold green] scaffold is ready ✅")
    elif args.cmd == "run":
        print(f"Would run workflow: [bold]{args.workflow}[/bold] (stub)")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
