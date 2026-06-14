// Package config holds typed representations of the YAML configs under configs/. The MVP
// keeps this dependency-free (no YAML parser is wired in yet — see ADR-002 / ROADMAP Phase 6);
// these structs are the typed shape that loading will populate. The fail-closed AppConfig and
// its boot validation live in the safety package (SAFETY_POLICY.md §2).
package config

// RiskLimits mirrors configs/risk.yaml.
type RiskLimits struct {
	MaxPositionPct       float64 `json:"max_position_pct" yaml:"max_position_pct"`
	MaxDailyLossPct      float64 `json:"max_daily_loss_pct" yaml:"max_daily_loss_pct"`
	MaxOpenPositions     int     `json:"max_open_positions" yaml:"max_open_positions"`
	MaxGrossExposure     float64 `json:"max_gross_exposure" yaml:"max_gross_exposure"`
	MaxNetExposure       float64 `json:"max_net_exposure" yaml:"max_net_exposure"`
	RequireHumanApproval bool    `json:"require_human_approval" yaml:"require_human_approval"`
}

// Costs mirrors configs/costs.yaml.
type Costs struct {
	CommissionBps       float64 `json:"commission_bps" yaml:"commission_bps"`
	SlippageBpsDaily    float64 `json:"slippage_bps_daily" yaml:"slippage_bps_daily"`
	SlippageBpsStress2x float64 `json:"slippage_bps_stress_2x" yaml:"slippage_bps_stress_2x"`
	SlippageBpsStress5x float64 `json:"slippage_bps_stress_5x" yaml:"slippage_bps_stress_5x"`
}

// Universe mirrors configs/universe.yaml.
type Universe struct {
	UniverseID string   `json:"universe_id" yaml:"universe_id"`
	Symbols    []string `json:"symbols" yaml:"symbols"`
}
