import argparse
import os
from abc import ABC, abstractmethod

DEFAULT_BASE = r"C:\Program Files (x86)\PlayOnline\SquareEnix\FINAL FANTASY XI"


class DumpScript(ABC):
    @abstractmethod
    def list_files(self) -> list[str]: ...

    @abstractmethod
    def dump(self, version: str, base_path: str, output_dir: str): ...

    def run(self):
        parser = argparse.ArgumentParser(description=self.__class__.__doc__ or "")
        sub = parser.add_subparsers(dest="command", required=True)

        sub.add_parser("list-files", help="Print required DAT files")

        dump_parser = sub.add_parser("dump", help="Run the dump")
        dump_parser.add_argument("--version", default="unknown")
        dump_parser.add_argument("--base-path", default=DEFAULT_BASE)
        dump_parser.add_argument("--output-dir", default="dist")

        args = parser.parse_args()
        if args.command == "list-files":
            for f in sorted(self.list_files()):
                print(f)
        elif args.command == "dump":
            os.makedirs(args.output_dir, exist_ok=True)
            self.dump(args.version, args.base_path, args.output_dir)
