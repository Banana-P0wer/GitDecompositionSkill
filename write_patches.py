import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

from validate_reviewer import (
    ValidationError as ReviewerValidationError,
    check_required_top_level,
    get_expected_item_ids,
    print_json,
    read_json,
    validate_disagreements,
    validate_groups,
)


class PatchError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise PatchError(message)


def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def add_unique(values, value):
    if value and value not in values:
        values.append(value)


def print_json_payload(payload):
    print(json.dumps(payload, ensure_ascii=False))


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PatchError(f"File not found: {path}") from exc
    except OSError as exc:
        raise PatchError(f"Could not read {path}: {exc}") from exc


def validate_reviewer_basic(input_data, reviewer_data):
    expected_ids = get_expected_item_ids(input_data)
    expected_set = set(expected_ids)
    groups, disagreements_resolved, is_mixed, confidence = check_required_top_level(
        reviewer_data
    )
    seen_ids = validate_groups(groups, expected_set)
    validate_disagreements(disagreements_resolved, expected_set)

    seen_set = set(seen_ids)
    missing_ids = [item_id for item_id in expected_ids if item_id not in seen_set]
    if missing_ids:
        raise ReviewerValidationError(f"Missing item id: {missing_ids[0]}")
    if len(groups) > 1 and not is_mixed:
        raise ReviewerValidationError(
            "reviewer.json is_mixed must be true when groups > 1"
        )

    return {
        "expected_items": len(expected_ids),
        "grouped_items": len(seen_ids),
        "groups": len(groups),
        "is_mixed": is_mixed,
        "confidence": confidence,
    }


def parse_diff_git_header(line):
    match = re.match(r"^diff --git a/(.*) b/(.*)$", line.rstrip("\n"))
    if not match:
        return None, None
    return match.group(1), match.group(2)


def split_diff_sections(diff_text):
    sections = []
    current_lines = []

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_lines:
                sections.append(build_section(current_lines))
            current_lines = [line]
        elif current_lines:
            current_lines.append(line)

    if current_lines:
        sections.append(build_section(current_lines))

    return sections


def build_section(lines):
    text = "".join(lines)
    old_path, new_path = parse_diff_git_header(lines[0]) if lines else (None, None)
    paths = []
    add_unique(paths, old_path)
    add_unique(paths, new_path)
    binary = any(
        line.startswith("Binary files ") or line.rstrip("\n") == "GIT binary patch"
        for line in lines
    )
    return {
        "path": new_path or old_path or "<unknown>",
        "old_path": old_path,
        "new_path": new_path,
        "paths": paths,
        "text": text if text.endswith("\n") else text + "\n",
        "binary": binary,
    }


def build_items_by_path(input_data):
    items_by_path = {}

    def add_item(path, item_id):
        if not path or not item_id:
            return
        items = items_by_path.setdefault(path, [])
        add_unique(items, item_id)

    for change in as_list(input_data.get("changes")):
        change = as_dict(change)
        item_id = change.get("change_id")
        add_item(change.get("file"), item_id)
        add_item(change.get("old_file"), item_id)

    for event in as_list(input_data.get("file_events")):
        event = as_dict(event)
        item_id = event.get("event_id")
        add_item(event.get("path"), item_id)
        add_item(event.get("old_path"), item_id)

    return items_by_path


def section_item_ids(section, items_by_path):
    item_ids = []
    for path in section["paths"]:
        for item_id in items_by_path.get(path, []):
            add_unique(item_ids, item_id)
    return item_ids


def build_item_to_group(reviewer_data):
    item_to_group = {}
    group_records = []

    for group in as_list(reviewer_data.get("groups")):
        group = as_dict(group)
        group_id = group.get("group_id")
        item_ids = as_list(group.get("item_ids"))
        record = {
            "group_id": group_id,
            "summary": group.get("summary", ""),
            "patch_path": None,
            "files": [],
            "items": len(item_ids),
            "generated": False,
            "verify_status": "not_run",
        }
        group_records.append(record)
        for item_id in item_ids:
            item_to_group[item_id] = group_id

    return item_to_group, group_records


def sanitize_patch_filename(group_id):
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(group_id))
    return f"{safe_name or 'group'}.patch"


def remove_previous_patch_artifacts(out_dir):
    if not out_dir.exists():
        return
    for path in out_dir.glob("*.patch"):
        if path.is_file():
            path.unlink()
    patch_plan_path = out_dir / "patch_plan.json"
    if patch_plan_path.exists() and patch_plan_path.is_file():
        patch_plan_path.unlink()


def add_unsafe_reason(group_record, reason):
    reasons = group_record.setdefault("unsafe_reasons", [])
    add_unique(reasons, reason)


def build_patch_plan(input_data, reviewer_data, diff_text, paths, verify):
    stats = validate_reviewer_basic(input_data, reviewer_data)
    item_to_group, group_records = build_item_to_group(reviewer_data)
    groups_by_id = {record["group_id"]: record for record in group_records}
    items_by_path = build_items_by_path(input_data)
    sections = split_diff_sections(diff_text)
    unsafe_sections = []
    patch_sections_by_group = {record["group_id"]: [] for record in group_records}

    def record_unsafe(section, reason, groups=None, item_ids=None):
        unsafe = {
            "path": section["path"],
            "reason": reason,
        }
        if groups:
            unsafe["groups"] = groups
        if item_ids:
            unsafe["item_ids"] = item_ids
        unsafe_sections.append(unsafe)
        for group_id in groups or []:
            group_record = groups_by_id.get(group_id)
            if group_record is not None:
                add_unsafe_reason(group_record, reason)

    for section in sections:
        item_ids = section_item_ids(section, items_by_path)
        groups = []
        for item_id in item_ids:
            add_unique(groups, item_to_group.get(item_id))

        if section["binary"]:
            record_unsafe(
                section,
                "binary diff file section cannot be safely split",
                groups,
                item_ids,
            )
            continue

        if not item_ids:
            record_unsafe(section, "could not map diff file section to analysis items")
            continue

        if len(groups) != 1:
            record_unsafe(
                section,
                "file section contains items from multiple reviewer groups",
                groups,
                item_ids,
            )
            continue

        group_id = groups[0]
        patch_sections_by_group[group_id].append(section["text"])
        group_record = groups_by_id[group_id]
        add_unique(group_record["files"], section["path"])

    out_dir = paths["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    remove_previous_patch_artifacts(out_dir)

    for group_record in group_records:
        group_id = group_record["group_id"]
        patch_sections = patch_sections_by_group.get(group_id, [])
        if not patch_sections:
            if group_record.get("unsafe_reasons"):
                add_unsafe_reason(
                    group_record,
                    "all file sections for this group were unsafe to split",
                )
            continue

        patch_path = out_dir / sanitize_patch_filename(group_id)
        try:
            patch_path.write_text("".join(patch_sections), encoding="utf-8")
        except OSError as exc:
            raise PatchError(f"Could not write patch file {patch_path}: {exc}") from exc
        group_record["patch_path"] = str(patch_path)
        group_record["generated"] = True

    warnings = []
    if verify:
        warnings.extend(verify_generated_patches(input_data, group_records))

    patches_generated = sum(1 for record in group_records if record["generated"])
    all_items_patchable = not unsafe_sections and all(
        record["generated"] for record in group_records if record["items"] > 0
    )
    plan = {
        "schema_version": 1,
        "strategy": "whole-file-section",
        "input_path": str(paths["input"]),
        "reviewer_path": str(paths["reviewer"]),
        "diff_path": str(paths["diff"]),
        "patches_dir": str(out_dir),
        "groups": group_records,
        "unsafe_sections": unsafe_sections,
        "summary": {
            "groups": stats["groups"],
            "patches_generated": patches_generated,
            "unsafe_sections": len(unsafe_sections),
            "all_items_patchable": all_items_patchable,
        },
    }
    if warnings:
        plan["warnings"] = warnings

    return plan


def run_command(command):
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise PatchError(f"Failed to run {' '.join(command)}: {exc}") from exc


def command_error(result):
    return (result.stderr.strip() or result.stdout.strip()).strip()


def verify_generated_patches(input_data, group_records):
    warnings = []
    generated_records = [record for record in group_records if record["generated"]]
    if not generated_records:
        return warnings

    repo = input_data.get("repo")
    parent_commit = input_data.get("parent_commit")
    if not repo or not parent_commit:
        warning = "patch verification skipped because repo or parent_commit is missing"
        warnings.append(warning)
        return warnings

    repo_path = pathlib.Path(repo).expanduser()
    temp_path = pathlib.Path(tempfile.mkdtemp(prefix="git-dec-patch-verify-"))
    worktree_added = False

    try:
        shutil.rmtree(temp_path)
        add_result = run_command(
            [
                "git",
                "-C",
                str(repo_path),
                "worktree",
                "add",
                "--detach",
                str(temp_path),
                str(parent_commit),
            ]
        )
        if add_result.returncode != 0:
            warning = (
                "patch verification skipped because temporary worktree could not be "
                f"created: {command_error(add_result)}"
            )
            warnings.append(warning)
            return warnings

        worktree_added = True
        for record in generated_records:
            patch_path = pathlib.Path(record["patch_path"]).expanduser().resolve()
            check_result = run_command(
                ["git", "-C", str(temp_path), "apply", "--check", str(patch_path)]
            )
            if check_result.returncode == 0:
                record["verify_status"] = "passed"
            else:
                record["verify_status"] = "failed"
                record["verify_error"] = command_error(check_result)
    finally:
        if worktree_added:
            remove_result = run_command(
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "worktree",
                    "remove",
                    "--force",
                    str(temp_path),
                ]
            )
            if remove_result.returncode != 0:
                warnings.append(
                    "temporary worktree cleanup reported an error: "
                    f"{command_error(remove_result)}"
                )
                shutil.rmtree(temp_path, ignore_errors=True)
        else:
            shutil.rmtree(temp_path, ignore_errors=True)

    return warnings


def write_patch_plan(plan, patch_plan_path):
    try:
        patch_plan_path.parent.mkdir(parents=True, exist_ok=True)
        patch_plan_path.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise PatchError(f"Could not write patch plan {patch_plan_path}: {exc}") from exc


def parse_args(argv):
    parser = JsonArgumentParser(
        description="Write conservative reviewer-group patch files."
    )
    parser.add_argument("--input", required=True, help="Path to input.json")
    parser.add_argument("--reviewer", required=True, help="Path to reviewer.json")
    parser.add_argument("--diff", required=True, help="Path to diff.patch")
    parser.add_argument("--out-dir", required=True, help="Directory for patch files")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip git apply --check verification in a temporary worktree",
    )
    return parser.parse_args(argv)


def write_patches(args):
    input_path = pathlib.Path(args.input).expanduser()
    reviewer_path = pathlib.Path(args.reviewer).expanduser()
    diff_path = pathlib.Path(args.diff).expanduser()
    out_dir = pathlib.Path(args.out_dir).expanduser()

    input_data = read_json(input_path)
    reviewer_data = read_json(reviewer_path)
    diff_text = read_text(diff_path)

    paths = {
        "input": input_path,
        "reviewer": reviewer_path,
        "diff": diff_path,
        "out_dir": out_dir,
    }
    plan = build_patch_plan(
        input_data,
        reviewer_data,
        diff_text,
        paths,
        verify=not args.no_verify,
    )
    patch_plan_path = out_dir / "patch_plan.json"
    write_patch_plan(plan, patch_plan_path)

    summary = plan["summary"]
    return {
        "status": "ok",
        "patches_dir": str(out_dir),
        "patch_plan_path": str(patch_plan_path),
        "groups": summary["groups"],
        "patches_generated": summary["patches_generated"],
        "unsafe_sections": summary["unsafe_sections"],
        "all_items_patchable": summary["all_items_patchable"],
    }


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        payload = write_patches(args)
    except (PatchError, ReviewerValidationError) as exc:
        print_json({"status": "error", "message": str(exc)})
        return 1

    print_json_payload(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
