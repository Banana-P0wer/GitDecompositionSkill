import argparse
import json
import pathlib
import re
import subprocess
import sys


class PrepError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise PrepError(message)


STATUS_MAP = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
}


FILE_KIND_MAP = {
    "modified": "file_modified",
    "added": "file_added",
    "deleted": "file_deleted",
    "renamed": "file_rename",
    "copied": "file_copy",
    "unknown": "file_unknown",
}


HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@.*$"
)


def run_git(repo, args):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise PrepError(f"Failed to run git: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        command = "git -C <repo> " + " ".join(args)
        if stderr:
            raise PrepError(f"{command} failed: {stderr}")
        raise PrepError(f"{command} failed with exit code {result.returncode}")

    return result.stdout


def validate_repo(repo):
    repo_path = pathlib.Path(repo).expanduser()
    if not repo_path.exists():
        raise PrepError(f"--repo does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise PrepError(f"--repo is not a directory: {repo_path}")

    try:
        inside = run_git(repo_path, ["rev-parse", "--is-inside-work-tree"]).strip()
        top_level = run_git(repo_path, ["rev-parse", "--show-toplevel"]).strip()
    except PrepError as exc:
        raise PrepError(f"--repo is not a git repository: {repo_path}") from exc

    if inside != "true" or not top_level:
        raise PrepError(f"--repo is not a git repository: {repo_path}")

    return pathlib.Path(top_level).resolve()


def resolve_commit(repo, commit):
    try:
        return run_git(repo, ["rev-parse", "--verify", f"{commit}^{{commit}}"]).strip()
    except PrepError as exc:
        raise PrepError(f"--commit is not a valid commit: {commit}") from exc


def resolve_parent(repo, commit_sha):
    try:
        return run_git(repo, ["rev-parse", f"{commit_sha}^"]).strip()
    except PrepError as exc:
        raise PrepError(f"Commit has no parent: {commit_sha}") from exc


def get_commit_metadata(repo, commit):
    output = run_git(
        repo,
        ["show", "-s", "--format=%s%x00%B%x00%an%x00%ae%x00%aI", commit],
    )
    parts = output.split("\x00")
    if len(parts) < 5:
        raise PrepError("Failed to parse commit metadata")

    return {
        "subject": parts[0].strip(),
        "message": parts[1].strip(),
        "author_name": parts[2].strip(),
        "author_email": parts[3].strip(),
        "date": parts[4].strip(),
    }


def get_name_status(repo, parent, commit):
    output = run_git(
        repo,
        ["diff", "--name-status", "--find-renames", "--find-copies", parent, commit],
    )
    statuses = []
    for line in output.splitlines():
        if not line.strip():
            continue

        parts = line.split("\t")
        status_code = parts[0]
        status_key = status_code[:1]
        status = STATUS_MAP.get(status_key, "unknown")

        if status_key in ("R", "C") and len(parts) >= 3:
            old_path = parts[1]
            path = parts[2]
        elif len(parts) >= 2:
            path = parts[1]
            old_path = None if status_key == "A" else path
        else:
            path = line
            old_path = path

        statuses.append(
            {
                "path": path,
                "old_path": old_path,
                "status": status,
                "raw_status": status_code,
            }
        )

    return statuses


def get_diff(repo, parent, commit):
    return run_git(
        repo,
        ["diff", "--find-renames", "--find-copies", "--unified=3", parent, commit],
    )


def detect_language(path):
    if not path:
        return "Unknown"

    suffix = pathlib.Path(path).suffix.lower()
    if suffix == ".py":
        return "Python"
    if suffix == ".java":
        return "Java"
    if suffix == ".cs":
        return "C#"
    if suffix in (".cpp", ".cc", ".cxx"):
        return "C++"
    if suffix in (".c", ".h"):
        return "C/C++"
    if suffix in (".js", ".jsx", ".ts", ".tsx"):
        return "JavaScript/TypeScript"
    if suffix == ".md":
        return "Markdown"
    if suffix == ".json":
        return "JSON"
    return "Unknown"


def parse_diff_git_header(line):
    match = re.match(r"^diff --git a/(.*) b/(.*)$", line)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def parse_file_marker(line):
    marker = line[4:]
    if marker == "/dev/null":
        return None
    if marker.startswith("a/") or marker.startswith("b/"):
        return marker[2:]
    return marker


def make_file_record(event_id, path, old_path, status):
    return {
        "event_id": event_id,
        "path": path,
        "old_path": old_path,
        "status": status,
        "language": detect_language(path or old_path),
        "hunks": [],
    }


def describe_file_event(file_record):
    status = file_record["status"]
    path = file_record["path"]
    old_path = file_record["old_path"]

    if status == "renamed":
        return f"{file_record['event_id']}: renamed {old_path} -> {path}"
    if status == "copied":
        return f"{file_record['event_id']}: copied {old_path} -> {path}"
    if status == "added":
        return f"{file_record['event_id']}: added {path}"
    if status == "deleted":
        return f"{file_record['event_id']}: deleted {old_path or path}"
    if status == "modified":
        return f"{file_record['event_id']}: modified {path}"
    return f"{file_record['event_id']}: unknown {old_path or path}"


def build_file_events(files):
    return [
        {
            "event_id": file_record["event_id"],
            "status": file_record["status"],
            "old_path": file_record["old_path"],
            "path": file_record["path"],
            "language": file_record["language"],
        }
        for file_record in files
    ]


def build_files_output(files):
    return [
        {
            "path": file_record["path"],
            "old_path": file_record["old_path"],
            "status": file_record["status"],
            "language": file_record["language"],
            "hunks": file_record["hunks"],
        }
        for file_record in files
    ]


def build_analysis_items(changes, file_events):
    analysis_items = [
        {"id": change["change_id"], "kind": "line_change"} for change in changes
    ]
    analysis_items.extend(
        {
            "id": file_event["event_id"],
            "kind": FILE_KIND_MAP.get(file_event["status"], "file_unknown"),
        }
        for file_event in file_events
    )
    return analysis_items


def parse_hunk_header(header):
    match = HUNK_RE.match(header)
    if not match:
        return None

    return {
        "old_start": int(match.group("old_start")),
        "old_count": int(match.group("old_count") or "1"),
        "new_start": int(match.group("new_start")),
        "new_count": int(match.group("new_count") or "1"),
    }


def parse_unified_diff(diff_text, file_statuses):
    warnings = []
    files_by_path = {}
    lookup = {}

    for index, status_info in enumerate(file_statuses, start=1):
        path = status_info["path"]
        old_path = status_info["old_path"]
        record = make_file_record(
            f"F{index:06d}", path, old_path, status_info["status"]
        )
        files_by_path[path] = record
        lookup[path] = record
        if old_path:
            lookup[old_path] = record

    files = list(files_by_path.values())
    changes = []
    binary_paths = set()

    current_file = None
    current_hunk = None
    pending_old_path = None
    old_line = None
    new_line = None
    line_index_in_hunk = 0
    hunk_counter = 0
    change_counter = 0
    next_file_index = len(files) + 1

    def ensure_file(path, old_path, status="unknown"):
        nonlocal next_file_index

        selected_path = path or old_path
        if selected_path in lookup:
            return lookup[selected_path]
        if old_path in lookup:
            return lookup[old_path]

        record = make_file_record(
            f"F{next_file_index:06d}", selected_path, old_path, status
        )
        next_file_index += 1
        files_by_path[selected_path] = record
        lookup[selected_path] = record
        if old_path:
            lookup[old_path] = record
        files.append(record)
        return record

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            old_header_path, new_header_path = parse_diff_git_header(line)
            current_file = ensure_file(new_header_path, old_header_path)
            current_hunk = None
            pending_old_path = old_header_path
            continue

        if line.startswith("Binary files ") or line == "GIT binary patch":
            path = current_file["path"] if current_file else "unknown"
            if path not in binary_paths:
                warnings.append(
                    f"Binary diff detected for {path}; line-level changes skipped."
                )
                binary_paths.add(path)
            current_hunk = None
            continue

        if line.startswith("--- "):
            pending_old_path = parse_file_marker(line)
            current_hunk = None
            continue

        if line.startswith("+++ "):
            new_path = parse_file_marker(line)
            status = "unknown"
            if new_path is None:
                selected_path = pending_old_path
            else:
                selected_path = new_path
            current_file = ensure_file(selected_path, pending_old_path, status)
            current_hunk = None
            continue

        if line.startswith("@@ "):
            if current_file is None:
                warnings.append(f"Hunk skipped because file header was missing: {line}")
                current_hunk = None
                continue

            hunk_info = parse_hunk_header(line)
            if hunk_info is None:
                warnings.append(f"Could not parse hunk header: {line}")
                current_hunk = None
                continue

            hunk_counter += 1
            current_hunk = {
                "hunk_id": f"H{hunk_counter:06d}",
                "header": line,
                "hunk_text": [],
                "old_start": hunk_info["old_start"],
                "old_count": hunk_info["old_count"],
                "new_start": hunk_info["new_start"],
                "new_count": hunk_info["new_count"],
                "change_ids": [],
            }
            current_file["hunks"].append(current_hunk)
            old_line = hunk_info["old_start"]
            new_line = hunk_info["new_start"]
            line_index_in_hunk = 0
            continue

        if current_hunk is None:
            continue

        current_hunk["hunk_text"].append(line)

        if line.startswith("\\ No newline at end of file"):
            continue

        line_index_in_hunk += 1

        if line.startswith("+") and not line.startswith("+++"):
            change_counter += 1
            change_id = f"C{change_counter:06d}"
            current_hunk["change_ids"].append(change_id)
            changes.append(
                {
                    "change_id": change_id,
                    "hunk_id": current_hunk["hunk_id"],
                    "file": current_file["path"],
                    "old_file": current_file["old_path"],
                    "op": "+",
                    "old_line": None,
                    "new_line": new_line,
                    "text": line[1:],
                    "line_index_in_hunk": line_index_in_hunk,
                }
            )
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            change_counter += 1
            change_id = f"C{change_counter:06d}"
            current_hunk["change_ids"].append(change_id)
            changes.append(
                {
                    "change_id": change_id,
                    "hunk_id": current_hunk["hunk_id"],
                    "file": current_file["path"],
                    "old_file": current_file["old_path"],
                    "op": "-",
                    "old_line": old_line,
                    "new_line": None,
                    "text": line[1:],
                    "line_index_in_hunk": line_index_in_hunk,
                }
            )
            old_line += 1
        elif line.startswith(" "):
            old_line += 1
            new_line += 1

    additions = sum(1 for change in changes if change["op"] == "+")
    deletions = sum(1 for change in changes if change["op"] == "-")
    files_output = build_files_output(files)
    file_events = build_file_events(files)
    file_event_summaries = [describe_file_event(file_record) for file_record in files]
    analysis_items = build_analysis_items(changes, file_events)
    stats = {
        "files_changed": len(files),
        "file_events": len(files),
        "hunks": hunk_counter,
        "changes": len(changes),
        "analysis_items": len(analysis_items),
        "additions": additions,
        "deletions": deletions,
    }

    return (
        files_output,
        file_events,
        file_event_summaries,
        analysis_items,
        changes,
        stats,
        warnings,
    )


def build_input_json(
    repo,
    target_commit,
    parent_commit,
    metadata,
    files,
    file_events,
    file_event_summaries,
    analysis_items,
    changes,
    stats,
    warnings,
):
    return {
        "schema_version": 1,
        "repo": str(pathlib.Path(repo).resolve()),
        "target_commit": target_commit,
        "parent_commit": parent_commit,
        "commit": metadata,
        "files": files,
        "file_events": file_events,
        "file_event_summaries": file_event_summaries,
        "analysis_items": analysis_items,
        "changes": changes,
        "stats": stats,
        "warnings": warnings,
    }


def write_outputs(out_dir, diff_text, input_data):
    out_path = pathlib.Path(out_dir).expanduser()
    if out_path.exists() and not out_path.is_dir():
        raise PrepError(f"--out exists but is not a directory: {out_path}")

    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PrepError(f"Could not create --out directory {out_path}: {exc}") from exc

    diff_path = out_path / "diff.patch"
    input_path = out_path / "input.json"

    try:
        diff_path.write_text(diff_text, encoding="utf-8")
        input_path.write_text(
            json.dumps(input_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise PrepError(f"Could not write output files in {out_path}: {exc}") from exc

    return input_path.resolve(), diff_path.resolve()


def parse_args(argv):
    parser = JsonArgumentParser(
        description="Prepare git commit data for future Codex agents."
    )
    parser.add_argument("--repo", required=True, help="Path to a git repository")
    parser.add_argument("--commit", required=True, help="Commit to prepare")
    parser.add_argument("--out", required=True, help="Output directory")
    return parser.parse_args(argv)


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False))


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        repo = validate_repo(args.repo)
        target_commit = resolve_commit(repo, args.commit)
        parent_commit = resolve_parent(repo, target_commit)
        metadata = get_commit_metadata(repo, target_commit)
        file_statuses = get_name_status(repo, parent_commit, target_commit)
        diff_text = get_diff(repo, parent_commit, target_commit)
        (
            files,
            file_events,
            file_event_summaries,
            analysis_items,
            changes,
            stats,
            warnings,
        ) = parse_unified_diff(diff_text, file_statuses)
        input_data = build_input_json(
            repo,
            target_commit,
            parent_commit,
            metadata,
            files,
            file_events,
            file_event_summaries,
            analysis_items,
            changes,
            stats,
            warnings,
        )
        input_path, diff_path = write_outputs(args.out, diff_text, input_data)
    except PrepError as exc:
        print_json({"status": "error", "message": str(exc)})
        return 1

    print_json(
        {
            "status": "ok",
            "input_path": str(input_path),
            "diff_path": str(diff_path),
            "target_commit": target_commit,
            "parent_commit": parent_commit,
            "changes": stats["changes"],
            "hunks": stats["hunks"],
            "file_events": stats["file_events"],
            "analysis_items": stats["analysis_items"],
            "files_changed": stats["files_changed"],
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
