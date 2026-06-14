// Package safety enforces the fail-closed boot invariants of SAFETY_POLICY.md. These are
// hard barriers, not tunable parameters: the system refuses to start rather than violate one.
package safety

import (
	"fmt"

	"github.com/maxmenac/alpaca-quant/internal/signals"
)

// AppConfig mirrors configs/app.yaml (SAFETY_POLICY.md §2). Defaults are fail-closed.
type AppConfig struct {
	Mode                 signals.Mode `json:"mode" yaml:"mode"`
	AllowLiveTrading     bool         `json:"allow_live_trading" yaml:"allow_live_trading"`
	RequireHumanApproval bool         `json:"require_human_approval" yaml:"require_human_approval"`
	MaxNotionalOrderUSD  float64      `json:"max_notional_order_usd" yaml:"max_notional_order_usd"`
	KillSwitchArmed      bool         `json:"kill_switch_armed" yaml:"kill_switch_armed"`
}

// ValidateBoot checks the resolved config at startup (SAFETY_POLICY.md §2 boot rules).
// It returns an error when the system must refuse to start.
func (c AppConfig) ValidateBoot() error {
	// mode: live but allow_live_trading: false -> inconsistent, refuse to start.
	if c.Mode == signals.ModeLive && !c.AllowLiveTrading {
		return fmt.Errorf("refusing to start: mode=live but allow_live_trading=false")
	}
	// require_human_approval: false in live -> forbidden in MVP, refuse to start.
	if c.Mode == signals.ModeLive && !c.RequireHumanApproval {
		return fmt.Errorf("refusing to start: mode=live but require_human_approval=false")
	}
	return nil
}
