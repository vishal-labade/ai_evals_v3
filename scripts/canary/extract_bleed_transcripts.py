#!/usr/bin/env python3
"""
extract_bleed_transcripts.py
=============================
Pulls full conversation transcripts for CTBR sessions where a specific
turn was flagged as bleed_detected (or not), for manual qualitative review.

This is the validation step before trusting aggregate CTBR numbers --
especially for cross-family comparisons where verbosity/style differences
between model families could produce scorer artifacts rather than genuine
privacy bleed.

Usage:
    # Pull 5 bleed=1 turn-7 transcripts from gemma2:9b
    python3 extract_bleed_transcripts.py \
        --runs_glob "results/ctbr/runs/*gemma_9b*.jsonl" \
        --turn_decay_csv results/ctbr/metrics/ctbr_turn.csv \
        --turn_number 7 --bleed_only --n 5

    # Pull 3 non-bleed turn-7 transcripts from qwen2.5:14b for contrast
    python3 extract_bleed_transcripts.py \
        --runs_glob "results/ctbr/runs/*qwen_14b*.jsonl" \
        --turn_decay_csv results/ctbr/metrics/ctbr_turn.csv \
        --turn_number 7 --no_bleed_only --n 3

    # Output to a markdown file for easy reading/sharing
    python3 extract_bleed_transcripts.py \
        --runs_glob "results/ctbr/runs/*gemma2_27b*.jsonl" \
        --turn_decay_csv results/ctbr/metrics/ctbr_turn.csv \
        --turn_number 7 --bleed_only --n 8 \
        --out artifacts/transcripts/gemma2_27b_turn7_bleed.md
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_jsonl(pattern: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return records


def _load_turn_csv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Session reconstruction
# ---------------------------------------------------------------------------

def _group_sessions(records: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """(model, scenario_id) -> ordered list of turn records (by turn_index)."""
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in records:
        key = (r.get("model", ""), r.get("scenario_id", ""))
        groups.setdefault(key, []).append(r)
    for key in groups:
        groups[key].sort(key=lambda r: r.get("turn_index", 0))
    return groups


def _find_target_sessions(
    scored_rows: List[Dict[str, Any]],
    turn_number: int,
    bleed_only: Optional[bool],
    model_filter: Optional[set] = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """
    From the scored turn CSV, find (model, scenario_id, scored_row) tuples
    matching turn_number and the bleed filter.

    bleed_only: True -> only bleed_detected==1
                False -> only bleed_detected==0
                None  -> no filter on bleed (turn_phase==post_switch still required)

    model_filter: if provided, only consider rows whose 'model' field is in
                   this set. The scored CSV typically contains ALL models'
                   results (score_ctbr.py globs every run file), and scenario_ids
                   are SHARED across models (same 216 scenarios run against every
                   model) -- so without this filter, a match for the wrong model
                   can be returned for the same scenario_id.
    """
    matches: List[Tuple[str, str, Dict[str, Any]]] = []
    for row in scored_rows:
        if row.get("turn_phase") != "post_switch":
            continue

        if model_filter is not None and row.get("model", "") not in model_filter:
            continue

        try:
            tn = int(float(row.get("turn_number", -1)))
        except ValueError:
            continue
        if tn != turn_number:
            continue

        bleed_val = row.get("bleed_detected", "")
        try:
            bleed_int = int(float(bleed_val)) if bleed_val != "" else None
        except ValueError:
            bleed_int = None

        if bleed_only is True and bleed_int != 1:
            continue
        if bleed_only is False and bleed_int != 0:
            continue

        matches.append((row.get("model", ""), row.get("scenario_id", ""), row))

    return matches


# ---------------------------------------------------------------------------
# Transcript formatting
# ---------------------------------------------------------------------------

def _format_transcript(
    session_turns: List[Dict[str, Any]],
    scored_row: Dict[str, Any],
    target_turn_number: int,
) -> str:
    """Render a full 8-turn session as readable markdown, highlighting the target turn."""
    lines: List[str] = []

    model = session_turns[0].get("model", "?") if session_turns else "?"
    scenario_id = session_turns[0].get("scenario_id", "?") if session_turns else "?"
    domain = session_turns[0].get("domain", "?") if session_turns else "?"
    postswitch_task = session_turns[0].get("postswitch_task", "?") if session_turns else "?"
    memory_condition = session_turns[0].get("memory_condition", "?") if session_turns else "?"
    context_length = session_turns[0].get("context_length", "?") if session_turns else "?"
    fingerprints = session_turns[0].get("fingerprints", []) if session_turns else []

    lines.append(f"## {scenario_id}")
    lines.append("")
    lines.append(f"- **model**: `{model}`")
    lines.append(f"- **domain**: {domain}  |  **post-switch task**: {postswitch_task}")
    lines.append(f"- **memory_condition**: {memory_condition}  |  **context_length**: {context_length}")
    lines.append(f"- **target turn**: {target_turn_number}")
    lines.append(f"- **bleed_detected** (target turn): `{scored_row.get('bleed_detected', '')}`")
    lines.append(f"- **fp_match**: `{scored_row.get('fp_match', '')}`")
    lines.append(f"- **sem_sim**: `{scored_row.get('sem_sim', '')}`")
    lines.append("")
    lines.append("**Canary fingerprints for this session:**")
    for fp in fingerprints:
        lines.append(f"- `{fp}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    for turn in session_turns:
        ti = turn.get("turn_index", "?")
        tn = turn.get("turn_number", ti)
        phase = turn.get("turn_phase", "?")
        user_text = turn.get("user_text", "")
        assistant_text = turn.get("assistant_text", "")

        marker = " 🎯 TARGET TURN" if tn == target_turn_number else ""
        phase_label = {
            "pre_switch": "PRE-SWITCH (sensitive task)",
            "switch": "CONTEXT SWITCH",
            "post_switch": "POST-SWITCH (unrelated task)",
        }.get(phase, phase)

        lines.append(f"### Turn {tn} — {phase_label}{marker}")
        lines.append("")
        lines.append(f"**User:** {user_text}")
        lines.append("")
        lines.append(f"**Assistant:** {assistant_text}")
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Extract CTBR session transcripts for qualitative review")
    ap.add_argument("--runs_glob", required=True,
                    help="Glob for run JSONL files, e.g. 'results/ctbr/runs/*gemma_9b*.jsonl'")
    ap.add_argument("--turn_decay_csv", default="results/ctbr/metrics/ctbr_turn.csv",
                    help="Path to ctbr_turn.csv (scored output from score_ctbr.py)")
    ap.add_argument("--turn_number", type=int, default=7,
                    help="Which post-switch turn_number to filter on (4-7)")

    bleed_group = ap.add_mutually_exclusive_group()
    bleed_group.add_argument("--bleed_only", action="store_true",
                              help="Only sessions where bleed_detected==1 at turn_number")
    bleed_group.add_argument("--no_bleed_only", action="store_true",
                              help="Only sessions where bleed_detected==0 at turn_number")

    ap.add_argument("--n", type=int, default=5,
                    help="Max number of transcripts to extract")
    ap.add_argument("--out", default=None,
                    help="Output markdown file. If omitted, prints to stdout.")
    args = ap.parse_args()

    bleed_only: Optional[bool]
    if args.bleed_only:
        bleed_only = True
    elif args.no_bleed_only:
        bleed_only = False
    else:
        bleed_only = None

    # Load run records and scored turn CSV
    print(f"[extract] loading runs: {args.runs_glob}")
    records = _load_jsonl(args.runs_glob)
    print(f"[extract] loaded {len(records)} turn records")

    print(f"[extract] loading scored turns: {args.turn_decay_csv}")
    scored_rows = _load_turn_csv(args.turn_decay_csv)
    print(f"[extract] loaded {len(scored_rows)} scored rows")

    sessions = _group_sessions(records)

    # Derive the set of model names actually present in the loaded run files.
    # This ensures we only match scored rows belonging to THESE models --
    # critical because ctbr_turn.csv contains all models combined and
    # scenario_ids are shared across models.
    models_in_runs = set(r.get("model", "") for r in records if r.get("model"))
    if not models_in_runs:
        print("[extract] WARNING: no 'model' field found in loaded run records")
    else:
        print(f"[extract] models in loaded runs: {sorted(models_in_runs)}")

    matches = _find_target_sessions(scored_rows, args.turn_number, bleed_only, model_filter=models_in_runs)

    filter_label = {True: "bleed=1", False: "bleed=0", None: "any"}[bleed_only]
    print(f"[extract] found {len(matches)} sessions matching turn={args.turn_number}, filter={filter_label}")

    if not matches:
        print("[extract] no matches found. Check --runs_glob and --turn_decay_csv align with the same model.")
        return

    matches = matches[: args.n]

    output_chunks: List[str] = []
    header = (
        f"# CTBR Transcript Review\n\n"
        f"**Filter**: turn_number={args.turn_number}, bleed_detected={filter_label}\n\n"
        f"**Runs glob**: `{args.runs_glob}`\n\n"
        f"**Showing**: {len(matches)} session(s)\n\n"
        f"---\n\n"
    )
    output_chunks.append(header)

    for model, scenario_id, scored_row in matches:
        session_turns = sessions.get((model, scenario_id), [])
        if not session_turns:
            output_chunks.append(f"## {scenario_id}\n\n*(no run records found for model={model})*\n\n---\n\n")
            continue
        output_chunks.append(_format_transcript(session_turns, scored_row, args.turn_number))

    full_output = "\n".join(output_chunks)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(full_output, encoding="utf-8")
        print(f"[extract] wrote {len(matches)} transcripts -> {out_path}")
    else:
        print("\n" + full_output)


if __name__ == "__main__":
    main()