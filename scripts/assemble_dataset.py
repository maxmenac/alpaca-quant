"""CLI: assemble a local PIT-safe ML dataset and write its manifest (JSON + Markdown).

Phase 4C: dataset assembly only. No model training, no CV, no alpha, no signal, no strategy,
no optimizer, no portfolio, no backtest, no trading. No Alpaca API calls. No network. No .env.

This CLI writes only the dataset manifest (JSON/Markdown) and, optionally, the assembled dataset
to a caller-specified path. It never writes into data/runs/ by default.
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl
import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.research.data_contract import FeatureSpec  # noqa: E402
from alpaca_quant.research.dataset_manifest import (  # noqa: E402
    render_dataset_manifest_markdown,
)
from alpaca_quant.research.ml_dataset import (  # noqa: E402
    DatasetConfig,
    MLDatasetError,
    assemble_ml_dataset,
)


def _read_frame(path: Path) -> pl.DataFrame:
    if not path.is_file():
        raise MLDatasetError(f"input file not found: {path}")
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pl.read_csv(path, try_parse_dates=True)
    raise MLDatasetError("input frames must be Parquet (.parquet) or CSV (.csv)")


def _read_spec(path: Path) -> dict:
    if not path.is_file():
        raise MLDatasetError(f"spec file not found: {path}")
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text())
    elif path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(path.read_text())
    else:
        raise MLDatasetError("spec file must be JSON, YAML, or YML")
    if not isinstance(payload, dict):
        raise MLDatasetError("spec root must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble a local PIT-safe ML dataset (4C).")
    parser.add_argument("--labels", required=True, help="Labelled Parquet or CSV path")
    parser.add_argument("--features", required=True, help="Features Parquet or CSV path")
    parser.add_argument("--spec", required=True, help="Assembly spec JSON/YAML path")
    parser.add_argument("--universe", help="Optional PIT universe Parquet/CSV path")
    parser.add_argument("--identity", help="Optional symbol identity Parquet/CSV path")
    parser.add_argument("--reference", help="Optional reference/fundamental Parquet/CSV path")
    parser.add_argument("--output-json", required=True, help="Manifest JSON output path")
    parser.add_argument("--output-md", required=True, help="Manifest Markdown output path")
    parser.add_argument("--output-dataset", help="Optional assembled dataset Parquet output path")
    args = parser.parse_args()

    try:
        spec = _read_spec(Path(args.spec))
        labels = _read_frame(Path(args.labels))
        features = _read_frame(Path(args.features))
        universe = _read_frame(Path(args.universe)) if args.universe else None
        identity = _read_frame(Path(args.identity)) if args.identity else None
        reference = _read_frame(Path(args.reference)) if args.reference else None

        feature_specs = [
            item if isinstance(item, dict) else {"name": item}
            for item in spec["feature_specs"]
        ]
        config = DatasetConfig(**spec.get("config", {}))
        result = assemble_ml_dataset(
            labels=labels,
            features=features,
            feature_specs=[FeatureSpec(**fs) for fs in feature_specs],
            label_columns=spec["label_columns"],
            label_horizons=spec.get("label_horizons"),
            universe=universe,
            identity=identity,
            reference=reference,
            reference_value_columns=spec.get("reference_value_columns", []),
            id_column=spec.get("id_column", "symbol"),
            config=config,
            config_payload=spec,
        )
        manifest = result.manifest
        markdown = render_dataset_manifest_markdown(manifest)

        output_json = Path(args.output_json)
        output_md = Path(args.output_md)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        output_md.write_text(markdown)
        if args.output_dataset:
            dataset_path = Path(args.output_dataset)
            dataset_path.parent.mkdir(parents=True, exist_ok=True)
            result.frame.write_parquet(dataset_path)
    except (OSError, ValueError, KeyError, MLDatasetError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"verdict      : {manifest.verdict}")
    print(f"dataset_id   : {manifest.dataset_id}")
    print(f"rows/eligible: {manifest.row_count}/{manifest.eligible_row_count}")
    print(f"json_manifest: {output_json}")
    print(f"md_manifest  : {output_md}")


if __name__ == "__main__":
    main()
