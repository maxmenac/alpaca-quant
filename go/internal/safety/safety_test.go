package safety

import (
	"testing"

	"github.com/maxmenac/alpaca-quant/internal/signals"
)

func TestPaperConfigBootsClean(t *testing.T) {
	cfg := AppConfig{
		Mode:                 signals.ModePaper,
		AllowLiveTrading:     false,
		RequireHumanApproval: true,
		MaxNotionalOrderUSD:  1000,
		KillSwitchArmed:      true,
	}
	if err := cfg.ValidateBoot(); err != nil {
		t.Fatalf("expected paper config to boot clean, got: %v", err)
	}
}

func TestLiveWithoutAllowLiveTradingRejected(t *testing.T) {
	cfg := AppConfig{
		Mode:                 signals.ModeLive,
		AllowLiveTrading:     false,
		RequireHumanApproval: true,
	}
	if err := cfg.ValidateBoot(); err == nil {
		t.Fatal("expected refuse-to-start when mode=live and allow_live_trading=false")
	}
}

func TestLiveWithoutHumanApprovalRejected(t *testing.T) {
	cfg := AppConfig{
		Mode:                 signals.ModeLive,
		AllowLiveTrading:     true,
		RequireHumanApproval: false,
	}
	if err := cfg.ValidateBoot(); err == nil {
		t.Fatal("expected refuse-to-start when mode=live and require_human_approval=false")
	}
}
