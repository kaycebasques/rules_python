import argparse
import os
import pathlib
import sys

from sphinx.cmd.build import main


def _create_parser() -> "argparse.Namespace":
    parser = argparse.ArgumentParser(fromfile_prefix_chars="@")
    parser.add_argument("--persistent_worker", action="store_true")
    return parser


JsonWorkerRequest = object
JsonWorkerResponse = object


def _main(args: "list[str]") -> int:
    options = _create_parser().parse_args(args)
    if options.persistent_worker:
        main(["python3", "-m", "sphinx", "build", "-M", "man")
    else:
        main()
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
