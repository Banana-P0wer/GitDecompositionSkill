import argparse
import pathlib
import sys

from validate_implicit import (
    ValidationError,
    build_item_index,
    ensure_list,
    ensure_object,
    get_expected_item_ids,
    print_json,
    read_json,
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(message)


def ensure_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Missing {label}")


def validate_supporting_agent(data, label, expected_agent):
    ensure_object(data, f"{label}.json")
    if data.get("agent") != expected_agent:
        raise ValidationError(f'{label}.json agent must be "{expected_agent}"')


def check_required_top_level(reviewer_data):
    ensure_object(reviewer_data, "reviewer.json")
    if reviewer_data.get("agent") != "reviewer-agent":
        raise ValidationError('reviewer.json agent must be "reviewer-agent"')
    if reviewer_data.get("schema_version") != 1:
        raise ValidationError("reviewer.json schema_version must be 1")

    is_mixed = reviewer_data.get("is_mixed")
    if not isinstance(is_mixed, bool):
        raise ValidationError("reviewer.json is_mixed must be a boolean")

    confidence = reviewer_data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValidationError("reviewer.json confidence must be a number")
    if confidence < 0.0 or confidence > 1.0:
        raise ValidationError("reviewer.json confidence must be between 0.0 and 1.0")

    if "ungrouped_item_ids" in reviewer_data:
        raise ValidationError("reviewer.json must not use ungrouped_item_ids")

    groups = reviewer_data.get("groups")
    disagreements_resolved = reviewer_data.get("disagreements_resolved")
    warnings = reviewer_data.get("warnings")
    ensure_list(groups, "reviewer.json groups")
    ensure_list(disagreements_resolved, "reviewer.json disagreements_resolved")
    ensure_list(warnings, "reviewer.json warnings")

    return groups, disagreements_resolved, is_mixed, confidence


def add_seen_id(seen_ids, expected_set, item_id, label):
    if not isinstance(item_id, str) or not item_id:
        raise ValidationError(f"Invalid item id in {label}")
    if item_id not in expected_set:
        raise ValidationError(f"Unknown item id: {item_id}")
    if item_id in seen_ids:
        raise ValidationError(f"Duplicate item id: {item_id}")
    seen_ids.append(item_id)


def validate_evidence(evidence, index):
    ensure_object(evidence, f"reviewer.json groups[{index}].evidence")
    if not evidence:
        raise ValidationError(f"Missing evidence at groups[{index}]")

    explicit_evidence = evidence.get("explicit")
    implicit_evidence = evidence.get("implicit")
    ensure_non_empty_string(explicit_evidence, f"evidence.explicit at groups[{index}]")
    ensure_non_empty_string(implicit_evidence, f"evidence.implicit at groups[{index}]")


def validate_groups(groups, expected_set):
    seen_ids = []

    for index, group in enumerate(groups):
        ensure_object(group, f"reviewer.json groups[{index}]")
        group_id = group.get("group_id")
        ensure_non_empty_string(group_id, f"group_id at groups[{index}]")

        item_ids = group.get("item_ids")
        ensure_list(item_ids, f"reviewer.json groups[{index}].item_ids")
        if not item_ids:
            raise ValidationError(f"Empty group item_ids at groups[{index}]")

        summary = group.get("summary")
        ensure_non_empty_string(summary, f"summary at groups[{index}]")

        why = group.get("why")
        ensure_non_empty_string(why, f"why at groups[{index}]")

        validate_evidence(group.get("evidence"), index)

        for item_id in item_ids:
            add_seen_id(
                seen_ids,
                expected_set,
                item_id,
                f"reviewer.json groups[{index}].item_ids",
            )

    return seen_ids


def validate_disagreements(disagreements_resolved, expected_set):
    for index, disagreement in enumerate(disagreements_resolved):
        ensure_object(disagreement, f"reviewer.json disagreements_resolved[{index}]")
        item_ids = disagreement.get("item_ids", [])
        ensure_list(
            item_ids,
            f"reviewer.json disagreements_resolved[{index}].item_ids",
        )
        for item_id in item_ids:
            if not isinstance(item_id, str) or not item_id:
                raise ValidationError(
                    f"Invalid item id in disagreements_resolved[{index}]"
                )
            if item_id not in expected_set:
                raise ValidationError(f"Unknown item id: {item_id}")


def validate_reviewer(input_data, explicit_data, implicit_data, reviewer_data):
    expected_ids = get_expected_item_ids(input_data)
    expected_set = set(expected_ids)

    validate_supporting_agent(explicit_data, "explicit", "explicit-agent")
    validate_supporting_agent(implicit_data, "implicit", "implicit-agent")

    groups, disagreements_resolved, is_mixed, confidence = check_required_top_level(
        reviewer_data
    )
    seen_ids = validate_groups(groups, expected_set)
    validate_disagreements(disagreements_resolved, expected_set)

    seen_set = set(seen_ids)
    missing_ids = [item_id for item_id in expected_ids if item_id not in seen_set]
    if missing_ids:
        raise ValidationError(f"Missing item id: {missing_ids[0]}")

    validation_warnings = []
    if len(groups) > 1 and not is_mixed:
        raise ValidationError("reviewer.json is_mixed must be true when groups > 1")
    if len(groups) == 1 and is_mixed:
        validation_warnings.append(
            "reviewer.json is_mixed is true with one final group"
        )

    return {
        "expected_items": len(expected_ids),
        "grouped_items": len(seen_ids),
        "groups": len(groups),
        "is_mixed": is_mixed,
        "confidence": confidence,
        "validation_warnings": validation_warnings,
    }


def render_disagreements(disagreements_resolved):
    lines = []
    if not disagreements_resolved:
        return lines

    lines.append("")
    lines.append("Disagreements resolved:")
    for disagreement in disagreements_resolved:
        item_ids = ", ".join(disagreement.get("item_ids", []))
        lines.append(f"- Items: {item_ids}")
        explicit_position = disagreement.get("explicit_position")
        implicit_position = disagreement.get("implicit_position")
        decision = disagreement.get("decision")
        reason = disagreement.get("reason")
        if explicit_position:
            lines.append(f"  Explicit: {explicit_position}")
        if implicit_position:
            lines.append(f"  Implicit: {implicit_position}")
        if decision:
            lines.append(f"  Decision: {decision}")
        if reason:
            lines.append(f"  Reason: {reason}")
    return lines


def render_pretty_report(input_data, reviewer_data, stats, reviewer_path):
    item_index = build_item_index(input_data)
    mixed_label = "yes" if stats["is_mixed"] else "no"
    lines = [
        "Reviewer Agent Result",
        "Status: ok",
        f"Mixed: {mixed_label}",
        f"Confidence: {stats['confidence']}",
        f"Groups: {stats['groups']}",
        f"Items: {stats['grouped_items']}/{stats['expected_items']}",
        f"File: {reviewer_path}",
    ]

    validation_warnings = stats.get("validation_warnings", [])
    if validation_warnings:
        lines.append("")
        lines.append("Validator warnings:")
        for warning in validation_warnings:
            lines.append(f"- {warning}")

    for group in reviewer_data.get("groups", []):
        lines.append("")
        lines.append(f"Group {group['group_id']}: {group['summary']}")
        lines.append("Items:")
        for item_id in group["item_ids"]:
            lines.append(f"- {item_index.get(item_id, item_id)}")
        lines.append("")
        lines.append("Why:")
        lines.append(group["why"])
        lines.append("")
        lines.append("Evidence:")
        evidence = group["evidence"]
        lines.append(f"explicit: {evidence.get('explicit', '')}")
        lines.append(f"implicit: {evidence.get('implicit', '')}")

    lines.extend(render_disagreements(reviewer_data.get("disagreements_resolved", [])))

    warnings = reviewer_data.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def parse_args(argv):
    parser = JsonArgumentParser(description="Validate reviewer-agent JSON output.")
    parser.add_argument("--input", required=True, help="Path to input.json")
    parser.add_argument("--explicit", required=True, help="Path to explicit.json")
    parser.add_argument("--implicit", required=True, help="Path to implicit.json")
    parser.add_argument("--reviewer", required=True, help="Path to reviewer.json")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print a human-readable reviewer-agent report after validation",
    )
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        input_path = pathlib.Path(args.input).expanduser()
        explicit_path = pathlib.Path(args.explicit).expanduser()
        implicit_path = pathlib.Path(args.implicit).expanduser()
        reviewer_path = pathlib.Path(args.reviewer).expanduser()
        input_data = read_json(input_path)
        explicit_data = read_json(explicit_path)
        implicit_data = read_json(implicit_path)
        reviewer_data = read_json(reviewer_path)
        stats = validate_reviewer(input_data, explicit_data, implicit_data, reviewer_data)
    except ValidationError as exc:
        print_json({"status": "error", "message": str(exc)})
        return 1

    if args.pretty:
        print(render_pretty_report(input_data, reviewer_data, stats, reviewer_path))
    else:
        payload = {
            "status": "ok",
            "expected_items": stats["expected_items"],
            "grouped_items": stats["grouped_items"],
            "groups": stats["groups"],
            "is_mixed": stats["is_mixed"],
            "confidence": stats["confidence"],
            "reviewer_path": str(reviewer_path),
        }
        if stats["validation_warnings"]:
            payload["validation_warnings"] = stats["validation_warnings"]
        print_json(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
