1. Run parameterized scripts:

python scripts/run_model_ollama.py --config configs/dev_rog.yaml --modelid qwen_3b


python scripts/score_run.py --run results/runs/<new_run_id>.jsonl


python scripts/score_run.py --run results/runs/dev_rog_smoke_20260221_211306_qwen2.5-3b_3e743f5f8dd7.jsonl


## Get Task Level Accuracy:
python - <<EOF
import csv
from collections import defaultdict

f="results/metrics/dev_rog_smoke_20260221_211306_qwen2.5-3b_3e743f5f8dd7.csv"
rows=list(csv.DictReader(open(f)))

by_task=defaultdict(list)
for r in rows:
    by_task[r["task"]].append(int(r["score"]))

for k,v in by_task.items():
    print(k, round(sum(v)/len(v),3), "n=", len(v))
EOF


## Get Overall Accuracy:

python - <<EOF
import csv
f="results/metrics/dev_rog_smoke_20260221_211306_qwen2.5-3b_3e743f5f8dd7.csv"
rows=list(csv.DictReader(open(f)))
acc=sum(int(r["score"]) for r in rows)/len(rows)
print("Overall accuracy:", round(acc,3))
EOF


## End to End Run:
dev_rog_smoke_20260221_220423_phi3-mini_3e743f5f8dd7.json

### Phi:Mini
python scripts/run_model_ollama.py --config configs/dev_rog.yaml --modelid ollama
python scripts/score_run.py --run results/runs/dev_rog_smoke_20260221_220423_phi3-mini_3e743f5f8dd7.jsonl
python scripts/make_report.py --metrics results/metrics/dev_rog_smoke_20260221_220423_phi3-mini_3e743f5f8dd7.csv
python scripts/make_leaderboard.py

python scripts/compare_runs.py \
  --a results/metrics/dev_rog_smoke_20260221_220423_phi3-mini_3e743f5f8dd7.csv \
  --b results/metrics/dev_rog_smoke_20260221_211306_qwen2.5-3b_3e743f5f8dd7.csv
  
### Qwen #b:




### deterministic vs freedom rune:

#### Run Models:
python scripts/run_model_ollama.py --config configs/dev_rog.yaml --modelid qwen_3b_t0
python scripts/run_model_ollama.py --config configs/dev_rog.yaml --modelid qwen_3b
python scripts/run_model_ollama.py --config configs/dev_rog.yaml --modelid phi_mini
python scripts/run_model_ollama.py --config configs/dev_rog.yaml --modelid phi_mini_t0

python3 scripts/run_models.py --model small
python3 scripts/run_models.py --model medium
python3 scripts/run_models.py --model large
python3 scripts/run_models.py --model xlarge




#### Run Scoring:
python scripts/score_run.py --run results/runs/dev_rog_smoke_20260221_223826_qwen_3b_t0_qwen2.5-3b_6b98c7b3cc22.jsonl
python scripts/score_run.py --run results/runs/dev_rog_smoke_20260221_223832_qwen_3b_qwen2.5-3b_6b98c7b3cc22.jsonl
python scripts/score_run.py --run results/runs/dev_rog_smoke_20260221_223837_phi_mini_phi3-mini_6b98c7b3cc22.jsonl
python scripts/score_run.py --run results/runs/dev_rog_smoke_20260221_223845_phi_mini_t0_phi3-mini_6b98c7b3cc22.jsonl

python3 scripts/score_all_runs.py --runs_dir results/runs --pattern "dev_rog_smoke_20260223_*.jsonl"


#### Make Reports:

python scripts/make_report.py --metrics results/metrics/dev_rog_smoke_20260221_223826_qwen_3b_t0_qwen2.5-3b_6b98c7b3cc22.csv
python scripts/make_report.py --metrics results/metrics/dev_rog_smoke_20260221_223832_qwen_3b_qwen2.5-3b_6b98c7b3cc22.csv
python scripts/make_report.py --metrics results/metrics/dev_rog_smoke_20260221_223837_phi_mini_phi3-mini_6b98c7b3cc22.csv
python scripts/make_report.py --metrics results/metrics/dev_rog_smoke_20260221_223845_phi_mini_t0_phi3-mini_6b98c7b3cc22.csv

python3 scripts/make_report_all_runs.py --runs_dir results/metrics --pattern "dev_rog_smoke_20260223_*.csv"


#### Get Leaderboard:
python scripts/make_leaderboard.py

python scripts/make_leaderboard_grouped.py


#### Add Confidence Intervals:
python3 scripts/add_confidence_intervals.py \
  --inputs "results/metrics/dev_rog_smoke_20260223_*.csv" \
  --out_csv results/leaderboards/rog_smoke_ci_20260223.csv \
  --out_md  results/leaderboards/rog_smoke_ci_20260223.md






## Prompt Expansion:

### Expansion via Paraphrases:

python3 scripts/expand_suite_v1.py \
  --in_jsonl ./data/prompts/v1_suite.jsonl \
  --out_jsonl ./data/prompts/v1_suite_120.jsonl \
  --manifest_out ./data/prompts/v1_suite_120.manifest.json \
  --include_original \
  --enable_paraphrase \
  --paraphrase_k 3

### Expansion via Numeric Perturbations:

python3 scripts/expand_suite_v1.py \
  --in_jsonl ./data/prompts/v1_suite.jsonl \
  --out_jsonl ./data/prompts/v1_suite_exp.jsonl \
  --manifest_out ./data/prompts/v1_suite_exp.manifest.json \
  --include_original \
  --enable_paraphrase --paraphrase_k 5 \
  --enable_numeric --numeric_k 10 \
  --seed 1337

python3 scripts/expand_suite_v1.py \
  --in_jsonl ./data/prompts/v1_suite.jsonl \
  --out_jsonl ./data/prompts/v1_suite_big.jsonl \
  --manifest_out ./data/prompts/v1_suite_big.manifest.json \
  --include_original \
  --enable_paraphrase --paraphrase_k 20 \
  --enable_format --format_k 10 \
  --enable_numeric --numeric_k 10 \
  --seed 1337