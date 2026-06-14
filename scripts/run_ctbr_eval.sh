#!/usr/bin/env bash
# =============================================================================
# run_ctbr_eval.sh
# Cross-Turn Privacy Bleed (CTBR) evaluation pipeline
#
# Usage:
#   ./scripts/run_ctbr_eval.sh --config configs/run_config.yaml \
#       --profiles qwen_3b_t0,qwen_14b_t0
#   ./scripts/run_ctbr_eval.sh --limit 5     # smoke test
#   ./scripts/run_ctbr_eval.sh --skip_generate
#   ./scripts/run_ctbr_eval.sh --skip_run    # re-score only
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CTBR_DIR="scripts/canary"
CONFIG="configs/run_config.yaml"
PROFILES=""
LIMIT=""
SKIP_GENERATE=false
SKIP_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)         CONFIG="$2";          shift 2 ;;
    --profiles)       PROFILES="$2";        shift 2 ;;
    --limit)          LIMIT="$2";           shift 2 ;;
    --skip_generate)  SKIP_GENERATE=true;   shift   ;;
    --skip_run)       SKIP_RUN=true;        shift   ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p data results/ctbr/runs results/ctbr/metrics artifacts/figures artifacts/metrics

echo "============================================================"
echo " Cross-Turn Privacy Bleed (CTBR) Evaluation Pipeline"
echo "============================================================"
echo " config:   $CONFIG"
echo " profiles: ${PROFILES:-<ALL>}"
echo " limit:    ${LIMIT:-<none>}"
echo "------------------------------------------------------------"

# ── Step 1: Generate suite ────────────────────────────────────────────────────
if [[ "$SKIP_GENERATE" == "false" ]]; then
  echo ""
  echo "[1/4] Generating CTBR session suite..."
  PYTHONPATH="$ROOT/$CTBR_DIR" \
    python3 "$CTBR_DIR/generate_ctbr_suite.py"

  echo ""
  wc -l data/ctbr_suite.jsonl
else
  echo "[1/4] Skipping suite generation (--skip_generate)"
fi

# ── Step 2: Run ───────────────────────────────────────────────────────────────
if [[ "$SKIP_RUN" == "false" ]]; then
  echo ""
  echo "[2/4] Running CTBR sessions against model(s)..."
  RUN_CMD=(
    python3 "$CTBR_DIR/run_ctbr.py"
    --config "$CONFIG"
    --suite  "data/ctbr_suite.jsonl"
    --outdir "results/ctbr/runs"
    --timeout_s 300
  )
  [[ -n "$PROFILES" ]] && RUN_CMD+=(--profiles "$PROFILES")
  [[ -n "$LIMIT"    ]] && RUN_CMD+=(--limit    "$LIMIT")
  "${RUN_CMD[@]}"
else
  echo "[2/4] Skipping run (--skip_run)"
fi

# ── Step 3: Score ─────────────────────────────────────────────────────────────
echo ""
echo "[3/4] Scoring (CTBR + PRR + decay)..."
python3 "$CTBR_DIR/score_ctbr.py" \
  --runs_glob  "results/ctbr/runs/*.jsonl" \
  --out_turn   "results/ctbr/metrics/ctbr_turn.csv" \
  --out_summary "results/ctbr/metrics/ctbr_summary.csv" \
  --out_decay  "results/ctbr/metrics/ctbr_decay.csv"

# ── Step 4: Visualize ─────────────────────────────────────────────────────────
echo ""
echo "[4/4] Generating decay curves and heatmaps..."
python3 "$CTBR_DIR/plot_ctbr.py" \
  --decay   "results/ctbr/metrics/ctbr_decay.csv" \
  --summary "results/ctbr/metrics/ctbr_summary.csv" \
  --outdir  "artifacts/figures"

cp -f results/ctbr/metrics/ctbr_summary.csv artifacts/metrics/ 2>/dev/null || true
cp -f results/ctbr/metrics/ctbr_decay.csv   artifacts/metrics/ 2>/dev/null || true

echo ""
echo "============================================================"
echo " Done. Outputs:"
echo "   data/ctbr_suite.jsonl"
echo "   results/ctbr/runs/*.jsonl"
echo "   results/ctbr/metrics/ctbr_turn.csv"
echo "   results/ctbr/metrics/ctbr_summary.csv"
echo "   results/ctbr/metrics/ctbr_decay.csv"
echo "   artifacts/figures/ctbr_decay_*.png"
echo "   artifacts/figures/ctbr_summary_heatmap_*.png"
echo "============================================================"