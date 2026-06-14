#!/usr/bin/env bash
# =============================================================================
# run_canary_eval.sh
# Full canary injection evaluation pipeline.
#
# Usage:
#   ./run_canary_eval.sh
#   ./run_canary_eval.sh --profiles qwen_3b_t0,qwen_14b_t0
#   ./run_canary_eval.sh --limit 10       # smoke test: 10 scenarios per profile
#   ./run_canary_eval.sh --skip_generate  # skip corpus/suite generation
#   ./run_canary_eval.sh --skip_run       # only re-score existing run files
#
# Output layout:
#   data/canary_corpus.jsonl
#   data/canary_suite.jsonl
#   results/canary/runs/*.jsonl
#   results/canary/metrics/canary_metrics_turn.csv
#   results/canary/metrics/canary_metrics_summary.csv
#   artifacts/figures/canary_csr_heatmap_*.png
#   artifacts/figures/canary_cir_heatmap_*.png
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- Defaults ----------------------------------------------------------------
CONFIG="configs/run_config.yaml"
PROFILES=""
LIMIT=""
SKIP_GENERATE=false
SKIP_RUN=false
METRIC="both"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)          CONFIG="$2"; shift 2 ;;
    --profiles)        PROFILES="$2"; shift 2 ;;
    --limit)           LIMIT="$2"; shift 2 ;;
    --skip_generate)   SKIP_GENERATE=true; shift ;;
    --skip_run)        SKIP_RUN=true; shift ;;
    --metric)          METRIC="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p data results/canary/runs results/canary/metrics artifacts/figures artifacts/metrics

# CANARY_DIR="privacy_evals/canary_injection"
CANARY_DIR="scripts/canary"

echo "============================================================"
echo " Canary Injection Evaluation Pipeline"
echo "============================================================"
echo " config:   $CONFIG"
echo " profiles: ${PROFILES:-<ALL>}"
echo " limit:    ${LIMIT:-<none>}"
echo "------------------------------------------------------------"

# ── Step 1: Generate corpus ──────────────────────────────────────────────────
if [[ "$SKIP_GENERATE" == "false" ]]; then
  echo ""
  echo "[1/4] Generating synthetic corpus..."
    PYTHONPATH="$ROOT/$CANARY_DIR" \
    python3 "$CANARY_DIR/generate_corpus.py"

    echo ""
    echo "[2/4] Generating canary prompt suite..."
    PYTHONPATH="$ROOT/$CANARY_DIR" \
    python3 "$CANARY_DIR/generate_canary_suite.py"
else
  echo "[1-2/4] Skipping corpus/suite generation (--skip_generate)"
fi

# ── Step 2: Run model(s) ──────────────────────────────────────────────────────
if [[ "$SKIP_RUN" == "false" ]]; then
  echo ""
  echo "[3/4] Running canary suite against model(s)..."
  RUN_CMD=(
    python3 "$CANARY_DIR/run_canary.py"
    --config "$CONFIG"
    --suite "data/canary_suite.jsonl"
    --outdir "results/canary/runs"
  )
  if [[ -n "$PROFILES" ]]; then
    RUN_CMD+=(--profiles "$PROFILES")
  fi
  if [[ -n "$LIMIT" ]]; then
    RUN_CMD+=(--limit "$LIMIT")
  fi
  "${RUN_CMD[@]}"
else
  echo "[3/4] Skipping model run (--skip_run)"
fi

# ── Step 3: Score ─────────────────────────────────────────────────────────────
echo ""
echo "[4a/4] Scoring runs (CSR + CIR)..."
python3 "$CANARY_DIR/score_canary.py" \
  --runs_glob "results/canary/runs/*.jsonl" \
  --out_turn "results/canary/metrics/canary_metrics_turn.csv" \
  --out_summary "results/canary/metrics/canary_metrics_summary.csv"

# ── Step 4: Visualize ─────────────────────────────────────────────────────────
echo ""
echo "[4b/4] Generating heatmaps..."
python3 "$CANARY_DIR/plot_canary_heatmap.py" \
  --summary "results/canary/metrics/canary_metrics_summary.csv" \
  --outdir "artifacts/figures" \
  --metric "$METRIC"

# ── Curate artifacts ──────────────────────────────────────────────────────────
cp -f results/canary/metrics/canary_metrics_summary.csv artifacts/metrics/ 2>/dev/null || true
cp -f results/canary/metrics/canary_metrics_turn.csv    artifacts/metrics/ 2>/dev/null || true

echo ""
echo "============================================================"
echo " Done. Outputs:"
echo "   data/canary_corpus.jsonl"
echo "   data/canary_suite.jsonl"
echo "   results/canary/runs/*.jsonl"
echo "   results/canary/metrics/canary_metrics_turn.csv"
echo "   results/canary/metrics/canary_metrics_summary.csv"
echo "   artifacts/figures/canary_csr_heatmap_*.png"
echo "   artifacts/figures/canary_cir_heatmap_*.png"
echo "============================================================"