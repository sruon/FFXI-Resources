"""Discover all dumpers, topologically sort by produces/consumes, run in order."""

import argparse
import importlib.util
import inspect
import os
import subprocess
import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.base import DEFAULT_BASE, DumpScript


def discover() -> dict[str, dict]:
    """Return {dumper_name: {path, produces, consumes}}."""
    found: dict[str, dict] = {}
    for dump_py in sorted((ROOT / "scripts").glob("*/dump.py")):
        name = dump_py.parent.name
        spec = importlib.util.spec_from_file_location(f"_dumper_{name}", dump_py)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = next(
            (
                c for c in vars(module).values()
                if inspect.isclass(c) and issubclass(c, DumpScript) and c is not DumpScript
            ),
            None,
        )
        if cls is None:
            print(f"warn: no DumpScript subclass found in {dump_py}", file=sys.stderr)
            continue
        found[name] = {
            "path": dump_py,
            "produces": list(cls.produces),
            "consumes": list(cls.consumes),
        }
    return found


def order(dumpers: dict[str, dict]) -> list[str]:
    """Topological order: every consumer comes after its producers."""
    producer_of: dict[str, str] = {}
    for name, meta in dumpers.items():
        for art in meta["produces"]:
            if art in producer_of:
                raise ValueError(f"artifact {art!r} produced by both {producer_of[art]} and {name}")
            producer_of[art] = name

    graph: dict[str, set[str]] = {name: set() for name in dumpers}
    for name, meta in dumpers.items():
        for art in meta["consumes"]:
            producer = producer_of.get(art)
            if producer is None:
                raise ValueError(f"{name} consumes {art!r}, but no dumper produces it")
            if producer != name:
                graph[name].add(producer)

    try:
        return list(TopologicalSorter(graph).static_order())
    except CycleError as e:
        raise ValueError(f"dependency cycle: {e.args[1]}") from None


def main():
    parser = argparse.ArgumentParser(description="Run all dumpers in dependency order.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plan", help="Print the planned execution order")

    dump_parser = sub.add_parser("dump", help="Run all dumpers in order")
    dump_parser.add_argument("--version", default="unknown")
    dump_parser.add_argument("--base-path", default=DEFAULT_BASE)
    dump_parser.add_argument("--output-dir", default="dist")

    args = parser.parse_args()
    dumpers = discover()
    plan = order(dumpers)

    if args.command == "plan":
        for name in plan:
            meta = dumpers[name]
            print(f"{name}  produces={meta['produces']}  consumes={meta['consumes']}")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    for name in plan:
        path = dumpers[name]["path"]
        print(f"=== Running scripts/{name}/dump.py ===", flush=True)
        subprocess.run(
            [
                sys.executable, str(path), "dump",
                "--version", args.version,
                "--base-path", args.base_path,
                "--output-dir", args.output_dir,
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
