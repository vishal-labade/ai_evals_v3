#!/usr/bin/env python3
"""
plot_ctbr.py
============
Generates bleed decay curves and CTBR/PRR summary charts from CTBR metric CSVs.

Produces:
  artifacts/figures/ctbr_decay_curves.png      — bleed rate by turn, all conditions
  artifacts/figures/ctbr_decay_{model}.png     — per-model decay curves
  artifacts/figures/ctbr_summary_heatmap.png   — CTBR heatmap: memory × context_length

Usage:
    python plot_ctbr.py
    python plot_ctbr.py --decay results/ctbr/metrics/ctbr_decay.csv
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.lines as mlines
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_csv(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def _f(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def _i(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Colour / style helpers
# ---------------------------------------------------------------------------

MEM_STYLES = {
    "memory_off": {"linestyle": "--", "marker": "o"},
    "memory_on":  {"linestyle": "-",  "marker": "s"},
}
CTX_COLORS = {
    2048: "#2563EB",   # blue
    8192: "#DC2626",   # red
}
FALLBACK_COLORS = ["#7C3AED", "#059669", "#D97706", "#0891B2"]


def _condition_label(mem: str, ctx: int) -> str:
    mem_lbl = "mem=OFF" if mem == "memory_off" else "mem=ON"
    ctx_lbl = f"ctx={ctx//1024}K"
    return f"{mem_lbl}, {ctx_lbl}"


# ---------------------------------------------------------------------------
# Decay curve plot
# ---------------------------------------------------------------------------

def plot_decay_curves(
    decay_rows: List[Dict[str, Any]],
    outdir: str,
    model_filter: Optional[str] = None,
) -> None:
    if not HAS_MPL:
        _ascii_decay(decay_rows, outdir, model_filter)
        return

    # Group: (model, memory_condition, context_length) → {turn_number: bleed_rate}
    groups: Dict[Tuple[str, str, int], Dict[int, float]] = defaultdict(dict)
    for row in decay_rows:
        model = row.get("model", "")
        if model_filter and model != model_filter:
            continue
        mem   = row.get("memory_condition", "")
        ctx   = _i(row.get("context_length", 2048))
        turn  = _i(row.get("turn_number", 4))
        rate  = _f(row.get("bleed_rate", 0.0))
        groups[(model, mem, ctx)][turn] = rate

    if not groups:
        print(f"[plot_ctbr] no decay data for model_filter={model_filter}")
        return

    models = sorted(set(k[0] for k in groups))
    suffix = model_filter.replace(" ", "_").replace("/", "_").replace(":", "_") if model_filter else "all"

    for model in models:
        fig, ax = plt.subplots(figsize=(9, 5))
        has_lines = False

        for cidx, ((m, mem, ctx), turn_data) in enumerate(sorted(groups.items())):
            if m != model:
                continue
            if len(turn_data) < 2:
                continue

            turns_sorted = sorted(turn_data.keys())
            rates = [turn_data[t] for t in turns_sorted]

            style  = MEM_STYLES.get(mem, {"linestyle": "-", "marker": "o"})
            color  = CTX_COLORS.get(ctx, FALLBACK_COLORS[cidx % len(FALLBACK_COLORS)])
            label  = _condition_label(mem, ctx)

            ax.plot(turns_sorted, rates, color=color, label=label,
                    linewidth=2, markersize=7, **style)
            has_lines = True

        if not has_lines:
            plt.close()
            continue

        # Reference line at 0
        ax.axhline(0, color="gray", linewidth=0.7, linestyle=":")
        ax.axvline(3.5, color="orange", linewidth=1.2, linestyle="--", alpha=0.7,
                   label="← context switch →")

        ax.set_xlabel("Turn Number (post-switch turns: 4–7)", fontsize=11)
        ax.set_ylabel("Bleed Rate", fontsize=11)
        ax.set_title(f"Privacy Bleed Decay — {model}", fontsize=12, fontweight="bold")
        ax.set_xticks(range(4, 8))
        ax.set_xticklabels([f"Turn {t}" for t in range(4, 8)])
        ax.set_ylim(-0.05, 1.05)
        ax.legend(fontsize=9, loc="upper right")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        slug = model.replace(" ", "_").replace("/", "_").replace(":", "_")
        out_path = str(Path(outdir) / f"ctbr_decay_{slug}.png")
        Path(outdir).mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"[plot_ctbr] saved: {out_path}")

    # Aggregate across all models
    agg: Dict[Tuple[str, int], Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    for (model, mem, ctx), turn_data in groups.items():
        for turn, rate in turn_data.items():
            agg[(mem, ctx)][turn].append(rate)

    fig, ax = plt.subplots(figsize=(9, 5))
    for cidx, ((mem, ctx), turn_data) in enumerate(sorted(agg.items())):
        turns_sorted = sorted(turn_data.keys())
        rates = [sum(turn_data[t]) / len(turn_data[t]) for t in turns_sorted]
        style = MEM_STYLES.get(mem, {"linestyle": "-", "marker": "o"})
        color = CTX_COLORS.get(ctx, FALLBACK_COLORS[cidx % len(FALLBACK_COLORS)])
        ax.plot(turns_sorted, rates, color=color, label=_condition_label(mem, ctx),
                linewidth=2.5, markersize=8, **style)

    ax.axhline(0, color="gray", linewidth=0.7, linestyle=":")
    ax.axvline(3.5, color="orange", linewidth=1.2, linestyle="--", alpha=0.7,
               label="← context switch →")
    ax.set_xlabel("Turn Number (post-switch: 4–7)", fontsize=11)
    ax.set_ylabel("Bleed Rate (averaged across models)", fontsize=11)
    ax.set_title("Privacy Bleed Decay — All Models (averaged)", fontsize=12, fontweight="bold")
    ax.set_xticks(range(4, 8))
    ax.set_xticklabels([f"Turn {t}" for t in range(4, 8)])
    ax.set_ylim(-0.05, 1.05)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_all = str(Path(outdir) / "ctbr_decay_all.png")
    plt.savefig(out_all, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot_ctbr] saved: {out_all}")


# ---------------------------------------------------------------------------
# CTBR summary heatmap — memory × context per model
# ---------------------------------------------------------------------------

def plot_summary_heatmap(
    summary_rows: List[Dict[str, Any]],
    outdir: str,
) -> None:
    if not HAS_MPL or not HAS_NP:
        print("[plot_ctbr] matplotlib/numpy not available — skipping heatmap")
        return

    models = sorted(set(r["model"] for r in summary_rows if r.get("model")))

    for model in models:
        rows = [r for r in summary_rows if r.get("model") == model]

        # Axes: memory_condition (rows) × context_length (cols)
        mem_vals = ["memory_off", "memory_on"]
        ctx_vals = sorted(set(_i(r["context_length"]) for r in rows))

        if not ctx_vals:
            continue

        ctbr_matrix = np.full((len(mem_vals), len(ctx_vals)), float("nan"))
        prr_matrix  = np.full((len(mem_vals), len(ctx_vals)), float("nan"))

        for row in rows:
            mem = row.get("memory_condition", "")
            ctx = _i(row.get("context_length", 0))
            if mem in mem_vals and ctx in ctx_vals:
                mi = mem_vals.index(mem)
                ci = ctx_vals.index(ctx)
                ctbr_val = _f(row.get("CTBR", 0.0))
                ctbr_matrix[mi, ci] = max(
                    ctbr_val,
                    ctbr_matrix[mi, ci] if not math.isnan(ctbr_matrix[mi, ci]) else 0.0
                )
                prr_raw = row.get("PRR", "")
                if prr_raw != "" and prr_raw is not None:
                    try:
                        prr_matrix[mi, ci] = float(prr_raw)
                    except ValueError:
                        pass

        fig, axes = plt.subplots(1, 2, figsize=(11, 3.5))
        mem_labels = ["mem=OFF", "mem=ON"]
        ctx_labels = [f"ctx={c//1024}K" for c in ctx_vals]

        for ax, matrix, title, cmap in [
            (axes[0], ctbr_matrix, "CTBR",  "RdYlGn_r"),
            (axes[1], prr_matrix,  "PRR",   "RdYlGn"),
        ]:
            im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=0, vmax=1)
            ax.set_xticks(range(len(ctx_labels)))
            ax.set_yticks(range(len(mem_labels)))
            ax.set_xticklabels(ctx_labels, fontsize=10)
            ax.set_yticklabels(mem_labels, fontsize=10)
            ax.set_title(f"{title} — {model}", fontsize=10, fontweight="bold")
            ax.set_xlabel("Context Length", fontsize=9)
            ax.set_ylabel("Memory Condition", fontsize=9)
            plt.colorbar(im, ax=ax)

            for i in range(len(mem_labels)):
                for j in range(len(ctx_labels)):
                    val = matrix[i, j]
                    txt = f"{val:.2f}" if not math.isnan(val) else "n/a"
                    clr = "white" if not math.isnan(val) and val > 0.55 else "black"
                    ax.text(j, i, txt, ha="center", va="center",
                            fontsize=11, fontweight="bold", color=clr)

        plt.tight_layout()
        slug = model.replace(" ", "_").replace("/", "_").replace(":", "_")
        out_path = str(Path(outdir) / f"ctbr_summary_heatmap_{slug}.png")
        Path(outdir).mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"[plot_ctbr] saved: {out_path}")


# ---------------------------------------------------------------------------
# ASCII fallback
# ---------------------------------------------------------------------------

def _ascii_decay(rows, outdir, model_filter):
    groups: Dict[str, Dict[int, float]] = defaultdict(dict)
    for row in rows:
        model = row.get("model", "")
        if model_filter and model != model_filter:
            continue
        key = f"{model}|{row.get('memory_condition')}|{row.get('context_length')}"
        groups[key][_i(row.get("turn_number", 4))] = _f(row.get("bleed_rate", 0.0))
    txt = ["CTBR Bleed Decay", ""]
    for cond, td in sorted(groups.items()):
        txt.append(f"Condition: {cond}")
        for t in sorted(td):
            bar = "█" * int(td[t] * 20)
            txt.append(f"  Turn {t}: {td[t]:.3f}  {bar}")
        txt.append("")
    p = Path(outdir) / "ctbr_decay.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(txt))
    print(f"[plot_ctbr] ASCII fallback: {p}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Plot CTBR decay curves and heatmaps")
    ap.add_argument("--decay",   default="results/ctbr/metrics/ctbr_decay.csv")
    ap.add_argument("--summary", default="results/ctbr/metrics/ctbr_summary.csv")
    ap.add_argument("--outdir",  default="artifacts/figures")
    args = ap.parse_args()

    if not Path(args.decay).exists():
        print(f"[plot_ctbr] decay CSV not found: {args.decay}")
        return

    decay_rows = _load_csv(args.decay)
    plot_decay_curves(decay_rows, args.outdir)

    if Path(args.summary).exists():
        summary_rows = _load_csv(args.summary)
        plot_summary_heatmap(summary_rows, args.outdir)

    print("[plot_ctbr] done.")


if __name__ == "__main__":
    main()