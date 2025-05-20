import os
import sys
import pathlib

def main():
    if len(sys.argv) != 2:
        print("Usage: python verify_persistent_worker_output.py <html_output_dir_path>")
        sys.exit(1)

    html_output_dir = pathlib.Path(sys.argv[1])
    print(f"Verifying Sphinx output in: {html_output_dir.resolve()}")

    errors = []

    # 1. Check for index.html
    index_html_path = html_output_dir / "index.html"
    if not index_html_path.is_file():
        errors.append(f"ERROR: Main output file not found: {index_html_path}")
    else:
        print(f"SUCCESS: Found main output file: {index_html_path}")

    # 2. Check for doctree directory
    # The doctree directory is configured in sphinx.bzl as <output_dir>/.doctrees
    doctree_dir_path = html_output_dir / ".doctrees"
    if not doctree_dir_path.is_dir():
        errors.append(f"ERROR: Doctree directory not found: {doctree_dir_path}")
    else:
        print(f"SUCCESS: Found doctree directory: {doctree_dir_path}")

        # 3. Check for key doctree files
        environment_pickle_path = doctree_dir_path / "environment.pickle"
        if not environment_pickle_path.is_file():
            errors.append(f"ERROR: environment.pickle not found in doctrees: {environment_pickle_path}")
        else:
            print(f"SUCCESS: Found environment.pickle: {environment_pickle_path}")

        # Check for at least one .doctree file (e.g., index.doctree)
        # The exact name depends on the source files. Assuming index.md -> index.doctree
        index_doctree_path = doctree_dir_path / "index.doctree"
        if not index_doctree_path.is_file():
            # Try to find any .doctree file if index.doctree is not present
            found_any_doctree = any(doctree_dir_path.glob("*.doctree"))
            if not found_any_doctree:
                errors.append(f"ERROR: No .doctree files found in {doctree_dir_path}. Expected e.g. {index_doctree_path}")
            else:
                print(f"SUCCESS: Found at least one .doctree file in {doctree_dir_path} (though not necessarily {index_doctree_path}).")

        else:
            print(f"SUCCESS: Found specific doctree file: {index_doctree_path}")


    if errors:
        print("\n".join(errors))
        sys.exit(1)
    else:
        print("All checks passed successfully!")

if __name__ == "__main__":
    main()
