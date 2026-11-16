"""Compare stage-2 attack-minus-control effects between protected and original series."""
import csv
import sys
from pathlib import Path

original, protected = map(Path, sys.argv[1:3])


def cells(root):
    with (root / "plots/etapa-2/cell-effects.csv").open(newline="") as handle:
        return {(int(row["m"]), int(row["ttlb_ms"])): row for row in csv.DictReader(handle)}


before, after = cells(original), cells(protected)
if before.keys() != after.keys() or len(after) != 6:
    raise SystemExit("Expected the same six stage-2 cells in both modes")
metrics = ("d_steer", "delta_c_usd_per_gb", "delta_qoe")
rows = []
for m, ttlb in sorted(after):
    row = {"m": m, "ttlb_ms": ttlb}
    for metric in metrics:
        old, new = before[m, ttlb][metric], after[m, ttlb][metric]
        row[f"original_{metric}"] = old
        row[f"protected_{metric}"] = new
        row[f"difference_{metric}"] = float(new) - float(old) if old and new else ""
    rows.append(row)
target = protected / "plots/etapa-2/defense-comparison.csv"
with target.open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(target)
