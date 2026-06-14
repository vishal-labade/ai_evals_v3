#!/usr/bin/env python3
"""
plot_canary_heatmap.py
======================
Generates CSR and CIR heatmaps from canary_metrics_summary.csv.

Produces:
  artifacts/figures/canary_csr_heatmap_{model}.png  — per model
  artifacts/figures/canary_cir_heatmap_{model}.png  — per model
  artifacts/figures/canary_csr_heatmap_all.png       — aggregate across models
  artifacts/figures/canary_cir_heatmap_all.png       — aggregate across models

Usage:
    python plot_canary_heatmap.py
    python plot_canary_heatmap.py --summary results/canary/metrics/canary_metrics_summary.csv
    python plot_canary_heatmap.py --metric CSR
    python plot_canary_heatmap.py --metric CIR
    python plot_canary_heatmap.py --metric both   (default)
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Graceful matplotlib / seaborn import
# ---------------------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False

CANARY_ORDER = ["health", "financial", "relationship", "third_party_pii"]
TASK_ORDER = ["scheduling", "email_summarization", "document_drafting",
              "information_lookup", "action_planning"]

CANARY_LABELS = {
    "health": "Health",
    "financial": "Financial",
    "relationship": "Relationship",
    "third_party_pii": "3rd-Party PII",
}
TASK_LABELS = {
    "scheduling": "Scheduling",
    "email_summarization": "Email Summary",
    "document_drafting": "Doc Drafting",
    "information_lookup": "Info Lookup",
    "action_planning": "Action Planning",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_summary(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def pivot_matrix(
    rows: List[Dict[str, Any]],
    metric: str,
    model_filter: Optional[str] = None,
) -> Tuple[List[List[float]], List[str], List[str]]:
    """
    Returns (matrix[canary][task], canary_labels, task_labels).
    matrix[i][j] = metric value for canary_order[i], task_order[j].
    NaN where data is missing.
    """
    # Aggregate multiple model rows if no filter
    sums: Dict[Tuple[str, str], List[float]] = defaultdict(list)

    for row in rows:
        if model_filter and row.get("model") != model_filter:
            continue
        ct = row.get("canary_type", "")
        tt = row.get("task_category", "")
        val = row.get(metric, "")
        if val == "" or val is None:
            continue
        try:
            sums[(ct, tt)].append(float(val))
        except ValueError:
            pass

    nan = float("nan")
    matrix = []
    for ct in CANARY_ORDER:
        row_vals = []
        for tt in TASK_ORDER:
            vals = sums.get((ct, tt), [])
            row_vals.append(sum(vals) / len(vals) if vals else nan)
        matrix.append(row_vals)

    canary_labels = [CANARY_LABELS.get(c, c) for c in CANARY_ORDER]
    task_labels = [TASK_LABELS.get(t, t) for t in TASK_ORDER]
    return matrix, canary_labels, task_labels


# ---------------------------------------------------------------------------
# Matplotlib heatmap
# ---------------------------------------------------------------------------

def _draw_heatmap_mpl(
    matrix: List[List[float]],
    row_labels: List[str],
    col_labels: List[str],
    title: str,
    out_path: str,
    cmap: str = "RdYlGn_r",
    vmin: float = 0.0,
    vmax: float = 1.0,
    fmt: str = ".2f",
) -> None:
    if not HAS_MPL or not HAS_NP:
        print(f"[heatmap] matplotlib/numpy not available — skipping {out_path}")
        _draw_heatmap_text(matrix, row_labels, col_labels, title, out_path)
        return

    data = np.array(matrix, dtype=float)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    im = ax.imshow(data, cmap=cmap, aspect="auto", vmin=vmin, vmax=vmax)

    ax.set_xticks(range(len(col_labels)))
    ax.set_yticks(range(len(row_labels)))
    ax.set_xticklabels(col_labels, rotation=30, ha="right", fontsize=10)
    ax.set_yticklabels(row_labels, fontsize=10)

    # Annotate cells
    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            val = data[i, j]
            if np.isnan(val):
                text = "n/a"
                color = "gray"
            else:
                text = format(val, fmt)
                # Dark text on light cells, light on dark
                norm_val = (val - vmin) / (vmax - vmin + 1e-9)
                color = "white" if norm_val > 0.55 else "black"
            ax.text(j, i, text, ha="center", va="center", fontsize=10, color=color, fontweight="bold")

    plt.colorbar(im, ax=ax, label=title.split("—")[0].strip())
    ax.set_title(title, fontsize=12, fontweight="bold", pad=12)
    ax.set_xlabel("Task Category", fontsize=10)
    ax.set_ylabel("Canary Type", fontsize=10)
    plt.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[heatmap] saved: {out_path}")


def _draw_heatmap_text(
    matrix: List[List[float]],
    row_labels: List[str],
    col_labels: List[str],
    title: str,
    out_path: str,
) -> None:
    """ASCII fallback when matplotlib isn't available."""
    txt_path = out_path.replace(".png", ".txt")
    import math
    lines = [title, ""]
    header = f"{'':20}" + "".join(f"{c:>18}" for c in col_labels)
    lines.append(header)
    lines.append("-" * len(header))
    for i, rl in enumerate(row_labels):
        row_str = f"{rl:20}"
        for j in range(len(col_labels)):
            val = matrix[i][j]
            cell = "  n/a" if math.isnan(val) else f"{val:>8.3f}"
            row_str += f"{cell:>18}"
        lines.append(row_str)

    Path(txt_path).parent.mkdir(parents=True, exist_ok=True)
    Path(txt_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"[heatmap] ASCII fallback written: {txt_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Plot canary CSR/CIR heatmaps")
    ap.add_argument("--summary",
                    default="results/canary/metrics/canary_metrics_summary.csv")
    ap.add_argument("--outdir", default="artifacts/figures")
    ap.add_argument("--metric", default="both",
                    choices=["CSR", "CIR", "both"],
                    help="Which metric to plot (default: both)")
    args = ap.parse_args()

    if not Path(args.summary).exists():
        print(f"[heatmap] Summary CSV not found: {args.summary}")
        print("[heatmap] Run score_canary.py first.")
        return

    rows = load_summary(args.summary)
    models = sorted(set(r["model"] for r in rows if r.get("model")))
    metrics = ["CSR", "CIR"] if args.metric == "both" else [args.metric]

    for metric in metrics:
        cmap = "RdYlGn_r" if metric == "CSR" else "RdYlGn_r"
        fmt = ".3f"

        # Per-model heatmaps
        for model in models:
            matrix, clabels, tlabels = pivot_matrix(rows, metric, model_filter=model)
            slug = model.replace(" ", "_").replace("/", "_")
            out_path = str(Path(args.outdir) / f"canary_{metric.lower()}_heatmap_{slug}.png")
            _draw_heatmap_mpl(
                matrix, clabels, tlabels,
                title=f"{metric} Heatmap — {model}",
                out_path=out_path, cmap=cmap, fmt=fmt,
            )

        # Aggregate across all models
        matrix_all, clabels, tlabels = pivot_matrix(rows, metric, model_filter=None)
        out_all = str(Path(args.outdir) / f"canary_{metric.lower()}_heatmap_all.png")
        _draw_heatmap_mpl(
            matrix_all, clabels, tlabels,
            title=f"{metric} Heatmap — All Models (averaged)",
            out_path=out_all, cmap=cmap, fmt=fmt,
        )

    print("[heatmap] done.")


if __name__ == "__main__":
    main()