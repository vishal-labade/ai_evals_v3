# Run Instructions for V2 Version:

---

## Expanding the Scenario Suite:

**Run the generator:**
`python3 scripts/expand_v2_suite.py`

**Copy the data to immutable file for separation:**
head -n 50 data/v2_scenarios_expanded.jsonl > data/v2_suite_50.jsonl

---

## Run Behavioral Lane:

**Session Runner:**

``` 
    python3 scripts/run_sessions.py \
  --config configs/run_config.yaml \
  --scenarios data/v2_suite_50.jsonl && \

```

**Scorecard Generator:**

```
    python3 results/v2/scorecard.py \
  --scenarios data/v2_suite_50.jsonl

```

**Run only selected profiles + score:**

```
    python3 scripts/run_sessions.py \
    --config configs/run_config.yaml \
    --scenarios data/v2_suite_50.jsonl \
    --profiles qwen_14b_t0,gpt_20b_t0,mixtral_moe_7b_t0 && \

    python3 results/v2/scorecard.py \
    --scenarios data/v2_suite_50.jsonl

```

**Run Session Runner and scorecard in one go:**

`./scripts/run_behavioral_and_score.sh`

*Run Selected Profiles only:*

`./scripts/run_behavioral_and_score.sh --profiles qwen_14b_t0,gpt_20b_t0`

*Clean Run Logs:*

`./scripts/run_behavioral_and_score.sh --clean --profiles qwen_14b_t0`


**Metrics Location:**

```
results/v2/metrics/behavioral_metrics.csv
results/v2/model_scorecard.json

```

---

## Run Experiments:

**Run all experiments:**

```
    python3 scripts/run_experiments.py \
    --experiments configs/experiments.yaml

```

**Run only Context cliff experiment:**

``` 
    python3 scripts/run_experiments.py \
    --experiments configs/experiments.yaml \
    --only context_cliff_qwen14b

```

**Run only one Cell:**

```
    python3 scripts/run_experiments.py \
        --experiments configs/experiments.yaml \
        --only context_cliff_qwen14b

```

**Report Location:**

`results/v2/runs/`

---
s
## Compute Memory Compliance Metrics (MCS)

**Run the experiment:**

`python3 results/v2/metrics/memory_compliance.py`

**Metrics Location:**

``` 
    results/v2/metrics/metrics_turn.csv
    results/v2/metrics/metrics_run.csv

```
---

## Sanity Checks:

**Check Memory Results exist:**

`cat results/v2/metrics/metrics_run.csv`

 > You should see non-empty mcs_n for runs that include memory scenarios.
    >
    >   If mcs_n is 0: </br>
    >    → Your suite doesn’t include memory scenarios (or checks.memory missing).

---


## Running Experiments:

**Family 1: Context cliff (fixed model, sweep ctx):**

```
python3 scripts/run_experiments.py \
  --experiments configs/experiments.yaml \
  --only context_cliff_qwen14b

```


**Family 2: Fixed ctx, model-size compare (3B vs 20B, etc.)**

```
python3 scripts/run_experiments.py \
  --experiments configs/experiments.yaml \
  --only fixed_ctx_model_size
```


**Family 3: Tradeoff (14B long ctx vs 20B short ctx)**

```
python3 scripts/run_experiments.py \
  --experiments configs/experiments.yaml \
  --only tradeoff_ctx_vs_size

```


**Family 4: MoE vs dense at fixed ctx:**

```
python3 scripts/run_experiments.py \
  --experiments configs/experiments.yaml \
  --only moe_fixed_ctx

```

### Experiments Summary:

```
python3 scripts/enrich_metrics_with_run_metadata.py \
  --runs_glob "results/v2/runs/*.jsonl" \
  --metrics_run results/v2/metrics/metrics_run.csv \
  --metrics_turn results/v2/metrics/metrics_turn.csv \
  --out_run results/v2/metrics_run_enriched.csv \
  --enrich_turn
```