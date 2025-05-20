import argparse
import json
import logging
import os
import pathlib
import sys
import traceback
from sphinx.cmd.build import main as sphinx_build_main

# Configure basic logging
# In a Bazel worker, logs to stderr are typically captured by Bazel.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - sphinx_build_worker - %(message)s',
    stream=sys.stderr # Explicitly log to stderr
)

def create_argument_parser():
    """
    Creates an ArgumentParser for sphinx-build commands.
    This parser is used by the worker to interpret arguments from JSON requests.
    """
    parser = argparse.ArgumentParser(
        description="Sphinx documentation builder (worker internal parser)",
        add_help=False # sphinx_build_main will handle help requests if it gets --help
    )

    # Worker does not use --persistent_worker internally, it's a startup flag.

    # Positional arguments (required for each build request)
    parser.add_argument("sourcedir", help="Path to source directory.")
    parser.add_argument("outputdir", help="Path to output directory.")
    parser.add_argument("filenames", nargs="*", help="Specific filenames to rebuild.")

    # Standard Sphinx options (mirroring sphinx-build CLI)
    parser.add_argument("-M", dest="make_mode_builder",
                        help="Select a builder in make-mode (e.g., html, latexpdf).")
    parser.add_argument("-b", "--builder", dest="buildername",
                        help="Select a builder (e.g., html, latex).")
    parser.add_argument("-a", "--write-all", action="store_true", dest="write_all",
                        help="Write all output files (default: only new/changed).")
    parser.add_argument("-E", "--fresh-env", action="store_true", dest="fresh_env",
                        help="Rebuild environment completely, discarding saved environment.")
    parser.add_argument("-t", "--tag", dest="tags", action="append", default=[],
                        help="Define a tag TAG (can be used multiple times).")
    parser.add_argument("-d", "--doctree-dir", dest="doctreedir",
                        help="Path to cached doctree pickles directory. Worker will manage this.")
    parser.add_argument("-j", "--jobs", dest="jobs", type=str, default="1",
                        help="Number of parallel jobs (N or 'auto'). Defaults to 1.")
    parser.add_argument("-c", "--conf-dir", dest="confdir", metavar="PATH",
                        help="Path to configuration directory (default: sourcedir).")
    parser.add_argument("-C", "--isolated", action="store_true", dest="isolated",
                        help="Don't look for a configuration file; only take options via -D.")
    parser.add_argument("-D", "--define", dest="defines", action="append", default=[],
                        metavar="SETTING=VALUE",
                        help="Override a conf.py setting (can be used multiple times).")
    parser.add_argument("-A", "--html-define", dest="html_defines", action="append", default=[],
                        metavar="NAME=VALUE",
                        help="Define an HTML template variable (can be used multiple times).")
    parser.add_argument("-n", "--nitpicky", action="store_true", dest="nitpicky",
                        help="Run in nitpicky mode (warn about all missing references).")
    parser.add_argument("-N", "--no-color", action="store_true", dest="no_color",
                        help="Do not emit colored output.")
    parser.add_argument("--color", action="store_true", dest="color",
                        help="Emit colored output (auto-detected by default).")
    parser.add_argument("-v", "--verbose", action="count", default=0, dest="verbosity",
                        help="Increase verbosity (can be used multiple times, e.g., -vv).")
    parser.add_argument("-q", "--quiet", action="store_true", dest="quiet",
                        help="No output on stdout, only warnings/errors on stderr.")
    parser.add_argument("-Q", "--silent", action="store_true", dest="silent",
                        help="No output on stdout, suppress warnings, only errors on stderr.")
    parser.add_argument("-w", "--warning-file", dest="warning_file", metavar="FILE",
                        help="Write warnings/errors to the given file.")
    parser.add_argument("-W", "--fail-on-warning", action="store_true", dest="fail_on_warning",
                        help="Turn warnings into errors.")
    parser.add_argument("--keep-going", action="store_true", dest="keep_going",
                        help="With -W, keep going when warnings occur to report more.")
    parser.add_argument("-T", "--show-traceback", action="store_true", dest="show_traceback",
                        help="Display full traceback on unhandled exception.")
    parser.add_argument("-P", "--pdb", action="store_true", dest="pdb",
                        help="Run PDB on unhandled exception.")
    parser.add_argument("--exception-on-warning", action="store_true", dest="exception_on_warning",
                        help="Raise an exception when a warning is emitted.")
    return parser


class _SerialPersistentWorker:
    def __init__(self, instream, outstream):
        self.instream = instream
        self.outstream = outstream
        self.argument_parser = create_argument_parser()

        # Determine a base directory for doctrees.
        # Try common environment variables for temporary/cache directories.
        # Fallback to a directory within the current working directory if others aren't set.
        # In Bazel, $TMPDIR is usually set for actions.
        tmp_dir_options = [os.environ.get("TMPDIR"), os.environ.get("TEMP"), os.environ.get("TMP")]
        worker_tmp_base_str = next((d for d in tmp_dir_options if d), None)

        if not worker_tmp_base_str:
            # If no standard temp dirs are found, use a relative path.
            # This might be inside a Bazel sandbox execution root.
            worker_tmp_base_str = ".sphinx_worker_cache"
            logging.info(f"No standard temp directory found, using relative path: {worker_tmp_base_str}")

        self.worker_doctrees_root = pathlib.Path(worker_tmp_base_str) / "_sphinx_worker_doctrees"

        try:
            self.worker_doctrees_root.mkdir(parents=True, exist_ok=True)
            logging.info(f"Persistent worker initialized. Doctree root: {self.worker_doctrees_root.resolve()}")
        except Exception as e:
            # If creation fails (e.g., permissions, invalid path), log and potentially disable doctree management or exit.
            # For now, we'll log the error. Subsequent operations might fail if doctree path is unusable.
            logging.error(f"CRITICAL: Could not create or access worker doctree root at "
                          f"{self.worker_doctrees_root.resolve()}: {e}. "
                          f"Doctree caching will likely fail.")
            # Depending on strictness, could raise an exception here to stop the worker.


    def _get_next_request(self):
        line = self.instream.readline()
        if not line:
            return None  # End of stream
        logging.debug(f"Received request line: {line.strip()}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to decode JSON request: {line.strip()}. Error: {e}")
            # Send a response indicating a malformed request if possible,
            # or return a special marker if the protocol supports it.
            # For now, returning None will cause the worker to skip and wait for next.
            return None # Or a specific error marker if protocol allows

    def _send_response(self, response_data):
        response_str = json.dumps(response_data)
        logging.debug(f"Sending response: {response_str}")
        self.outstream.write(response_str + "\n")
        self.outstream.flush()

    def _process_request(self, request_data):
        request_id = request_data.get("requestId", "unknown")
        response_output = [] # For any textual output from Sphinx, if captured.
        exit_code = 1        # Default to error

        try:
            raw_arguments = request_data.get("arguments", [])
            logging.info(f"Request {request_id}: Processing with raw args: {raw_arguments}")

            # Use the worker's parser to interpret the arguments for this specific build.
            # Pass only known args to sphinx_build_main; unknown args cause it to error.
            # However, sphinx itself has args like --help, --version.
            # So, parse_known_args is better, allowing Sphinx to handle its own flags.
            parsed_args, unknown_args_for_sphinx = self.argument_parser.parse_known_args(raw_arguments)

            if not parsed_args.sourcedir or not parsed_args.outputdir:
                raise ValueError("Request arguments must include 'sourcedir' and 'outputdir'.")

            # Construct the argument list for sphinx_build_main (like sys.argv[1:])
            sphinx_argv = []

            # Options
            if parsed_args.make_mode_builder: sphinx_argv.extend(["-M", parsed_args.make_mode_builder])
            elif parsed_args.buildername: sphinx_argv.extend(["-b", parsed_args.buildername]) # M and b are usually exclusive

            if parsed_args.write_all: sphinx_argv.append("-a")
            if parsed_args.fresh_env: sphinx_argv.append("-E") # Important for cache invalidation if needed
            for tag in parsed_args.tags: sphinx_argv.extend(["-t", tag])
            
            # === Doctree Directory Management ===
            # Use the pre-parsed `parsed_args.doctreedir` if the client explicitly set it.
            # Otherwise, manage it internally.
            if parsed_args.doctreedir:
                current_doctreedir = pathlib.Path(parsed_args.doctreedir)
                logging.info(f"Request {request_id}: Using client-specified doctree dir: {current_doctreedir.resolve()}")
            else:
                # Generate a unique key for this build configuration to isolate doctrees.
                # Using resolved paths for consistency.
                norm_sourcedir = pathlib.Path(parsed_args.sourcedir).resolve()
                norm_outputdir = pathlib.Path(parsed_args.outputdir).resolve() # Output dir might not be part of doctree key
                norm_confdir = pathlib.Path(parsed_args.confdir or norm_sourcedir).resolve() # Sphinx defaults confdir to sourcedir

                # Create a hash or a safe string representation for the key.
                # Using path hashing can be robust. For simplicity, join parts of resolved paths.
                # Ensure this key is filesystem-safe.
                key_parts = [
                    str(norm_sourcedir).replace(os.sep, "_"),
                    str(norm_confdir).replace(os.sep, "_"),
                    # Builder name can also be part of the key if doctrees are builder-specific
                    parsed_args.buildername or parsed_args.make_mode_builder or "default_builder"
                ]
                # Simple truncation and hashing for very long paths can be added here.
                doctree_key = "dt_" + "_".join(key_parts).replace(":", "").replace("/", "_").replace("\\", "_")
                max_key_len = 100 # Keep path segments reasonable
                if len(doctree_key) > max_key_len:
                    doctree_key = doctree_key[:max_key_len//2] + "..." + doctree_key[-(max_key_len//2 -3):]
                
                current_doctreedir = self.worker_doctrees_root / doctree_key
            
            current_doctreedir.mkdir(parents=True, exist_ok=True) # Ensure it exists
            sphinx_argv.extend(["-d", str(current_doctreedir)])
            logging.info(f"Request {request_id}: Effective doctree dir: {current_doctreedir.resolve()}")
            # ===================================

            if parsed_args.jobs != "1": sphinx_argv.extend(["-j", str(parsed_args.jobs)])
            if parsed_args.confdir: sphinx_argv.extend(["-c", parsed_args.confdir])
            if parsed_args.isolated: sphinx_argv.append("-C")
            for define in parsed_args.defines: sphinx_argv.extend(["-D", define])
            for html_define in parsed_args.html_defines: sphinx_argv.extend(["-A", html_define])
            if parsed_args.nitpicky: sphinx_argv.append("-n")
            if parsed_args.no_color: sphinx_argv.append("-N")
            elif parsed_args.color: sphinx_argv.append("--color") # Explicit --color overrides no_color
            
            if parsed_args.verbosity > 0: sphinx_argv.append(f"-{'v'*parsed_args.verbosity}")
            if parsed_args.quiet: sphinx_argv.append("-q")
            if parsed_args.silent: sphinx_argv.append("-Q") # Overrides -q and -v
            if parsed_args.warning_file: sphinx_argv.extend(["-w", parsed_args.warning_file])
            if parsed_args.fail_on_warning: sphinx_argv.append("-W")
            if parsed_args.keep_going: sphinx_argv.append("--keep-going")
            if parsed_args.show_traceback: sphinx_argv.append("-T")
            if parsed_args.pdb: sphinx_argv.append("-P")
            if parsed_args.exception_on_warning: sphinx_argv.append("--exception-on-warning")

            # Positional arguments for Sphinx
            sphinx_argv.append(parsed_args.sourcedir)
            sphinx_argv.append(parsed_args.outputdir)
            sphinx_argv.extend(parsed_args.filenames) # Add any specified filenames

            # Add any arguments not parsed by our definition, so Sphinx can handle them (e.g., --version, --help)
            sphinx_argv.extend(unknown_args_for_sphinx)
            
            logging.info(f"Request {request_id}: Invoking sphinx.cmd.build.main with argv: {sphinx_argv}")
            
            # Note: Capturing stdout/stderr from sphinx_build_main directly can be complex
            # as it might interfere with the worker's own logging or I/O.
            # For now, relying on sphinx_build_main's exit code and its own logging (to stderr).
            # The 'output' field in the JSON response will be minimal unless specific capture is implemented.
            
            exit_code = sphinx_build_main(sphinx_argv)
            logging.info(f"Request {request_id}: sphinx.cmd.build.main finished with exit code {exit_code}.")

        except ValueError as ve: # For errors like missing sourcedir/outputdir
            logging.error(f"Request {request_id}: Argument validation error: {ve}")
            exit_code = 2 # Specific exit code for bad arguments in request
            response_output.append(f"Argument error: {ve}")
        except Exception as e:
            logging.error(f"Request {request_id}: Unhandled exception during processing: {e}\n{traceback.format_exc()}")
            exit_code = 1 # General error
            response_output.append(f"Unhandled exception: {e}\n{traceback.format_exc()}")
        
        self._send_response({
            "requestId": request_id,
            "exitCode": exit_code,
            "output": "\n".join(response_output) # This is mainly for error messages now
        })

    def run(self):
        logging.info("Persistent worker run loop started. Waiting for requests on stdin...")
        while True:
            request = self._get_next_request()
            if request is None:
                # This can mean EOF or a JSON decode error that returned None.
                # If EOF, it's a signal to exit. If error, worker might be stuck.
                # For robustness, log and decide whether to continue or break.
                # Assuming EOF means clean shutdown.
                logging.info("Input stream closed or invalid request received. Exiting worker run loop.")
                break 
            self._process_request(request)
        logging.info("Persistent worker run loop finished.")


if __name__ == "__main__":
    # This initial parsing is only to detect the --persistent_worker flag.
    # All other arguments are passed either to sphinx_build_main directly
    # or through the JSON requests to the worker.
    
    # Use a simple parser that doesn't conflict with Sphinx's own argument parsing.
    # It only looks for --persistent_worker and ignores other arguments.
    startup_parser = argparse.ArgumentParser(add_help=False)
    startup_parser.add_argument("--persistent_worker", action="store_true")
    
    # Parse only the known args for this initial parser.
    # `sys.argv[1:]` contains all command-line arguments after the script name.
    cli_args = sys.argv[1:]
    initial_parsed_args, remaining_argv = startup_parser.parse_known_args(cli_args)

    if initial_parsed_args.persistent_worker:
        logging.info("Starting in persistent worker mode.")
        # In persistent worker mode, communication is via stdin/stdout.
        # All other command-line arguments received at startup are ignored by the worker itself;
        # build arguments come from JSON requests.
        worker = _SerialPersistentWorker(sys.stdin, sys.stdout)
        worker.run()
        sys.exit(0) # Clean exit for worker
    else:
        # Not in persistent worker mode.
        # Execute sphinx.cmd.build.main directly with all original command-line arguments.
        # `cli_args` (which is `sys.argv[1:]`) is what sphinx_build_main expects.
        logging.info(f"Running sphinx.cmd.build.main directly with args: {cli_args}")
        sys.exit(sphinx_build_main(cli_args))
