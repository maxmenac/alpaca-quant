"""Data layer: ingestion, cleaning, point-in-time, universe construction.

The foundation (ARCHITECTURE.md §3.1). Two invariants: point-in-time access (no
lookahead) and no survivorship bias. Nothing in features/ reads raw data directly.
"""
