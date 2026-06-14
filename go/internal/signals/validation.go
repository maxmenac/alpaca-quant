package signals

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// SupportedSchemaMajor is the only signal schema major version Go will accept. An unknown
// major is rejected fail-closed (SIGNAL_CONTRACT.md §5): better a rejected signal than a
// misinterpreted one that touches capital.
const SupportedSchemaMajor = 1

// ValidationInput carries the process-side facts validation needs: the wall clock, the
// process mode, whether live trading is allowed, and the portfolio exposure limits
// (from risk.yaml; zero means "not enforced here").
type ValidationInput struct {
	Now              time.Time
	ProcessMode      Mode
	AllowLiveTrading bool
	MaxGrossExposure float64
	MaxNetExposure   float64
}

// Validate applies the fail-closed rejection rules of SIGNAL_CONTRACT.md §2. It returns nil
// only if the signal is safe to act on; otherwise it returns an error describing the first
// violated rule (the caller logs a structured rejection line). Absence of a valid signal
// means no trade — never a default execution.
func Validate(sig *Signal, in ValidationInput) error {
	if sig == nil {
		return fmt.Errorf("signal is nil")
	}

	// 1. Required fields (SIGNAL_CONTRACT.md §2).
	if sig.SchemaVersion == "" {
		return fmt.Errorf("missing required field: schema_version")
	}
	if sig.SignalID == "" {
		return fmt.Errorf("missing required field: signal_id")
	}
	if sig.ValidUntil.IsZero() {
		return fmt.Errorf("missing required field: valid_until")
	}
	if sig.Mode == "" {
		return fmt.Errorf("missing required field: mode")
	}
	if sig.RebalanceType == "" {
		return fmt.Errorf("missing required field: rebalance_type")
	}
	if sig.BacktestRunID == "" {
		return fmt.Errorf("missing required field: backtest_run_id")
	}
	if sig.DataDeclarationID == "" {
		return fmt.Errorf("missing required field: data_declaration_id")
	}

	// 2. Schema major must be known.
	major, err := schemaMajor(sig.SchemaVersion)
	if err != nil {
		return fmt.Errorf("invalid schema_version %q: %w", sig.SchemaVersion, err)
	}
	if major != SupportedSchemaMajor {
		return fmt.Errorf("unsupported schema major %d (want %d)", major, SupportedSchemaMajor)
	}

	// 3. Reject expired signals (anti stale-signal).
	if in.Now.After(sig.ValidUntil) {
		return fmt.Errorf("signal expired: now %s > valid_until %s",
			in.Now.UTC().Format(time.RFC3339), sig.ValidUntil.UTC().Format(time.RFC3339))
	}

	// 4. Mode must match the process mode.
	if sig.Mode != in.ProcessMode {
		return fmt.Errorf("mode mismatch: signal %q, process %q", sig.Mode, in.ProcessMode)
	}

	// 5. Live requires the explicit allow flag (cross-checked with SAFETY_POLICY.md).
	if sig.Mode == ModeLive && !in.AllowLiveTrading {
		return fmt.Errorf("live signal rejected: allow_live_trading is false")
	}

	// 6. Portfolio exposure bounds (reject the whole signal if exceeded).
	if in.MaxGrossExposure > 0 && sig.Metadata.TargetGrossExposure > in.MaxGrossExposure {
		return fmt.Errorf("target_gross_exposure %.4f exceeds limit %.4f",
			sig.Metadata.TargetGrossExposure, in.MaxGrossExposure)
	}
	if in.MaxNetExposure > 0 && abs(sig.Metadata.TargetNetExposure) > in.MaxNetExposure {
		return fmt.Errorf("target_net_exposure %.4f exceeds limit %.4f",
			sig.Metadata.TargetNetExposure, in.MaxNetExposure)
	}

	// 7. Block exposure-increasing actions without approval. reduce_only / close_only /
	// rebalance_to_zero only reduce risk and are always allowed (the system's key asymmetry).
	if sig.RebalanceType.IsExposureIncreasing() &&
		sig.ApprovalRequired && sig.ApprovalStatus != ApprovalApproved {
		return fmt.Errorf("exposure increase blocked: approval_required and approval_status=%q",
			sig.ApprovalStatus)
	}

	return nil
}

// schemaMajor parses the major component of a semver string ("1.1.0" -> 1).
func schemaMajor(v string) (int, error) {
	parts := strings.Split(v, ".")
	if len(parts) == 0 || parts[0] == "" {
		return 0, fmt.Errorf("not semver")
	}
	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return 0, fmt.Errorf("major not an integer: %w", err)
	}
	return major, nil
}

func abs(f float64) float64 {
	if f < 0 {
		return -f
	}
	return f
}
