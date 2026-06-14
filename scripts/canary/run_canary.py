#!/usr/bin/env python3
"""
run_canary.py
=============
Runs the canary injection suite against a configured model endpoint.

Extends the ai_evals_v2 run_sessions architecture:
  - Same JSONL schema (run_id, scenario_id, turn_index, user_text, assistant_text, ...)
  - Adds: privacy_meta, canary_type, task_category, variant fields to each row

Usage:
    python run_canary.py --config configs/run_config.yaml --profile qwen_14b_t0
    python run_canary.py --config configs/run_config.yaml --profile qwen_14b_t0 --limit 20
    python run_canary.py --config configs/run_config.yaml --profiles qwen_3b_t0,qwen_14b_t0

Output: results/canary/runs/{run_id}.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

import yaml


DEFAULT_SUITE = Path(__file__).parent.parent / "data" / "canary_suite.jsonl"
DEFAULT_OUTDIR = Path(__file__).parent.parent / "results" / "canary" / "runs"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s)[:60]


def _make_run_id(run_name: str, profile: str, model: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    h = hashlib.sha1(f"{stamp}:{profile}:{model}".encode("utf-8")).hexdigest()[:10]
    return f"{run_name}_{stamp}_{_slug(profile)}_{_slug(model)}_{h}"


# ---------------------------------------------------------------------------
# Ollama HTTP helper (matches run_sessions.py pattern)
# ---------------------------------------------------------------------------

def _ollama_chat(
    host: str,
    model: str,
    messages: List[Dict[str, str]],
    options: Dict[str, Any],
    timeout_s: int = 180,
) -> Tuple[str, Dict[str, Any], int]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options or {},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{host.rstrip('/')}/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_text = resp.read().decode("utf-8")
            raw = json.loads(raw_text)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTPError {e.code}: {err}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e
    t1 = time.perf_counter()

    latency_ms = int((t1 - t0) * 1000)
    assistant_text = (raw.get("message") or {}).get("content") or ""
    return assistant_text, raw, latency_ms


def _build_messages(system: str, user_text: str) -> List[Dict[str, str]]:
    """Single-turn: system + one user message (all context is in system prompt)."""
    msgs: List[Dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user_text})
    return msgs


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _profile_keys(cfg: Dict[str, Any]) -> List[str]:
    skip = {"run", "input_format", "prompts"}
    return sorted(
        k for k, v in cfg.items()
        if k not in skip and isinstance(v, dict) and "host" in v and "model" in v
    )


def _select_profile(cfg: Dict[str, Any], profile: str) -> Dict[str, Any]:
    if profile not in cfg:
        known = _profile_keys(cfg)
        raise SystemExit(f"Unknown profile '{profile}'. Known: {', '.join(known)}")
    p = cfg[profile] or {}
    if "host" not in p or "model" not in p:
        raise SystemExit(f"Profile '{profile}' must contain host and model.")
    p.setdefault("options", {})
    return p


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_profile(
    *,
    cfg: Dict[str, Any],
    profile_name: str,
    scenarios: List[Dict[str, Any]],
    outdir: Path,
    run_name: str = "canary_run",
    shuffle: bool = False,
    seed: int = 42,
    limit: Optional[int] = None,
    timeout_s: int = 180,
) -> Path:
    profile_cfg = _select_profile(cfg, profile_name)
    host = str(profile_cfg["host"])
    model = str(profile_cfg["model"])
    options = dict(profile_cfg.get("options") or {})

    scen_list = list(scenarios)
    if shuffle:
        random.Random(seed).shuffle(scen_list)
    if limit:
        scen_list = scen_list[:int(limit)]

    run_id = _make_run_id(run_name, profile_name, model)
    outpath = outdir / f"{run_id}.jsonl"

    print(f"\n[canary/run] run_id={run_id}")
    print(f"[canary/run] profile={profile_name} model={model}")
    print(f"[canary/run] scenarios={len(scen_list)} shuffle={shuffle} seed={seed}")
    print(f"[canary/run] writing → {outpath}")

    total_turns = 0
    with outpath.open("w", encoding="utf-8") as f:
        for sidx, scenario in enumerate(scen_list):
            scenario_id = scenario.get("scenario_id", f"canary_{sidx:04d}")
            system = scenario.get("system", "")
            turns = scenario.get("turns", [])
            tags = scenario.get("tags", []) or []
            privacy_meta = scenario.get("privacy_meta", {})

            if not isinstance(turns, list) or not turns:
                continue

            user_turns = [t for t in turns if isinstance(t, dict) and t.get("role") == "user"]
            if not user_turns:
                continue

            for turn_i, turn in enumerate(user_turns):
                user_text = (turn or {}).get("content", "")
                messages = _build_messages(system=system, user_text=user_text)

                started_at = _utc_now_iso()
                try:
                    assistant_text, raw, latency_ms = _ollama_chat(
                        host=host,
                        model=model,
                        messages=messages,
                        options=options,
                        timeout_s=timeout_s,
                    )
                    error = None
                except RuntimeError as e:
                    assistant_text = ""
                    raw = {}
                    latency_ms = -1
                    error = str(e)

                ended_at = _utc_now_iso()

                rec: Dict[str, Any] = {
                    # ── Standard v2 schema ──────────────────────────────
                    "run_id": run_id,
                    "run_name": run_name,
                    "profile": profile_name,
                    "scenario_id": scenario_id,
                    "scenario_index": sidx,
                    "turn_index": turn_i,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "latency_ms": latency_ms,
                    "host": host,
                    "model": model,
                    "options": options,
                    "system": system,
                    "tags": tags,
                    "user_text": user_text,
                    "messages": messages,
                    "assistant_text": assistant_text,
                    "ollama_raw": raw,
                    # ── Privacy extension fields ─────────────────────────
                    "canary_type": privacy_meta.get("canary_type"),
                    "task_category": privacy_meta.get("task_category"),
                    "variant": privacy_meta.get("variant"),
                    "prompt_index": privacy_meta.get("prompt_index"),
                    "corpus_id": privacy_meta.get("corpus_id"),
                    "privacy_meta": privacy_meta,
                    "error": error,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                total_turns += 1

            pct = (sidx + 1) / len(scen_list) * 100
            print(f"[canary/run] {sidx+1}/{len(scen_list)} ({pct:.0f}%) {scenario_id}")

    print(f"[canary/run] done. profile={profile_name} turns_logged={total_turns} file={outpath}")
    return outpath


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Run canary injection suite")
    ap.add_argument("--config", type=str, required=True, help="configs/run_config.yaml")
    ap.add_argument("--suite", type=str, default=str(DEFAULT_SUITE),
                    help="Path to canary_suite.jsonl")
    ap.add_argument("--outdir", type=str, default=str(DEFAULT_OUTDIR),
                    help="Output directory for run JSONL files")
    ap.add_argument("--profiles", type=str, default="",
                    help="Comma-separated profiles to run (default: all)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limit number of scenarios per profile (for testing)")
    ap.add_argument("--shuffle", action="store_true", help="Shuffle scenarios")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout_s", type=int, default=180)
    args = ap.parse_args()

    cfg = _load_yaml(Path(args.config))
    run_cfg = cfg.get("run", {}) or {}

    suite_path = Path(args.suite)
    if not suite_path.exists():
        raise SystemExit(
            f"Suite not found: {suite_path}\n"
            "Run: python suite/generate_canary_suite.py first"
        )
    scenarios = _read_jsonl(suite_path)

    outdir = Path(args.outdir)
    _safe_mkdir(outdir)

    run_name = run_cfg.get("run_name", "canary_run")
    shuffle = bool(run_cfg.get("shuffle", args.shuffle))
    seed = int(run_cfg.get("seed", args.seed))

    all_profiles = _profile_keys(cfg)
    if args.profiles:
        profiles_to_run = [p.strip() for p in args.profiles.split(",") if p.strip()]
    else:
        profiles_to_run = all_profiles

    print(f"[canary/run] profiles to run: {profiles_to_run}")
    print(f"[canary/run] suite: {suite_path} ({len(scenarios)} scenarios)")

    for profile_name in profiles_to_run:
        run_profile(
            cfg=cfg,
            profile_name=profile_name,
            scenarios=scenarios,
            outdir=outdir,
            run_name=run_name,
            shuffle=shuffle,
            seed=seed,
            limit=args.limit,
            timeout_s=args.timeout_s,
        )

    print("\n[canary/run] All profiles complete.")


if __name__ == "__main__":
    main()