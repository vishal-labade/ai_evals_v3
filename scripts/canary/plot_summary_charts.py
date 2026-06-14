#!/usr/bin/env python3
"""
plot_summary_charts.py
=======================
Generates the two "hero" charts for publication/review from the full
canary (CSR/CIR) and CTBR results:

  1. csr_cir_vs_model_size.png
     Dual-axis line chart — CSR (verbatim leakage) and CIR (semantic
     influence) plotted against model size. Shows that scale reduces
     CSR but does not reduce (and can increase) CIR.

  2. ctbr_decay_all_conditions.png
     Faceted bleed-decay curves (one panel per model) showing bleed
     rate at post-switch turns 4-7, broken out by memory_condition x
     context_length. Surfaces the "anti-decay" pattern where bleed
     reappears at turn 7 after several clean turns.

  3. ctbr_decay_{model}.png
     Per-model single-panel version of (2).

Inputs (produced by the existing pipeline)
--------------------------------------------
  results/canary/metrics/canary_metrics_summary.csv
      columns: model, canary_type, task_category, n_runs, csr_flagged,
               CSR, n_paired, cir_flagged, CIR

  results/ctbr/metrics/ctbr_decay.csv
      columns: model, memory_condition, context_length, turn_number,
               n, bleed_count, bleed_rate

Usage
-----
    python plot_summary_charts.py
    python plot_summary_charts.py \
        --canary_summary results/canary/metrics/canary_metrics_summary.csv \
        --ctbr_decay     results/ctbr/metrics/ctbr_decay.csv \
        --outdir         artifacts/figures \
        --model_size_map configs/model_sizes.yaml
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CANARY_SUMMARY = "results/canary/metrics/canary_metrics_summary.csv"
DEFAULT_CTBR_DECAY     = "results/ctbr/metrics/ctbr_decay.csv"
DEFAULT_OUTDIR         = "artifacts/figures"

# Maps Ollama model tags -> approximate parameter count in billions.
# Override / extend via --model_size_map (a YAML file: {model_tag: size_b}).
DEFAULT_MODEL_SIZES: Dict[str, float] = {
    "qwen2.5:3b":                  3,
    "qwen2.5:14b":                 14,
    "qwen2.5:32b":                 32,
    "qwen2.5:72b":                 72,
    "gemma2:9b-instruct-q4_K_M":   9,
    "gemma2:9b":                   9,
    "llama3:8b-instruct-q4_0":     8,
    "llama3.3:70b":                70,
    "mistral-nemo:12b-instruct-2407-q4_K_M": 12,
    "mixtral:8x7b":                47,   # total params (8x7B MoE)
    "gpt-oss-safeguard:20b":       20,
    "phi3:mini":                   3.8,
}

# Short display labels for the x-axis
DEFAULT_MODEL_LABELS: Dict[str, str] = {
    "qwen2.5:3b":                  "3B",
    "qwen2.5:14b":                 "14B",
    "qwen2.5:32b":                 "32B",
    "qwen2.5:72b":                 "72B",
    "gemma2:9b-instruct-q4_K_M":   "9B",
    "gemma2:9b":                   "9B",
    "llama3:8b-instruct-q4_0":     "8B",
    "llama3.3:70b":                "70B",
    "mistral-nemo:12b-instruct-2407-q4_K_M": "12B",
    "mixtral:8x7b":                "8x7B",
    "gpt-oss-safeguard:20b":       "20B",
    "phi3:mini":                   "3.8B",
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _load_csv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
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


def _load_model_size_map(path: Optional[str]) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Returns (sizes, labels). Falls back to defaults; merges overrides from YAML."""
    sizes = dict(DEFAULT_MODEL_SIZES)
    labels = dict(DEFAULT_MODEL_LABELS)

    if path and HAS_YAML and Path(path).exists():
        with open(path, encoding="utf-8") as f:
            override = yaml.safe_load(f) or {}
        for model, info in override.items():
            if isinstance(info, dict):
                if "size_b" in info:
                    sizes[model] = float(info["size_b"])
                if "label" in info:
                    labels[model] = str(info["label"])
            else:
                # Allow shorthand: model: 14   (just the size in billions)
                sizes[model] = float(info)
                labels.setdefault(model, f"{info}B")

    return sizes, labels


# ---------------------------------------------------------------------------
# Chart 1: CSR / CIR vs model size
# ---------------------------------------------------------------------------

def aggregate_csr_cir_by_model(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Aggregates canary_metrics_summary.csv rows into overall CSR and CIR per model.

    CSR = sum(csr_flagged) / sum(n_runs)
    CIR = sum(cir_flagged) / sum(n_paired)   (only over rows where CIR is not empty)
    """
    agg: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "n_runs": 0, "csr_flagged": 0, "n_paired": 0, "cir_flagged": 0,
    })

    for row in rows:
        model = row.get("model", "")
        agg[model]["n_runs"]      += _i(row.get("n_runs", 0))
        agg[model]["csr_flagged"] += _i(row.get("csr_flagged", 0))

        cir_val = row.get("CIR", "")
        if cir_val not in ("", None):
            agg[model]["n_paired"]    += _i(row.get("n_paired", 0))
            agg[model]["cir_flagged"] += _i(row.get("cir_flagged", 0))

    result: Dict[str, Dict[str, float]] = {}
    for model, d in agg.items():
        csr = d["csr_flagged"] / d["n_runs"]   if d["n_runs"]   else float("nan")
        cir = d["cir_flagged"] / d["n_paired"] if d["n_paired"] else float("nan")
        result[model] = {"CSR": csr, "CIR": cir, "n_runs": d["n_runs"], "n_paired": d["n_paired"]}

    return result


def plot_csr_cir_vs_model_size(
    canary_summary_rows: List[Dict[str, Any]],
    outdir: str,
    model_sizes: Dict[str, float],
    model_labels: Dict[str, str],
    filename: str = "csr_cir_vs_model_size.png",
) -> Optional[str]:
    if not HAS_MPL:
        print("[plot_summary_charts] matplotlib not available — skipping CSR/CIR chart")
        return None

    per_model = aggregate_csr_cir_by_model(canary_summary_rows)

    # Keep only models we have a size mapping for, sorted by size
    plot_data = []
    for model, vals in per_model.items():
        if model not in model_sizes:
            print(f"[plot_summary_charts] WARNING: no size mapping for '{model}', skipping. "
                  f"Add it via --model_size_map.")
            continue
        plot_data.append((model_sizes[model], model_labels.get(model, model), vals["CSR"], vals["CIR"]))

    if not plot_data:
        print("[plot_summary_charts] no models with known sizes — skipping CSR/CIR chart")
        return None

    plot_data.sort(key=lambda t: t[0])
    sizes  = [d[0] for d in plot_data]
    labels = [d[1] for d in plot_data]
    csr    = [d[2] for d in plot_data]
    cir    = [d[3] for d in plot_data]

    fig, ax1 = plt.subplots(figsize=(9, 5.5))

    color_csr = "#DC2626"
    color_cir = "#2563EB"

    l1 = ax1.plot(sizes, csr, color=color_csr, marker="o", markersize=11,
                   linewidth=2.5, label="CSR (verbatim leakage)")
    ax1.set_xlabel("Model Size (parameters, billions)", fontsize=11)
    ax1.set_ylabel("Canary Surface Rate (CSR)", color=color_csr, fontsize=11)
    ax1.tick_params(axis="y", labelcolor=color_csr)

    csr_max = max(csr) if csr else 0.25
    ax1.set_ylim(-0.01, max(csr_max * 1.3, 0.05))

    for x, y in zip(sizes, csr):
        ax1.annotate(f"{y:.3f}", (x, y), textcoords="offset points",
                      xytext=(0, 12), ha="center", fontsize=10,
                      color=color_csr, fontweight="bold")

    ax2 = ax1.twinx()
    l2 = ax2.plot(sizes, cir, color=color_cir, marker="s", markersize=11,
                   linewidth=2.5, linestyle="--", label="CIR (semantic influence)")
    ax2.set_ylabel("Canary Influence Rate (CIR)", color=color_cir, fontsize=11)
    ax2.tick_params(axis="y", labelcolor=color_cir)

    cir_vals_valid = [v for v in cir if v == v]  # filter NaN
    if cir_vals_valid:
        cir_min, cir_max = min(cir_vals_valid), max(cir_vals_valid)
        pad = max((cir_max - cir_min) * 0.25, 0.02)
        ax2.set_ylim(max(cir_min - pad, 0), min(cir_max + pad, 1.02))

    for x, y in zip(sizes, cir):
        if y == y:  # not NaN
            ax2.annotate(f"{y:.3f}", (x, y), textcoords="offset points",
                          xytext=(0, -22), ha="center", fontsize=10,
                          color=color_cir, fontweight="bold")

    # Use model labels (e.g. "3B") as x tick labels at their actual size positions
    ax1.set_xticks(sizes)
    ax1.set_xticklabels(labels, fontsize=11)
    ax1.grid(True, alpha=0.3)

    ax1.set_title(
        "Privacy Leakage vs Model Size\n"
        "Scale reduces verbatim leakage (CSR↓) — semantic influence (CIR) does not necessarily follow",
        fontsize=12, fontweight="bold"
    )

    lines = l1 + l2
    labels_combined = [l.get_label() for l in lines]
    ax1.legend(lines, labels_combined, loc="center left", fontsize=10)

    plt.tight_layout()
    Path(outdir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(outdir) / filename)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot_summary_charts] saved: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Chart 2: CTBR bleed decay curves (faceted + per-model)
# ---------------------------------------------------------------------------

# Fixed style per (memory_condition, context_length) condition — kept
# consistent across all panels/files so legends are comparable.
COND_STYLE: Dict[Tuple[str, int], Dict[str, Any]] = {
    ("memory_off", 2048): {"color": "#DC2626", "linestyle": "--", "marker": "o", "label": "mem=OFF, ctx=2K"},
    ("memory_off", 8192): {"color": "#F59E0B", "linestyle": "--", "marker": "D", "label": "mem=OFF, ctx=8K"},
    ("memory_on",  2048): {"color": "#2563EB", "linestyle": "-",  "marker": "s", "label": "mem=ON, ctx=2K"},
    ("memory_on",  8192): {"color": "#16A34A", "linestyle": "-",  "marker": "^", "label": "mem=ON, ctx=8K"},
}


def _group_decay(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str, int], Dict[int, float]]:
    """(model, memory_condition, context_length) -> {turn_number: bleed_rate}"""
    groups: Dict[Tuple[str, str, int], Dict[int, float]] = defaultdict(dict)
    for row in rows:
        model = row.get("model", "")
        mem   = row.get("memory_condition", "")
        ctx   = _i(row.get("context_length", 2048))
        turn  = _i(row.get("turn_number", 4))
        rate  = _f(row.get("bleed_rate", 0.0))
        groups[(model, mem, ctx)][turn] = rate
    return groups


def _y_limit(groups: Dict[Tuple[str, str, int], Dict[int, float]]) -> float:
    all_rates = [v for td in groups.values() for v in td.values()]
    if not all_rates:
        return 0.30
    return max(max(all_rates) * 1.3, 0.05)


def plot_ctbr_decay_per_model(
    decay_rows: List[Dict[str, Any]],
    outdir: str,
    model_labels: Optional[Dict[str, str]] = None,
) -> List[str]:
    """One PNG per model: ctbr_decay_{slug}.png"""
    if not HAS_MPL:
        print("[plot_summary_charts] matplotlib not available — skipping CTBR decay charts")
        return []

    groups = _group_decay(decay_rows)
    if not groups:
        print("[plot_summary_charts] no CTBR decay data found")
        return []

    models = sorted(set(k[0] for k in groups))
    y_max = _y_limit(groups)
    out_paths = []

    for model in models:
        fig, ax = plt.subplots(figsize=(9, 5.5))
        any_line = False

        for (mem, ctx), style in COND_STYLE.items():
            turn_data = groups.get((model, mem, ctx), {})
            if not turn_data:
                continue
            turns = sorted(turn_data.keys())
            rates = [turn_data[t] for t in turns]
            ax.plot(turns, rates, linewidth=2.5, markersize=9, **style)
            any_line = True

        if not any_line:
            plt.close()
            continue

        ax.axhline(0, color="gray", linewidth=0.7, linestyle=":")
        ax.set_xlabel("Turn Number (post-switch turns: 4–7)", fontsize=11)
        ax.set_ylabel("Bleed Rate", fontsize=11)

        display_name = (model_labels or {}).get(model, model)
        ax.set_title(f"Privacy Bleed Decay — {model} ({display_name})", fontsize=12, fontweight="bold")

        all_turns = sorted({t for td in groups.values() for t in td})
        if all_turns:
            ax.set_xticks(all_turns)
            ax.set_xticklabels([f"Turn {t}" for t in all_turns])
        ax.set_ylim(-0.02, y_max)
        ax.legend(fontsize=10, loc="upper left")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        slug = model.replace(":", "_").replace(".", "_").replace("/", "_")
        Path(outdir).mkdir(parents=True, exist_ok=True)
        out_path = str(Path(outdir) / f"ctbr_decay_{slug}.png")
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"[plot_summary_charts] saved: {out_path}")
        out_paths.append(out_path)

    return out_paths


def plot_ctbr_decay_faceted(
    decay_rows: List[Dict[str, Any]],
    outdir: str,
    filename: str = "ctbr_decay_all_conditions.png",
    title: str = "Privacy Bleed Decay — All Models, All Conditions",
) -> Optional[str]:
    """Single PNG with one panel per model, side by side, shared y-axis."""
    if not HAS_MPL:
        print("[plot_summary_charts] matplotlib not available — skipping faceted CTBR chart")
        return None

    groups = _group_decay(decay_rows)
    if not groups:
        print("[plot_summary_charts] no CTBR decay data found")
        return None

    models = sorted(set(k[0] for k in groups))
    y_max = _y_limit(groups)

    n = len(models)
    fig, axes = plt.subplots(1, n, figsize=(6.5 * n, 5.5), sharey=True)
    if n == 1:
        axes = [axes]

    for ax, model in zip(axes, models):
        for (mem, ctx), style in COND_STYLE.items():
            turn_data = groups.get((model, mem, ctx), {})
            if not turn_data:
                continue
            turns = sorted(turn_data.keys())
            rates = [turn_data[t] for t in turns]
            ax.plot(turns, rates, linewidth=2.5, markersize=8, **style)

        ax.axhline(0, color="gray", linewidth=0.7, linestyle=":")
        ax.set_title(model, fontsize=12, fontweight="bold")
        ax.set_xlabel("Turn Number", fontsize=10)

        all_turns = sorted({t for td in groups.values() for t in td})
        if all_turns:
            ax.set_xticks(all_turns)
            ax.set_xticklabels([f"T{t}" for t in all_turns])
        ax.set_ylim(-0.02, y_max)
        ax.legend(fontsize=9, loc="upper left")
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("Bleed Rate", fontsize=11)
    fig.suptitle(title, fontsize=13, fontweight="bold")
    plt.tight_layout()

    Path(outdir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(outdir) / filename)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[plot_summary_charts] saved: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Generate CSR/CIR-vs-size and CTBR decay summary charts")
    ap.add_argument("--canary_summary", default=DEFAULT_CANARY_SUMMARY,
                    help="Path to canary_metrics_summary.csv")
    ap.add_argument("--ctbr_decay", default=DEFAULT_CTBR_DECAY,
                    help="Path to ctbr_decay.csv")
    ap.add_argument("--outdir", default=DEFAULT_OUTDIR,
                    help="Output directory for PNGs")
    ap.add_argument("--model_size_map", default=None,
                    help="Optional YAML file overriding/extending model -> size_b mapping")
    ap.add_argument("--skip_csr_cir", action="store_true",
                    help="Skip the CSR/CIR-vs-size chart")
    ap.add_argument("--skip_ctbr_decay", action="store_true",
                    help="Skip the CTBR decay charts")
    args = ap.parse_args()

    model_sizes, model_labels = _load_model_size_map(args.model_size_map)

    if not args.skip_csr_cir:
        if Path(args.canary_summary).exists():
            canary_rows = _load_csv(args.canary_summary)
            plot_csr_cir_vs_model_size(canary_rows, args.outdir, model_sizes, model_labels)
        else:
            print(f"[plot_summary_charts] canary summary not found: {args.canary_summary} — skipping")

    if not args.skip_ctbr_decay:
        if Path(args.ctbr_decay).exists():
            decay_rows = _load_csv(args.ctbr_decay)
            plot_ctbr_decay_per_model(decay_rows, args.outdir, model_labels)
            plot_ctbr_decay_faceted(decay_rows, args.outdir)
        else:
            print(f"[plot_summary_charts] CTBR decay CSV not found: {args.ctbr_decay} — skipping")

    print("[plot_summary_charts] done.")


if __name__ == "__main__":
    main()