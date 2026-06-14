// Package portfolio tracks live positions and PnL (ARCHITECTURE.md §3.6). MVP stub: types
// only, no broker connectivity.
package portfolio

// Position is a single live position.
type Position struct {
	Symbol   string  `json:"symbol"`
	Qty      float64 `json:"qty"`
	AvgPrice float64 `json:"avg_price"`
}

// Portfolio is the current set of positions keyed by symbol.
type Portfolio struct {
	Positions map[string]Position `json:"positions"`
}

// New returns an empty portfolio.
func New() *Portfolio {
	return &Portfolio{Positions: make(map[string]Position)}
}

// Weight returns the current weight of a symbol given total equity, or 0 if absent or
// equity is non-positive. (Mark price wiring arrives with the broker client in a later sprint.)
func (p *Portfolio) Weight(symbol string, equity float64) float64 {
	pos, ok := p.Positions[symbol]
	if !ok || equity <= 0 {
		return 0
	}
	return (pos.Qty * pos.AvgPrice) / equity
}
