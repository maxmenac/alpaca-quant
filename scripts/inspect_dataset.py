"""CLI: inspect a local Phase 4C dataset against feature-registry metadata (4D).

Phase 4D: dataset + feature metadata inspection only. No feature computation, no model training,
no CV, no alpha/signal/strategy/optimizer/weight/portfolio/backtest/order. No Alpaca API. No
network. No .env. Writes only to caller-specified output paths (never into data/runs/).
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl
import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.research.dataset_report import (  # noqa: E402
    DatasetReportError,
    attach_feature_set_id,
    build_dataset_inspection_report,
    render_dataset_inspection_markdown,
)
from alpaca_quant.research.feature_registry import (  # noqa: E402
    FeatureDefinition,
    build_registry,
    compute_feature_set_id,
)


def _read_frame(path: Path) -> pl.DataFrame:
    if not path.is_file():
        raise DatasetReportError(f"input file not found: {path}")
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pl.read_csv(path, try_parse_dates=True)
    raise DatasetReportError("dataset must be Parquet (.parquet) or CSV (.csv)")


def _read_doc(path: Path) -> object:
    if not path.is_file():
        raise DatasetReportError(f"file not found: {path}")
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text())
    raise DatasetReportError("metadata files must be JSON, YAML, or YML")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a local 4C dataset (4D, metadata only).")
    parser.add_argument("--dataset", required=True, help="Assembled dataset Parquet/CSV path")
    parser.add_argument("--manifest", required=True, help="Dataset manifest JSON/YAML path")
    parser.add_argument("--feature-registry", help="Optional feature registry JSON/YAML path")
    parser.add_argument("--output-json", required=True, help="Report JSON output path")
    parser.add_argument("--output-md", required=True, help="Report Markdown output path")
    args = parser.parse_args()

    try:
        frame = _read_frame(Path(args.dataset))
        manifest = _read_doc(Path(args.manifest))
        if not isinstance(manifest, dict):
            raise DatasetReportError("manifest root must be an object")

        definitions = []
        if args.feature_registry:
            payload = _read_doc(Path(args.feature_registry))
            raw = payload.get("features", payload) if isinstance(payload, dict) else payload
            if not isinstance(raw, list):
                raise DatasetReportError("feature registry must be a list of definitions")
            definitions = [FeatureDefinition(**item) for item in raw]
        registry = build_registry(definitions)

        requested = list(manifest.get("feature_columns", []))
        report = build_dataset_inspection_report(
            frame, manifest=manifest, registry=registry, requested_features=requested
        )
        known = [d for d in definitions if d.name in requested]
        if known:
            report = attach_feature_set_id(report, compute_feature_set_id(known))
        markdown = render_dataset_inspection_markdown(report)

        output_json = Path(args.output_json)
        output_md = Path(args.output_md)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        output_md.write_text(markdown)
    except (OSError, ValueError, KeyError, TypeError, DatasetReportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"verdict    : {report['verdict']}")
    print(f"dataset_id : {report.get('dataset_id')}")
    print(f"json_report: {output_json}")
    print(f"md_report  : {output_md}")


if __name__ == "__main__":
    main()
