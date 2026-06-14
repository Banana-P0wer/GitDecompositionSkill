import argparse
import pathlib
import sys

from validate_explicit import (
    ValidationError,
    print_json,
    read_json,
    render_pretty_report,
    validate_explicit,
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(message)


def parse_args(argv):
    parser = JsonArgumentParser(description="Show explicit-agent JSON output.")
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

    print(render_pretty_report(input_data, explicit_data, stats, explicit_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
