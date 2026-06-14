package signals

import (
	"testing"
	"time"
)

// validSignal returns a well-formed paper signal that should pass validation.
func validSignal() *Signal {
	return &Signal{
		SchemaVersion:     "1.1.0",
		SignalID:          "11111111-1111-1111-1111-111111111111",
		CreatedAt:         time.Now().Add(-time.Minute),
		AsOf:              time.Now().Add(-time.Minute),
		ValidUntil:        time.Now().Add(24 * time.Hour),
		Mode:              ModePaper,
		RebalanceType:     RebalanceTargetWeight,
		GeneratedBy:       "python-research-pipeline",
		ApprovalRequired:  true,
		ApprovalStatus:    ApprovalApproved,
		BacktestRunID:     "bt-2026-06-14-001",
		DataDeclarationID: "dq-tier1-us-largecap-2026-06-14",
		Horizon:           "1d",
	}
}

func paperInput() ValidationInput {
	return ValidationInput{Now: time.Now(), ProcessMode: ModePaper, AllowLiveTrading: false}
}

func TestValidPaperSignalAccepted(t *testing.T) {
	if err := Validate(validSignal(), paperInput()); err != nil {
		t.Fatalf("expected valid paper signal to be accepted, got: %v", err)
	}
}

func TestExpiredSignalRejected(t *testing.T) {
	sig := validSignal()
	sig.ValidUntil = time.Now().Add(-time.Hour)
	if err := Validate(sig, paperInput()); err == nil {
		t.Fatal("expected expired signal to be rejected")
	}
}

func TestLiveSignalRejectedWhenLiveNotAllowed(t *testing.T) {
	sig := validSignal()
	sig.Mode = ModeLive
	in := ValidationInput{Now: time.Now(), ProcessMode: ModeLive, AllowLiveTrading: false}
	if err := Validate(sig, in); err == nil {
		t.Fatal("expected live signal to be rejected when allow_live_trading=false")
	}
}

func TestApprovalRequiredPendingBlocksExposureIncrease(t *testing.T) {
	sig := validSignal()
	sig.RebalanceType = RebalanceTargetWeight
	sig.ApprovalRequired = true
	sig.ApprovalStatus = ApprovalPending
	if err := Validate(sig, paperInput()); err == nil {
		t.Fatal("expected pending approval to block exposure-increasing signal")
	}
}

func TestReduceOnlyAllowedDespitePendingApproval(t *testing.T) {
	sig := validSignal()
	sig.RebalanceType = RebalanceReduceOnly
	sig.ApprovalRequired = true
	sig.ApprovalStatus = ApprovalPending
	if err := Validate(sig, paperInput()); err != nil {
		t.Fatalf("expected reduce_only to be allowed despite pending approval, got: %v", err)
	}
}

func TestUnknownSchemaMajorRejected(t *testing.T) {
	sig := validSignal()
	sig.SchemaVersion = "2.0.0"
	if err := Validate(sig, paperInput()); err == nil {
		t.Fatal("expected unknown schema major to be rejected")
	}
}

func TestMissingRequiredFieldRejected(t *testing.T) {
	sig := validSignal()
	sig.DataDeclarationID = ""
	if err := Validate(sig, paperInput()); err == nil {
		t.Fatal("expected missing data_declaration_id to be rejected")
	}
}
