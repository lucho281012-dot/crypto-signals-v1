"""Read-only export of a validated paper report history to dashboard JSON.

The input must be the dedicated report-history file, never paper_state.json.
This command writes JSON to stdout only; it does not modify files, contact
exchanges, or interact with the paper trading bot.
"""
import argparse
import sys
from pathlib import Path

from paper_report_history import serialize_report_history
from paper_report_json_store import load_report_history


def export_history_json(source_path):
    """Load and validate a dedicated history file, returning dashboard JSON."""
    source = Path(source_path)
    if source.name == "paper_state.json":
        raise ValueError("refusing to export the operational paper_state.json")
    history = load_report_history(source)
    return serialize_report_history(history)


def main(argv=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = argparse.ArgumentParser(
        description="Export a validated paper report-history JSON file to stdout."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the dedicated report-history JSON file (not paper_state.json).",
    )
    args = parser.parse_args(argv)
    try:
        payload = export_history_json(args.input)
    except (OSError, ValueError) as exc:
        print(f"Export refused: {exc}", file=stderr)
        return 2
    stdout.write(payload)
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
