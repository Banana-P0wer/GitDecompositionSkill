import argparse
import json
import pathlib
import subprocess
import sys


def resolve_commit_hash(repo, commit):
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{commit}^{{commit}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"Could not resolve commit: {commit}"
        print(json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        return None
    return result.stdout.strip()


def default_out_dir(repo, commit_hash):
    repo_path = pathlib.Path(repo).expanduser()
    return repo_path / ".git-dec" / commit_hash


def run_prep(repo, commit, out_dir):
    prep_path = pathlib.Path(__file__).resolve().parent / "src" / "prep.py"
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
        help="Output directory, defaults to <repo>/.git-dec/<resolved_commit_sha>",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.out:
        out_dir = pathlib.Path(args.out).expanduser()
    else:
        commit_hash = resolve_commit_hash(args.repo, args.commit)
        if commit_hash is None:
            return 1
        out_dir = default_out_dir(args.repo, commit_hash)

    result = run_prep(args.repo, args.commit, out_dir)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
