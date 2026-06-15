import argparse
import pathlib
import sys

from validate_implicit import (
    ValidationError,
    print_json,
    read_json,
    render_pretty_report,
    validate_implicit,
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(message)


def parse_args(argv):
    parser = JsonArgumentParser(description="Show implicit-agent JSON output.")
    parser.add_argument("--input", required=True, help="Path to input.json")
    parser.add_argument("--implicit", required=True, help="Path to implicit.json")
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

    print(render_pretty_report(input_data, implicit_data, stats, implicit_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
