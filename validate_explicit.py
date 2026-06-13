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


def check_required_top_level(explicit_data):
    ensure_object(explicit_data, "explicit.json")
    if explicit_data.get("agent") != "explicit-agent":
        raise ValidationError('explicit.json agent must be "explicit-agent"')
    if explicit_data.get("schema_version") != 1:
        raise ValidationError("explicit.json schema_version must be 1")

    groups = explicit_data.get("groups")
    ungrouped_item_ids = explicit_data.get("ungrouped_item_ids")
    warnings = explicit_data.get("warnings")
    ensure_list(groups, "explicit.json groups")
    ensure_list(ungrouped_item_ids, "explicit.json ungrouped_item_ids")
    ensure_list(warnings, "explicit.json warnings")
    return groups, ungrouped_item_ids


def add_seen_id(seen_ids, expected_set, item_id):
    if not isinstance(item_id, str) or not item_id:
        raise ValidationError("Invalid item id in explicit.json")
    if item_id not in expected_set:
        raise ValidationError(f"Unknown item id: {item_id}")
    if item_id in seen_ids:
        raise ValidationError(f"Duplicate item id: {item_id}")
    seen_ids.append(item_id)


def validate_groups(groups, expected_set):
    seen_ids = []

    for index, group in enumerate(groups):
        ensure_object(group, f"explicit.json groups[{index}]")
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValidationError(f"Missing group_id at groups[{index}]")

        item_ids = group.get("item_ids")
        ensure_list(item_ids, f"explicit.json groups[{index}].item_ids")
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


def validate_explicit(input_data, explicit_data):
    expected_ids = get_expected_item_ids(input_data)
    expected_set = set(expected_ids)
    groups, ungrouped_item_ids = check_required_top_level(explicit_data)

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


def parse_args(argv):
    parser = JsonArgumentParser(description="Validate explicit-agent JSON output.")
    parser.add_argument("--input", required=True, help="Path to input.json")
    parser.add_argument("--explicit", required=True, help="Path to explicit.json")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        input_path = pathlib.Path(args.input).expanduser()
        explicit_path = pathlib.Path(args.explicit).expanduser()
        input_data = read_json(input_path)
        explicit_data = read_json(explicit_path)
        stats = validate_explicit(input_data, explicit_data)
    except ValidationError as exc:
        print_json({"status": "error", "message": str(exc)})
        return 1

    print_json(
        {
            "status": "ok",
            "expected_items": stats["expected_items"],
            "grouped_items": stats["grouped_items"],
            "groups": stats["groups"],
            "explicit_path": str(explicit_path),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
