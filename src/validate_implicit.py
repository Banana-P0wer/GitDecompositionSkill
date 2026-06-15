import argparse
import json
import pathlib
import sys


class ValidationError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(message)


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False))


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"File not found: {path}") from exc
    except OSError as exc:
        raise ValidationError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {path}: {exc}") from exc


def ensure_object(value, label):
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")


def ensure_list(value, label):
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be a list")


def add_expected_id(expected_ids, item_id, source):
    if not isinstance(item_id, str) or not item_id:
        raise ValidationError(f"Invalid item id in {source}")
    if item_id in expected_ids:
        raise ValidationError(f"Duplicate expected item id in input.json: {item_id}")
    expected_ids.append(item_id)


def get_expected_item_ids(input_data):
    ensure_object(input_data, "input.json")

    expected_ids = []
    analysis_items = input_data.get("analysis_items")
    if analysis_items is not None:
        ensure_list(analysis_items, "input.json analysis_items")
        for index, item in enumerate(analysis_items):
            ensure_object(item, f"input.json analysis_items[{index}]")
            add_expected_id(expected_ids, item.get("id"), "analysis_items")
        return expected_ids

    changes = input_data.get("changes", [])
    ensure_list(changes, "input.json changes")
    for index, change in enumerate(changes):
        ensure_object(change, f"input.json changes[{index}]")
        add_expected_id(expected_ids, change.get("change_id"), "changes")

    file_events = input_data.get("file_events", [])
    ensure_list(file_events, "input.json file_events")
    for index, event in enumerate(file_events):
        ensure_object(event, f"input.json file_events[{index}]")
        add_expected_id(expected_ids, event.get("event_id"), "file_events")

    return expected_ids


def check_required_top_level(implicit_data):
    ensure_object(implicit_data, "implicit.json")
    if implicit_data.get("agent") != "implicit-agent":
        raise ValidationError('implicit.json agent must be "implicit-agent"')
    if implicit_data.get("schema_version") != 1:
        raise ValidationError("implicit.json schema_version must be 1")

    groups = implicit_data.get("groups")
    ungrouped_item_ids = implicit_data.get("ungrouped_item_ids")
    warnings = implicit_data.get("warnings")
    ensure_list(groups, "implicit.json groups")
    ensure_list(ungrouped_item_ids, "implicit.json ungrouped_item_ids")
    ensure_list(warnings, "implicit.json warnings")
    return groups, ungrouped_item_ids


def add_seen_id(seen_ids, expected_set, item_id):
    if not isinstance(item_id, str) or not item_id:
        raise ValidationError("Invalid item id in implicit.json")
    if item_id not in expected_set:
        raise ValidationError(f"Unknown item id: {item_id}")
    if item_id in seen_ids:
        raise ValidationError(f"Duplicate item id: {item_id}")
    seen_ids.append(item_id)


def validate_groups(groups, expected_set):
    seen_ids = []

    for index, group in enumerate(groups):
        ensure_object(group, f"implicit.json groups[{index}]")
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValidationError(f"Missing group_id at groups[{index}]")

        item_ids = group.get("item_ids")
        ensure_list(item_ids, f"implicit.json groups[{index}].item_ids")
        if not item_ids:
            raise ValidationError(f"Empty group item_ids at groups[{index}]")

        summary = group.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValidationError(f"Missing summary at groups[{index}]")

        reason = group.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError(f"Missing reason at groups[{index}]")

        for item_id in item_ids:
            add_seen_id(seen_ids, expected_set, item_id)

    return seen_ids


def validate_ungrouped(ungrouped_item_ids, expected_set, seen_ids):
    for item_id in ungrouped_item_ids:
        add_seen_id(seen_ids, expected_set, item_id)


def validate_implicit(input_data, implicit_data):
    expected_ids = get_expected_item_ids(input_data)
    expected_set = set(expected_ids)
    groups, ungrouped_item_ids = check_required_top_level(implicit_data)

    seen_ids = validate_groups(groups, expected_set)
    validate_ungrouped(ungrouped_item_ids, expected_set, seen_ids)

    seen_set = set(seen_ids)
    missing_ids = [item_id for item_id in expected_ids if item_id not in seen_set]
    if missing_ids:
        raise ValidationError(f"Missing item id: {missing_ids[0]}")

    return {
        "expected_items": len(expected_ids),
        "grouped_items": len(seen_ids),
        "groups": len(groups),
    }


def trim_text(text, limit=160):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def format_file_event(event):
    event_id = event.get("event_id", "<unknown>")
    status = event.get("status", "unknown")
    old_path = event.get("old_path")
    path = event.get("path")

    if status in ("renamed", "copied"):
        return f"{event_id} {status} {old_path} -> {path}"
    if status == "deleted":
        return f"{event_id} deleted {old_path or path}"
    if status == "added":
        return f"{event_id} added {path}"
    if status == "modified":
        return f"{event_id} modified {path}"
    return f"{event_id} {status} {old_path or path}"


def format_line_change(change):
    change_id = change.get("change_id", "<unknown>")
    file_path = change.get("file") or change.get("old_file") or "<unknown>"
    op = change.get("op", "?")
    line = change.get("new_line") if op == "+" else change.get("old_line")
    line_label = f":{line}" if line is not None else ""
    text = trim_text(change.get("text", ""))
    if op == "+":
        action = "added"
    elif op == "-":
        action = "removed"
    else:
        action = "changed"
    return f"{change_id} {file_path}{line_label} {action}: {text}"


def build_item_index(input_data):
    item_index = {}

    for event in input_data.get("file_events", []):
        if isinstance(event, dict):
            event_id = event.get("event_id")
            if isinstance(event_id, str):
                item_index[event_id] = format_file_event(event)

    for change in input_data.get("changes", []):
        if isinstance(change, dict):
            change_id = change.get("change_id")
            if isinstance(change_id, str):
                item_index[change_id] = format_line_change(change)

    for item in input_data.get("analysis_items", []):
        if isinstance(item, dict):
            item_id = item.get("id")
            kind = item.get("kind", "unknown")
            if isinstance(item_id, str) and item_id not in item_index:
                item_index[item_id] = f"{item_id} {kind}"

    return item_index


def render_pretty_report(input_data, implicit_data, stats, implicit_path):
    item_index = build_item_index(input_data)
    lines = [
        "Implicit Agent Result",
        "Status: ok",
        f"Groups: {stats['groups']}",
        f"Items: {stats['grouped_items']}/{stats['expected_items']}",
        f"File: {implicit_path}",
    ]

    groups = implicit_data.get("groups", [])
    for group in groups:
        lines.append("")
        lines.append(f"Group {group['group_id']}: {group['summary']}")
        lines.append("Items:")
        for item_id in group["item_ids"]:
            lines.append(f"- {item_index.get(item_id, item_id)}")
        lines.append("")
        lines.append("Reason:")
        lines.append(group["reason"])

    ungrouped_item_ids = implicit_data.get("ungrouped_item_ids", [])
    if ungrouped_item_ids:
        lines.append("")
        lines.append("Ungrouped items:")
        for item_id in ungrouped_item_ids:
            lines.append(f"- {item_index.get(item_id, item_id)}")

    warnings = implicit_data.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def parse_args(argv):
    parser = JsonArgumentParser(description="Validate implicit-agent JSON output.")
    parser.add_argument("--input", required=True, help="Path to input.json")
    parser.add_argument("--implicit", required=True, help="Path to implicit.json")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print a human-readable implicit-agent report after validation",
    )
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        input_path = pathlib.Path(args.input).expanduser()
        implicit_path = pathlib.Path(args.implicit).expanduser()
        input_data = read_json(input_path)
        implicit_data = read_json(implicit_path)
        stats = validate_implicit(input_data, implicit_data)
    except ValidationError as exc:
        print_json({"status": "error", "message": str(exc)})
        return 1

    if args.pretty:
        print(render_pretty_report(input_data, implicit_data, stats, implicit_path))
    else:
        print_json(
            {
                "status": "ok",
                "expected_items": stats["expected_items"],
                "grouped_items": stats["grouped_items"],
                "groups": stats["groups"],
                "implicit_path": str(implicit_path),
            }
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
