import argparse
import json
import logging
import os
import pathlib
import sys
import time
import traceback
import typing

from sphinx.cmd.build import main


WorkRequest = object
WorkResponse = object


parser = argparse.ArgumentParser(
    fromfile_prefix_chars='@'
)
parser.add_argument("--persistent_worker", action="store_true")


class Worker:

    def __init__(self, instream: "typing.TextIO", outstream: "typing.TextIO"):
        self._instream = instream
        self._outstream = outstream
        self._logger = logging.getLogger("worker")
        logging.basicConfig(filename='echo.log', encoding='utf-8', level=logging.DEBUG)
        self._logger.info("starting worker")

    def run(self) -> None:
        try:
            while True:
                request = None
                try:
                    request = self._get_next_request()
                    if request is None:
                        self._logger.info("Empty request: exiting")
                        break
                    response = self._process_request(request)
                    if response:
                        self._send_response(response)
                except Exception:
                    self._logger.exception("Unhandled error: request=%s", request)
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
        finally:
            self._logger.info("Worker shutting down")

    def _get_next_request(self) -> "object | None":
        line = self._instream.readline()
        if not line:
            return None
        return json.loads(line)

    def _process_request(self, request: "WorkRequest") -> "WorkResponse | None":
        if request.get("cancel"):
            return None
        args = request["arguments"]
        sys.exit(args)
        main(args)
        response = {
            "requestId": request.get("requestId", 0),
            "exitCode": 0,
        }
        return response

    def _send_response(self, response: "WorkResponse") -> None:
        self._outstream.write(json.dumps(response) + "\n")
        self._outstream.flush()


# Request: {'arguments': ['--show-traceback', '--builder', 'html', '--quiet', '--jobs', 'auto', '--silent', '--fail-on-warning', 'bazel-out/k8-fastbuild/bin/docs/_docs/_sources', 'bazel-out/k8-fastbuild/bin/docs/docs/_build/html', '--doctree-dir', 'bazel-out/k8-fastbuild/bin/docs/docs/_build/html/.doctrees'], 'inputs': [{'path': 'bazel-out/k8-fastbuild/bin/docs/_docs/_sources/conf.py', 'digest': 'ZGQ3NmEyMTBiNDgzZThiMzM4ODY5YzE1NmVlMGRjNzQwNmEyZDllYzI5NGM0MGJhZDJmYThiYjY4Mjc3NmE1ZQ=='}, {'path': 'bazel-out/k8-fastbuild/bin/docs/_docs/_sources/doxygen/doxygen/_2public_2pw__async2_2dispatcher_8h_source.html',
# 


if __name__ == "__main__":
    args, unknown = parser.parse_known_args()
    if args.persistent_worker:
        Worker(sys.stdin, sys.stdout).run()
    else:
        sys.exit(main())
