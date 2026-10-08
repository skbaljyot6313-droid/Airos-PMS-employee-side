"""Canonical resource-state domain — the single source of truth for what
physical resources ARE, which states are legal, and which transitions may
occur. Services request transitions through ResourceStateService; nothing
else writes resource status."""
