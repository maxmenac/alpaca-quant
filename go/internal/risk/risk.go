// Package risk holds the real-time risk-gate checks (ARCHITECTURE.md §3.6). The risk gate is
// a deliberately separate Go process that can stop everything. The MVP exposes the limit type
// and pre-trade exposure checks; order execution does not exist yet.
package risk

import "github.com/maxmenac/alpaca-quant/internal/config"

// Limits is the subset of config.RiskLimits the gate enforces on portfolio exposure.
type Limits struct {
	MaxGrossExposure float64
	MaxNetExposure   float64
}

// LimitsFrom derives gate limits from the loaded risk config.
func LimitsFrom(c config.RiskLimits) Limits {
	return Limits{
		MaxGrossExposure: c.MaxGrossExposure,
		MaxNetExposure:   c.MaxNetExposure,
	}
}

// ExposureWithinLimits reports whether the given gross/net exposure respects the limits.
// A non-positive limit means "not enforced".
func (l Limits) ExposureWithinLimits(gross, net float64) bool {
	if l.MaxGrossExposure > 0 && gross > l.MaxGrossExposure {
		return false
	}
	if l.MaxNetExposure > 0 && abs(net) > l.MaxNetExposure {
		return false
	}
	return true
}

func abs(f float64) float64 {
	if f < 0 {
		return -f
	}
	return f
}
