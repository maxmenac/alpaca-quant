"""Phase 4B target QA report tests. Synthetic/local only; no .env, network, or live data."""

import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from alpaca_quant.research.target_report import (
    BOUNDARY_NOTE,
    TargetDefinition,
    TargetReportConfig,
    TargetReportError,
    build_target_qa_report,
    render_target_qa_markdown,
)
from alpaca_quant.research.targets import (
    build_forward_return_labels,
    build_target_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "report_targets.py"
FROZEN_TIME = datetime(2026, 6, 15, 12, 30, tzinfo=UTC)


def _bars(
    closes: list[float],
    symbol: str = "AAPL",
    *,
    start_day: int = 2,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(closes),
            "timestamp": [
                datetime(2024, 1, start_day + index, tzinfo=UTC)
                for index in range(len(closes))
            ],
            "close": closes,
        }
    )


def _labelled() -> pl.DataFrame:
    # Forward returns: 0.10, -0.10, 0.00, null.
    return build_forward_return_labels(_bars([100.0, 110.0, 99.0, 99.0]))


def _manifest(df: pl.DataFrame) -> dict:
    return build_target_manifest(
        df,
        horizon=1,
        source_dataset_id="rds-test",
    ).to_dict()


def _config(**overrides: object) -> TargetReportConfig:
    values = {
        "max_null_pct": 30.0,
        "extreme_return_threshold": 1.0,
        **overrides,
    }
    return TargetReportConfig(**values)


def _report(
    df: pl.DataFrame | None = None,
    *,
    manifest: dict | None = None,
    config: TargetReportConfig | None = None,
) -> dict:
    frame = df if df is not None else _labelled()
    resolved_manifest = _manifest(frame) if manifest is None else manifest
    return build_target_qa_report(
        frame,
        manifest=resolved_manifest,
        config=config or _config(),
        clock=lambda: FROZEN_TIME,
    )


def _warning_codes(report: dict) -> set[str]:
    return {item["code"] for item in report["warnings"]}


def test_report_computes_exact_small_fixture_stats() -> None:
    report = _report()
    stats = report["per_horizon"][0]
    assert report["schema_version"] == 1
    assert report["verdict"] == "OK"
    assert stats["horizon"] == 1
    assert stats["target_column"] == "label_forward_return_1d"
    assert stats["n_total"] == 4
    assert stats["n_valid"] == 3
    assert stats["n_null"] == 1
    assert stats["n_non_finite"] == 0
    assert stats["null_pct"] == pytest.approx(25.0)
    assert stats["mean"] == pytest.approx(0.0)
    assert stats["std"] == pytest.approx(0.1)
    assert stats["min"] == pytest.approx(-0.1)
    assert stats["max"] == pytest.approx(0.1)
    assert stats["p01"] == pytest.approx(-0.098)
    assert stats["p05"] == pytest.approx(-0.09)
    assert stats["p50"] == pytest.approx(0.0)
    assert stats["p95"] == pytest.approx(0.09)
    assert stats["p99"] == pytest.approx(0.098)


def test_target_metadata_and_monthly_summary_are_present() -> None:
    report = _report()
    metadata = report["target_set"]
    assert metadata["target_set_id"].startswith("tgt-")
    assert metadata["fingerprint"].startswith("sha256:")
    assert metadata["source"] == "rds-test"
    assert metadata["horizons"] == [1]
    assert metadata["target_columns"] == ["label_forward_return_1d"]
    assert report["per_period"][0]["period"] == "2024-01"
    assert report["per_period"][0]["n_rows"] == 4


def test_missing_declared_target_column_raises() -> None:
    manifest = _manifest(_labelled())
    manifest["label_column"] = "label_forward_return_5d"
    manifest["horizon"] = 5
    with pytest.raises(TargetReportError, match="missing required target column"):
        _report(manifest=manifest)


def test_manifest_and_config_disagreement_raises_without_inference() -> None:
    config = _config(
        targets=(TargetDefinition(horizon=5, column="label_forward_return_5d"),)
    )
    with pytest.raises(TargetReportError, match="definitions disagree"):
        _report(config=config)


def test_unsupported_manifest_schema_raises_clearly() -> None:
    manifest = _manifest(_labelled())
    manifest["schema_version"] = 999
    with pytest.raises(TargetReportError, match="unsupported target manifest"):
        _report(manifest=manifest)


def test_nulls_are_counted_and_never_filled() -> None:
    frame = _labelled()
    report = _report(frame)
    assert frame["label_forward_return_1d"].to_list()[-1] is None
    assert report["per_horizon"][0]["n_null"] == 1
    assert report["per_horizon"][0]["n_valid"] == 3
    assert report["null_breakdown"]["data"]["label_forward_return_1d"] == {
        "insufficient_future_rows": 1
    }


def test_too_many_nulls_marks_report_suspect() -> None:
    report = _report(config=_config(max_null_pct=10.0))
    assert report["verdict"] == "SUSPECT"
    assert "high_null_fraction" in _warning_codes(report)


def test_extreme_returns_produce_warning() -> None:
    frame = build_forward_return_labels(_bars([100.0, 250.0, 250.0]))
    report = _report(
        frame,
        manifest=_manifest(frame),
        config=_config(max_null_pct=40.0, extreme_return_threshold=1.0),
    )
    assert report["verdict"] == "SUSPECT"
    assert "extreme_return" in _warning_codes(report)


def test_non_finite_values_are_preserved_and_warned() -> None:
    frame = _labelled().with_columns(
        pl.when(pl.col("timestamp") == pl.col("timestamp").min())
        .then(pl.lit(float("inf")))
        .otherwise(pl.col("label_forward_return_1d"))
        .alias("label_forward_return_1d")
    )
    report = build_target_qa_report(
        frame,
        config=_config(
            targets=(TargetDefinition(1, "label_forward_return_1d"),),
        ),
        clock=lambda: FROZEN_TIME,
    )
    stats = report["per_horizon"][0]
    assert math.isinf(frame["label_forward_return_1d"][0])
    assert stats["n_non_finite"] == 1
    assert stats["n_valid"] == 2
    assert "non_finite_values" in _warning_codes(report)
    json.dumps(report, allow_nan=False)


def test_multi_horizon_report_does_not_misattribute_single_null_ledger() -> None:
    bars = _bars([100.0, 110.0, 121.0, 133.1])
    one = build_forward_return_labels(bars, horizon=1)
    two = build_forward_return_labels(bars, horizon=2).select(
        ["symbol", "timestamp", "label_forward_return_2d"]
    )
    frame = one.join(two, on=["symbol", "timestamp"])
    manifest = {
        "schema_version": 1,
        "target_set_id": "tgt-multi-horizon",
        "source": "synthetic",
        "targets": [
            {"horizon": 1, "label_column": "label_forward_return_1d"},
            {"horizon": 2, "label_column": "label_forward_return_2d"},
        ],
        "null_breakdown": {
            "label_forward_return_1d": {"insufficient_future_rows": 1},
            "label_forward_return_2d": {"insufficient_future_rows": 2},
        },
    }
    report = _report(
        frame,
        manifest=manifest,
        config=_config(max_null_pct=60.0),
    )
    assert [item["horizon"] for item in report["per_horizon"]] == [1, 2]
    assert report["null_breakdown"]["data"] == {}
    assert "ambiguous_null_reason_ledger" in _warning_codes(report)


def test_manifest_data_mismatch_marks_report_suspect() -> None:
    manifest = _manifest(_labelled())
    manifest["row_count"] = 999
    report = _report(manifest=manifest)
    assert report["verdict"] == "SUSPECT"
    assert "manifest_data_mismatch" in _warning_codes(report)


def test_missing_manifest_marks_report_suspect_but_infers_phase4a_column() -> None:
    report = build_target_qa_report(
        _labelled(),
        config=_config(),
        clock=lambda: FROZEN_TIME,
    )
    assert report["target_set"]["manifest_available"] is False
    assert report["target_set"]["horizons"] == [1]
    assert report["verdict"] == "SUSPECT"
    assert "missing_manifest" in _warning_codes(report)


def test_per_symbol_counts_and_distribution() -> None:
    frame = pl.concat(
        [
            build_forward_return_labels(_bars([100.0, 110.0, 121.0], "AAPL")),
            build_forward_return_labels(_bars([200.0, 190.0, 180.5], "MSFT")),
        ]
    )
    manifest = {
        "schema_version": 1,
        "target_set_id": "tgt-multi",
        "source": "synthetic",
        "targets": [{"horizon": 1, "label_column": "label_forward_return_1d"}],
    }
    report = _report(
        frame,
        manifest=manifest,
        config=_config(max_null_pct=40.0),
    )
    assert [item["symbol"] for item in report["per_symbol"]] == ["AAPL", "MSFT"]
    for item in report["per_symbol"]:
        stats = item["targets"]["label_forward_return_1d"]
        assert item["n_rows"] == 3
        assert stats["n_valid"] == 2
        assert stats["n_null"] == 1
        assert "mean" in stats


def test_generated_at_utc_uses_injected_clock() -> None:
    report = _report()
    assert report["generated_at_utc"] == "2026-06-15T12:30:00+00:00"


def test_markdown_contains_required_sections_and_boundary_note() -> None:
    markdown = render_target_qa_markdown(_report())
    assert markdown.startswith("# Target QA Report")
    assert "Summary verdict: OK" in markdown
    assert "## Per-Horizon Statistics" in markdown
    assert "## Null Breakdown" in markdown
    assert "## Per-Symbol Summary" in markdown
    assert "## Warnings" in markdown
    assert BOUNDARY_NOTE in markdown


def test_upstream_data_responsibility_warning_is_explicit() -> None:
    messages = " ".join(item["message"] for item in _report()["warnings"])
    assert "Adjusted close" in messages
    assert "point-in-time universe" in messages
    assert "survivorship bias" in messages


def test_report_and_cli_have_no_network_env_or_alpaca_client_imports() -> None:
    source = (
        (REPO_ROOT / "python/alpaca_quant/research/target_report.py").read_text()
        + (REPO_ROOT / "scripts/report_targets.py").read_text()
    )
    for forbidden in (
        "load_dotenv",
        "requests.",
        "urllib.request",
        "http.client",
        "alpaca.data",
        "TradingClient",
    ):
        assert forbidden not in source


def test_cli_writes_json_and_markdown_to_tmp_path_only(tmp_path: Path) -> None:
    labels = tmp_path / "labels.parquet"
    manifest_path = tmp_path / "manifest.json"
    output_json = tmp_path / "reports" / "target_report.json"
    output_md = tmp_path / "reports" / "target_report.md"
    frame = _labelled()
    frame.write_parquet(labels)
    manifest_path.write_text(json.dumps(_manifest(frame)))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--labels",
            str(labels),
            "--manifest",
            str(manifest_path),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output_json.is_file()
    assert output_md.is_file()
    parsed = json.loads(output_json.read_text())
    assert parsed["schema_version"] == 1
    assert parsed["target_set"]["target_set_id"].startswith("tgt-")
    assert "# Target QA Report" in output_md.read_text()
    assert not (REPO_ROOT / "targets_manifest.json").exists()
    assert not (REPO_ROOT / "targets_labelled.csv").exists()
    assert not (REPO_ROOT / "targets_labelled.parquet").exists()
