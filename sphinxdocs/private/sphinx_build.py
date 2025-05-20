import argparse
import json
import os
import pathlib
import sys
import typing

import sphinx


def _create_parser() -> "argparse.Namespace":
    parser = argparse.ArgumentParser(fromfile_prefix_chars="@")
    parser.add_argument("--persistent_worker", action="store_true")
    return parser


JsonWorkRequest = object
JsonWorkResponse = object


class _PersistentWorker:
    """Synchronous, serial persistent worker."""

    def __init__(self, instream: "typing.TextIO", outstream: "typing.TextIO"):
        self._instream = instream
        self._outstream = outstream

    def run(self) -> None:
        try:
            while True:
                request = None
                try:
                    request = self._get_next_request()
                    if request is None:
                        break
                    response = self._process_request(request)
                    if response:  # May be none for cancel request
                        self._send_response(response)
                except Exception:
                    output = (
                        f"Unhandled error:\nRequest: {request}\n"
                        + traceback.format_exc()
                    )
                    request_id = 0 if not request else request.get("requestId", 0)
                    self._send_response(
                        {
                            "exitCode": 3,
                            "output": output,
                            "requestId": request_id,
                        }
                    )

    def _get_next_request(self) -> "object | None":
        line = self._instream.readline()
        if not line:
            return None
        return json.loads(line)

    def _process_request(self, request: "JsonWorkRequest") -> "JsonWorkResponse | None":
        if request.get("cancel"):
            return None
        sphinx.cmd.build.main()
        response = {
            "requestId": request.get("requestId", 0),
            "exitCode": 0,
        }
        return response

    def _send_response(self, response: "JsonWorkResponse") -> None:
        self._outstream.write(json.dumps(response) + "\n")
        self._outstream.flush()


def main(args: "list[str]") -> int:
    options = _create_parser().parse_args(args)
    if options.persistent_worker:
        _PersistentWorker(sys.stdin, sys.stdout).run()
    else:
        sphinx.cmd.build.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
