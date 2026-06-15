import argparse
import pathlib
import re
import sys

from validate_explicit import (
    ValidationError as ExplicitValidationError,
    validate_explicit,
)
from validate_implicit import (
    ValidationError as ImplicitValidationError,
    print_json,
    read_json,
    validate_implicit,
)
from validate_reviewer import validate_reviewer


class ReportError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ReportError(message)


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def one_line(value):
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def trim_text(value, limit=160):
    text = one_line(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def inline_code(value):
    text = one_line(value)
    matches = re.findall(r"`+", text)
    tick_count = max((len(match) for match in matches), default=0) + 1
    ticks = "`" * tick_count
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{padding}{text}{padding}{ticks}"


def bullet_text(value):
    text = str(value).strip()
    return text if text else "None"


def build_detail_maps(input_data):
    changes = {}
    file_events = {}

    for change in as_list(input_data.get("changes")):
        if isinstance(change, dict) and isinstance(change.get("change_id"), str):
            changes[change["change_id"]] = change

    for event in as_list(input_data.get("file_events")):
        if isinstance(event, dict) and isinstance(event.get("event_id"), str):
            file_events[event["event_id"]] = event

    return changes, file_events


def format_line_change(item_id, change):
    file_path = change.get("file") or change.get("old_file") or "<unknown>"
    op = change.get("op")
    if op == "+":
        line = change.get("new_line")
        action = "added"
    elif op == "-":
        line = change.get("old_line")
        action = "removed"
    else:
        line = change.get("new_line") or change.get("old_line")
        action = "changed"

    line_label = f":{line}" if line is not None else ""
    text = trim_text(change.get("text", ""))
    return f"- {item_id} {inline_code(file_path + line_label)} {action} {inline_code(text)}"


def format_file_event(item_id, event):
    status = str(event.get("status", "unknown"))
    old_path = event.get("old_path")
    path = event.get("path")

    if status in ("renamed", "copied"):
        return (
            f"- {item_id} {status} "
            f"{inline_code(old_path or '<unknown>')} -> {inline_code(path or '<unknown>')}"
        )
    if status == "deleted":
        return f"- {item_id} deleted {inline_code(old_path or path or '<unknown>')}"
    if status == "added":
        return f"- {item_id} added {inline_code(path or '<unknown>')}"
    if status == "modified":
        return f"- {item_id} modified {inline_code(path or old_path or '<unknown>')}"
    return f"- {item_id} {status} {inline_code(old_path or path or '<unknown>')}"


def format_item(item_id, changes, file_events):
    if item_id in changes:
        return format_line_change(item_id, changes[item_id])
    if item_id in file_events:
        return format_file_event(item_id, file_events[item_id])
    return f"- {item_id} unknown item details"


def add_unique(values, value):
    if value and value not in values:
        values.append(value)


def group_files(item_ids, changes, file_events):
    files = []
    for item_id in item_ids:
        if item_id in changes:
            change = changes[item_id]
            add_unique(files, change.get("file") or change.get("old_file"))
        elif item_id in file_events:
            event = file_events[item_id]
            add_unique(files, event.get("old_path"))
            add_unique(files, event.get("path"))
    return files


def render_warnings(warnings):
    lines = ["- Warnings:"]
    if warnings:
        for warning in warnings:
            lines.append(f"  - {bullet_text(warning)}")
    else:
        lines.append("  - None")
    return lines


def render_agent_summary(title, label, data):
    groups = as_list(data.get("groups"))
    ungrouped_item_ids = as_list(data.get("ungrouped_item_ids"))
    lines = [
        f"## {title}",
        f"- Groups: {len(groups)}",
        f"- Ungrouped items: {len(ungrouped_item_ids)}",
    ]
    lines.extend(render_warnings(as_list(data.get("warnings"))))

    for group in groups:
        group = as_dict(group)
        group_id = group.get("group_id", "<unknown>")
        summary = group.get("summary", "No summary")
        item_ids = as_list(group.get("item_ids"))
        reason = group.get("reason", "")
        lines.extend(
            [
                f"### {label} group {group_id}: {summary}",
                f"- Items: {len(item_ids)}",
                "- Reason:",
                f"  {bullet_text(reason)}",
            ]
        )

    return lines


def format_item_id_summary(item_ids, max_items_per_group):
    item_ids = [str(item_id) for item_id in item_ids]
    if not item_ids:
        return "None"
    if max_items_per_group == 0 or len(item_ids) <= max_items_per_group:
        return ", ".join(item_ids)

    visible_item_ids = item_ids[:max_items_per_group]
    hidden_count = len(item_ids) - len(visible_item_ids)
    return (
        f"{len(item_ids)} items: {', '.join(visible_item_ids)}; "
        f"... and {hidden_count} more item ids. "
        "See report_items.md for the full item list."
    )


def render_disagreements(reviewer_data, max_items_per_group):
    disagreements = as_list(reviewer_data.get("disagreements_resolved"))
    lines = ["## Disagreements resolved by reviewer"]
    if not disagreements:
        lines.append("No explicit/implicit disagreements were recorded by the reviewer.")
        return lines

    for disagreement in disagreements:
        disagreement = as_dict(disagreement)
        item_ids = format_item_id_summary(
            as_list(disagreement.get("item_ids")),
            max_items_per_group,
        )
        lines.extend(
            [
                f"- Items: {item_ids or 'None'}",
                f"  - Explicit: {bullet_text(disagreement.get('explicit_position', ''))}",
                f"  - Implicit: {bullet_text(disagreement.get('implicit_position', ''))}",
                f"  - Decision: {bullet_text(disagreement.get('decision', ''))}",
                f"  - Reason: {bullet_text(disagreement.get('reason', ''))}",
            ]
        )
    return lines


def yes_no(value):
    return "yes" if value else "no"


def render_patch_files(patch_plan):
    summary = as_dict(patch_plan.get("summary"))
    lines = [
        "## Patch files",
        f"Strategy: {patch_plan.get('strategy', '')}",
        f"- Groups: {summary.get('groups', 0)}",
        f"- Patch files generated: {summary.get('patches_generated', 0)}",
        f"- Unsafe sections: {summary.get('unsafe_sections', 0)}",
        f"- All items patchable: {yes_no(summary.get('all_items_patchable'))}",
    ]

    for group in as_list(patch_plan.get("groups")):
        group = as_dict(group)
        group_id = group.get("group_id", "<unknown>")
        patch_path = group.get("patch_path")
        lines.extend(
            [
                f"### Group {group_id}",
                f"- Patch: {patch_path if patch_path else 'not generated'}",
                f"- Verify: {group.get('verify_status', 'not_run')}",
                "- Files:",
            ]
        )
        files = as_list(group.get("files"))
        if files:
            for file_path in files:
                lines.append(f"  - {file_path}")
        else:
            lines.append("  - None")

        unsafe_reasons = as_list(group.get("unsafe_reasons"))
        if unsafe_reasons:
            lines.append("- Reason:")
            for reason in unsafe_reasons:
                lines.append(f"  - {reason}")

    lines.append("## Unsafe patch sections")
    unsafe_sections = as_list(patch_plan.get("unsafe_sections"))
    if unsafe_sections:
        for section in unsafe_sections:
            section = as_dict(section)
            lines.append(
                f"- {section.get('path', '<unknown>')}: "
                f"{section.get('reason', 'unknown reason')}"
            )
    else:
        lines.append("No unsafe patch sections.")

    return lines


def render_group_items(item_ids, changes, file_events, max_items_per_group):
    if max_items_per_group == 0:
        visible_item_ids = item_ids
    else:
        visible_item_ids = item_ids[:max_items_per_group]

    lines = []
    for item_id in visible_item_ids:
        lines.append(format_item(str(item_id), changes, file_events))

    hidden_count = len(item_ids) - len(visible_item_ids)
    if hidden_count > 0:
        lines.append(
            f"... and {hidden_count} more items. "
            "See report_items.md for the full list."
        )
    return lines


def render_final_group(group, changes, file_events, max_items_per_group):
    group = as_dict(group)
    group_id = group.get("group_id", "<unknown>")
    summary = group.get("summary", "No summary")
    item_ids = as_list(group.get("item_ids"))
    evidence = as_dict(group.get("evidence"))
    files = group_files(item_ids, changes, file_events)
    items_heading = (
        "Sample items:"
        if max_items_per_group != 0 and len(item_ids) > max_items_per_group
        else "Items:"
    )

    lines = [
        f"### Group {group_id}: {summary}",
        f"- Items: {len(item_ids)}",
        "- Files:",
    ]
    if files:
        for file_path in files:
            lines.append(f"  - {file_path}")
    else:
        lines.append("  - <unknown>")

    lines.extend(
        [
            "Why:",
            bullet_text(group.get("why", "")),
            "Evidence:",
            f"- Explicit: {bullet_text(evidence.get('explicit', ''))}",
            f"- Implicit: {bullet_text(evidence.get('implicit', ''))}",
            items_heading,
        ]
    )
    lines.extend(render_group_items(item_ids, changes, file_events, max_items_per_group))
    return lines


def render_report_items(input_data, reviewer_data):
    commit = as_dict(input_data.get("commit"))
    changes, file_events = build_detail_maps(input_data)
    lines = [
        "# Git Decomposition Report Items",
        f"Commit: {input_data.get('target_commit', '')}",
        f"Subject: {commit.get('subject', '')}",
    ]

    for group in as_list(reviewer_data.get("groups")):
        group = as_dict(group)
        group_id = group.get("group_id", "<unknown>")
        summary = group.get("summary", "No summary")
        item_ids = as_list(group.get("item_ids"))
        lines.extend(
            [
                f"## Group {group_id}: {summary}",
                f"Items: {len(item_ids)}",
            ]
        )
        for item_id in item_ids:
            lines.append(format_item(str(item_id), changes, file_events))

    return "\n".join(lines) + "\n"


def group_label(group):
    group = as_dict(group)
    group_id = group.get("group_id")
    summary = group.get("summary") or "No summary"
    return f"{group_id} ({summary})" if group_id else summary


def group_labels_summary(groups, max_groups=5):
    labels = [group_label(group) for group in groups]
    if len(labels) <= max_groups:
        return "; ".join(labels)

    visible_labels = labels[:max_groups]
    hidden_count = len(labels) - len(visible_labels)
    return f"{'; '.join(visible_labels)}; ... and {hidden_count} more groups"


def render_verdict_explanation(reviewer_data):
    groups = as_list(reviewer_data.get("groups"))
    is_mixed = reviewer_data.get("is_mixed")
    confidence = reviewer_data.get("confidence")
    if not groups:
        return "Reviewer produced no final groups."

    summaries = group_labels_summary(groups)
    if is_mixed:
        return (
            f"Reviewer identified {len(groups)} final groups with confidence "
            f"{confidence}: {summaries}"
        )
    if len(groups) == 1:
        return (
            f"Reviewer found one coherent final group with confidence "
            f"{confidence}: {summaries}"
        )
    return (
        f"Reviewer marked the commit as not mixed with {len(groups)} final groups "
        f"and confidence {confidence}: {summaries}"
    )


def render_report(
    input_data,
    explicit_data,
    implicit_data,
    reviewer_data,
    stats,
    paths,
    max_items_per_group,
    patch_plan=None,
):
    commit = as_dict(input_data.get("commit"))
    author = commit.get("author_name", "")
    author_email = commit.get("author_email", "")
    if author_email:
        author = f"{author} <{author_email}>" if author else f"<{author_email}>"

    changes, file_events = build_detail_maps(input_data)
    reviewer_groups = as_list(reviewer_data.get("groups"))
    mixed_label = "yes" if stats["is_mixed"] else "no"

    lines = [
        "# Git Decomposition Report",
        "## Commit",
        f"- Repository: {input_data.get('repo', '')}",
        f"- Target commit: {input_data.get('target_commit', '')}",
        f"- Parent commit: {input_data.get('parent_commit', '')}",
        f"- Subject: {commit.get('subject', '')}",
        f"- Author: {author}",
        f"- Date: {commit.get('date', '')}",
        "## Verdict",
        f"- Mixed commit: {mixed_label}",
        f"- Confidence: {stats['confidence']}",
        f"- Final groups: {stats['groups']}",
        f"- Analysis items: {stats['grouped_items']}",
        "Короткое объяснение:",
        render_verdict_explanation(reviewer_data),
        "## Final decomposition",
    ]

    for group in reviewer_groups:
        lines.extend(
            render_final_group(group, changes, file_events, max_items_per_group)
        )

    lines.extend(render_agent_summary("Explicit agent summary", "Explicit", explicit_data))
    lines.extend(render_agent_summary("Implicit agent summary", "Implicit", implicit_data))
    lines.extend(render_disagreements(reviewer_data, max_items_per_group))
    if patch_plan is not None:
        lines.extend(render_patch_files(patch_plan))
    lines.extend(
        [
            "## Generated artifacts",
            f"- input.json: {paths['input']}",
            f"- diff.patch: {paths['diff']}",
            f"- explicit.json: {paths['explicit']}",
            f"- implicit.json: {paths['implicit']}",
            f"- reviewer.json: {paths['reviewer']}",
            f"- report.md: {paths['report']}",
            f"- report_items.md: {paths['report_items']}",
            *([f"- patch_plan.json: {paths['patch_plan']}"] if paths.get("patch_plan") else []),
            "## Limitations",
            "- Patch generation uses only whole diff file sections in this prototype.",
            "- This prototype does not modify the analyzed repository.",
            "- The final decomposition is advisory and should be reviewed by a human.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv):
    parser = JsonArgumentParser(description="Write final git decomposition report.md.")
    parser.add_argument("--input", required=True, help="Path to input.json")
    parser.add_argument("--explicit", required=True, help="Path to explicit.json")
    parser.add_argument("--implicit", required=True, help="Path to implicit.json")
    parser.add_argument("--reviewer", required=True, help="Path to reviewer.json")
    parser.add_argument(
        "--patch-plan",
        help="Optional path to patches/patch_plan.json for report patch summary",
    )
    parser.add_argument("--out", required=True, help="Path to report.md")
    parser.add_argument(
        "--items-out",
        help="Path to report_items.md, defaults to report_items.md next to --out",
    )
    parser.add_argument(
        "--max-items-per-group",
        type=int,
        default=30,
        help="Maximum items to show per reviewer group in report.md; 0 shows all",
    )
    return parser.parse_args(argv)


def write_report(args):
    input_path = pathlib.Path(args.input).expanduser()
    explicit_path = pathlib.Path(args.explicit).expanduser()
    implicit_path = pathlib.Path(args.implicit).expanduser()
    reviewer_path = pathlib.Path(args.reviewer).expanduser()
    patch_plan_path = (
        pathlib.Path(args.patch_plan).expanduser() if args.patch_plan else None
    )
    out_path = pathlib.Path(args.out).expanduser()
    items_out_path = (
        pathlib.Path(args.items_out).expanduser()
        if args.items_out
        else out_path.parent / "report_items.md"
    )
    max_items_per_group = args.max_items_per_group

    if max_items_per_group < 0:
        raise ReportError("--max-items-per-group must be 0 or greater")
    if out_path == items_out_path:
        raise ReportError("--out and --items-out must be different paths")

    input_data = read_json(input_path)
    explicit_data = read_json(explicit_path)
    implicit_data = read_json(implicit_path)
    reviewer_data = read_json(reviewer_path)
    patch_plan_data = None
    if patch_plan_path is not None and patch_plan_path.exists():
        patch_plan_data = read_json(patch_plan_path)

    validate_explicit(input_data, explicit_data)
    validate_implicit(input_data, implicit_data)
    stats = validate_reviewer(input_data, explicit_data, implicit_data, reviewer_data)

    paths = {
        "input": str(input_path),
        "diff": str(input_path.parent / "diff.patch"),
        "explicit": str(explicit_path),
        "implicit": str(implicit_path),
        "reviewer": str(reviewer_path),
        "report": str(out_path),
        "report_items": str(items_out_path),
        "patch_plan": str(patch_plan_path) if patch_plan_data is not None else None,
    }
    report = render_report(
        input_data,
        explicit_data,
        implicit_data,
        reviewer_data,
        stats,
        paths,
        max_items_per_group,
        patch_plan=patch_plan_data,
    )
    report_items = render_report_items(input_data, reviewer_data)

    if out_path.exists() and out_path.is_dir():
        raise ReportError(f"--out is a directory: {out_path}")
    if items_out_path.exists() and items_out_path.is_dir():
        raise ReportError(f"--items-out is a directory: {items_out_path}")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        items_out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        items_out_path.write_text(report_items, encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"Could not write report files: {exc}") from exc

    return {
        "status": "ok",
        "report_path": str(out_path),
        "report_items_path": str(items_out_path),
        "is_mixed": stats["is_mixed"],
        "confidence": stats["confidence"],
        "groups": stats["groups"],
        "items": stats["grouped_items"],
        "max_items_per_group": max_items_per_group,
    }


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        payload = write_report(args)
    except (ReportError, ExplicitValidationError, ImplicitValidationError) as exc:
        print_json({"status": "error", "message": str(exc)})
        return 1

    print_json(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
