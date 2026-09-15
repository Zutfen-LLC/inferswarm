# Hardware references

This directory holds living references for current InferSwarm test hardware. Update them when device placement or bus topology changes; do not rewrite historical benchmark or qualification records to match later hardware state.

## References

- [PCIe slot ledger](pcie-slot-ledger.md) — per-host slot capabilities, GPU occupants, negotiated widths/speeds, available slots, fleet aggregates, and topology notes.
- [Current-inventory captures](current-inventory/) — dated raw read-only scan receipts backing each living-ledger refresh. These are living-state receipts, not retained experiment evidence; a later refresh supersedes them without correction procedures.

## Maintenance

- Treat slot, PCIe generation, negotiated width, riser/bridge path, and device BDF as experimental state.
- Update the ledger after card moves, riser changes, firmware lane-allocation changes, or host hardware changes.
- Record intentional topology changes in the ledger change log.
- Do not use idle GPU link speed as a throughput claim; re-measure under load when speed matters.
- New experiments should identify the relevant hardware-topology revision or capture their own physical evidence.
