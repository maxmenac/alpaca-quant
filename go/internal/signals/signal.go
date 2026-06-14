// Package signals defines the Python -> Go signal contract (SIGNAL_CONTRACT.md v1.1.0)
// and its fail-closed validation. Python produces target weights; Go validates them and
// (in a later sprint) transforms them into orders behind the risk gate. No broker code lives
// here.
package signals

import "time"

// Mode is the execution mode a signal targets. Go verifies it matches the process mode.
type Mode string

const (
	ModePaper Mode = "paper"
	ModeLive  Mode = "live"
)

// RebalanceType encodes the rebalancing semantics and, by construction, the authorization
// level. Only target_weight can increase exposure; the others only reduce risk.
type RebalanceType string

const (
	RebalanceTargetWeight RebalanceType = "target_weight"
	RebalanceReduceOnly   RebalanceType = "reduce_only"
	RebalanceCloseOnly    RebalanceType = "close_only"
	RebalanceToZero       RebalanceType = "rebalance_to_zero"
)

// IsExposureIncreasing reports whether this rebalance type can increase exposure.
// reduce_only / close_only / rebalance_to_zero only reduce risk and are never
// exposure-increasing (SIGNAL_CONTRACT.md §3, SAFETY_POLICY.md §1).
func (rt RebalanceType) IsExposureIncreasing() bool {
	return rt == RebalanceTargetWeight
}

// ApprovalStatus traces the "recommends, approves" human-in-the-loop decision.
type ApprovalStatus string

const (
	ApprovalPending  ApprovalStatus = "pending"
	ApprovalApproved ApprovalStatus = "approved"
	ApprovalRejected ApprovalStatus = "rejected"
)

// Target is a single per-symbol target weight with its hard per-position bound.
type Target struct {
	Symbol            string   `json:"symbol"`
	AssetClass        string   `json:"asset_class"`
	TargetWeight      float64  `json:"target_weight"`
	Conviction        float64  `json:"conviction"`
	MaxPositionWeight float64  `json:"max_position_weight"`
	ReasonCodes       []string `json:"reason_codes"`
	ReduceOnly        bool     `json:"reduce_only"`
}

// Metadata carries portfolio-level expectations and the exposure bounds checked by the
// risk gate.
type Metadata struct {
	ExpectedTurnover    float64 `json:"expected_turnover"`
	ExpectedCostBps     float64 `json:"expected_cost_bps"`
	RiskScore           float64 `json:"risk_score"`
	TargetGrossExposure float64 `json:"target_gross_exposure"`
	TargetNetExposure   float64 `json:"target_net_exposure"`
}

// Signal is the versioned, frozen contract message (SIGNAL_CONTRACT.md §1, schema v1.1.0).
type Signal struct {
	SchemaVersion string    `json:"schema_version"`
	SignalID      string    `json:"signal_id"`
	CreatedAt     time.Time `json:"created_at"`
	AsOf          time.Time `json:"as_of"`
	ValidUntil    time.Time `json:"valid_until"`

	Mode             Mode           `json:"mode"`
	RebalanceType    RebalanceType  `json:"rebalance_type"`
	GeneratedBy      string         `json:"generated_by"`
	ApprovalRequired bool           `json:"approval_required"`
	ApprovalStatus   ApprovalStatus `json:"approval_status"`

	ModelID           string `json:"model_id"`
	FeatureSetID      string `json:"feature_set_id"`
	UniverseID        string `json:"universe_id"`
	BacktestRunID     string `json:"backtest_run_id"`
	DataDeclarationID string `json:"data_declaration_id"`

	Horizon string `json:"horizon"`

	Targets  []Target `json:"targets"`
	Metadata Metadata `json:"metadata"`
}
