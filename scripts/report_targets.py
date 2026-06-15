"""CLI: build local JSON and Markdown QA reports for Phase 4A target labels.

No Alpaca API calls. No network. No .env reads. No alpha, signal, strategy, model, weight,
portfolio, trading, or order logic.
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl
import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.research.target_report import (  # noqa: E402
    TargetReportError,
    build_target_qa_report,
    render_target_qa_markdown,
)


def _read_labels(path: Path) -> pl.DataFrame:
    if not path.is_file():
        raise TargetReportError(f"labels file not found: {path}")
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pl.read_csv(path, try_parse_dates=True)
    raise TargetReportError("labels file must be Parquet (.parquet) or CSV (.csv)")


def _read_manifest(path: Path) -> dict:
    if not path.is_file():
        raise TargetReportError(f"manifest file not found: {path}")
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text())
    elif path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(path.read_text())
    else:
        raise TargetReportError("manifest file must be JSON, YAML, or YML")
    if not isinstance(payload, dict):
        raise TargetReportError("manifest root must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local target-label QA report.")
    parser.add_argument("--labels", required=True, help="Labelled Parquet or CSV path")
    parser.add_argument("--manifest", required=True, help="Target manifest JSON or YAML path")
    parser.add_argument("--output-json", required=True, help="Output JSON report path")
    parser.add_argument("--output-md", required=True, help="Output Markdown report path")
    args = parser.parse_args()

    try:
        labels = _read_labels(Path(args.labels))
        manifest = _read_manifest(Path(args.manifest))
        report = build_target_qa_report(labels, manifest=manifest)
        markdown = render_target_qa_markdown(report)
        output_json = Path(args.output_json)
        output_md = Path(args.output_md)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        output_md.write_text(markdown)
    except (OSError, ValueError, TargetReportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"verdict    : {report['verdict']}")
    print(f"json_report: {output_json}")
    print(f"md_report  : {output_md}")


if __name__ == "__main__":
    main()
