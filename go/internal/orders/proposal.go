// Package orders builds paper order proposals from validated signals (SIGNAL_CONTRACT.md §4).
// MVP: a proposal is a recommendation only — nothing is sent to a broker. Idempotency is
// baked in from the start via client_order_id = signal_id + symbol.
package orders

import "fmt"

// Side is the order direction.
type Side string

const (
	SideBuy  Side = "buy"
	SideSell Side = "sell"
)

// Proposal is a recommended (not executed) marketable limit order. It is produced only after
// risk-gate checks and, for exposure-increasing actions, human approval.
type Proposal struct {
	ClientOrderID string  `json:"client_order_id"`
	Symbol        string  `json:"symbol"`
	Side          Side    `json:"side"`
	NotionalUSD   float64 `json:"notional_usd"`
}

// ClientOrderID returns the idempotent client order id (signal_id + symbol) so retries never
// double an order (SIGNAL_CONTRACT.md §4).
func ClientOrderID(signalID, symbol string) string {
	return fmt.Sprintf("%s:%s", signalID, symbol)
}
