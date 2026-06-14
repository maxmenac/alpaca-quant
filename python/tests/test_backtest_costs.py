"""Tests for the linear cost model. tmp_path synthetic config only — no .env, no network."""

from pathlib import Path

import pytest
import yaml

from alpaca_quant.backtest.costs.model import CostModel, CostModelError, load_cost_model


def _write_costs(path: Path) -> Path:
    path.write_text(
        yaml.dump(
            {
                "commission_bps": 0,
                "slippage_bps_daily": 5,
                "slippage_bps_stress_2x": 10,
                "slippage_bps_stress_5x": 25,
            }
        )
    )
    return path


class TestCostModel:
    def test_total_bps(self) -> None:
        assert CostModel(commission_bps=1.0, slippage_bps=5.0).total_bps == 6.0

    def test_rate(self) -> None:
        assert CostModel(slippage_bps=5.0).rate == pytest.approx(0.0005)

    def test_cost_for_turnover(self) -> None:
        model = CostModel(commission_bps=0.0, slippage_bps=5.0)
        assert model.cost_for_turnover(1.0) == pytest.approx(0.0005)
        assert model.cost_for_turnover(2.0) == pytest.approx(0.0010)

    def test_zero_turnover_zero_cost(self) -> None:
        assert CostModel(slippage_bps=5.0).cost_for_turnover(0.0) == 0.0


class TestLoadCostModel:
    def test_load_default_stress(self, tmp_path: Path) -> None:
        path = _write_costs(tmp_path / "costs.yaml")
        model = load_cost_model(path)
        assert model.commission_bps == 0.0
        assert model.slippage_bps == 5.0

    def test_load_stress_2x(self, tmp_path: Path) -> None:
        path = _write_costs(tmp_path / "costs.yaml")
        assert load_cost_model(path, stress="2x").slippage_bps == 10.0

    def test_load_stress_5x(self, tmp_path: Path) -> None:
        path = _write_costs(tmp_path / "costs.yaml")
        assert load_cost_model(path, stress="5x").slippage_bps == 25.0

    def test_unknown_stress_rejected(self, tmp_path: Path) -> None:
        path = _write_costs(tmp_path / "costs.yaml")
        with pytest.raises(CostModelError, match="unknown stress"):
            load_cost_model(path, stress="10x")

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(CostModelError, match="not found"):
            load_cost_model(tmp_path / "nope.yaml")

    def test_missing_field_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "costs.yaml"
        path.write_text(yaml.dump({"commission_bps": 0}))
        with pytest.raises(CostModelError, match="missing field"):
            load_cost_model(path)

    def test_repo_default_config_loads(self) -> None:
        # the committed configs/costs.yaml is read-only source, not a data artifact
        model = load_cost_model()
        assert model.slippage_bps == 5.0
