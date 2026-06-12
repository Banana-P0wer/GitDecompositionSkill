import argparse
import pathlib
import re
import subprocess
import sys


def sanitize_commit_for_path(commit):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", commit.strip())
    return safe.strip("._") or "commit"


def default_out_dir(repo, commit):
    repo_path = pathlib.Path(repo).expanduser()
    return repo_path / ".git-dec" / sanitize_commit_for_path(commit)


def run_prep(repo, commit, out_dir):
    prep_path = pathlib.Path(__file__).resolve().with_name("prep.py")
    command = [
        sys.executable,
        str(prep_path),
        "--repo",
        str(repo),
        "--commit",
        commit,
        "--out",
        str(out_dir),
    ]
    return subprocess.run(command, text=True)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Prepare git decomposition input for a repo commit."
    )
    parser.add_argument("--repo", required=True, help="Path to a git repository")
    parser.add_argument("--commit", required=True, help="Commit to prepare")
    parser.add_argument(
        "--out",
        help="Output directory, defaults to <repo>/.git-dec/<commit>",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out_dir = pathlib.Path(args.out).expanduser() if args.out else default_out_dir(
        args.repo, args.commit
    )
    result = run_prep(args.repo, args.commit, out_dir)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
