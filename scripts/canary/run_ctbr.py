#!/usr/bin/env python3
"""
run_ctbr.py
===========
Runs the CTBR session suite against configured model endpoints.

Extends run_sessions.py multi-turn architecture with:
  - Context length injection per session (num_ctx override from ctbr_meta)
  - Turn-phase tracking (pre_switch / switch / post_switch)
  - Per-turn bleed_detected placeholder (filled by score_ctbr.py)
  - Full conversation history maintained across all 8 turns

JSONL schema extends v2 with:
  turn_phase             : pre_switch | switch | post_switch
  sensitive_content_present : bool
  bleed_detected         : null (filled by scorer)
  ctbr_meta              : session-level metadata

Usage:
    python run_ctbr.py --config configs/run_config.yaml --profiles qwen_3b_t0,qwen_14b_t0
    python run_ctbr.py --config configs/run_config.yaml --profiles qwen_3b_t0 --limit 5
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

DEFAULT_SUITE  = Path(__file__).resolve().parents[2] / "data" / "ctbr_suite.jsonl"
DEFAULT_OUTDIR = Path(__file__).resolve().parents[2] / "results" / "ctbr" / "runs"


# ---------------------------------------------------------------------------
# Utilities (mirrors run_sessions.py / run_canary.py pattern)
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def _safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s)[:50]

def _make_run_id(run_name: str, profile: str, model: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    h = hashlib.sha1(f"{stamp}:{profile}:{model}".encode()).hexdigest()[:10]
    return f"{run_name}_{stamp}_{_slug(profile)}_{_slug(model)}_{h}"

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
    p = dict(cfg[profile] or {})
    if "host" not in p or "model" not in p:
        raise SystemExit(f"Profile '{profile}' must have host and model.")
    p.setdefault("options", {})
    return p


# ---------------------------------------------------------------------------
# Ollama HTTP (same pattern as run_sessions.py)
# ---------------------------------------------------------------------------

def _ollama_chat(
    host: str,
    model: str,
    messages: List[Dict[str, str]],
    options: Dict[str, Any],
    timeout_s: int = 300,
) -> Tuple[str, Dict[str, Any], int]:
    payload = {"model": model, "messages": messages, "stream": False, "options": options}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=f"{host.rstrip('/')}/api/chat",
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e
    latency_ms = int((time.perf_counter() - t0) * 1000)
    text = (raw.get("message") or {}).get("content") or ""
    return text, raw, latency_ms


# ---------------------------------------------------------------------------
# Core session runner
# ---------------------------------------------------------------------------

def run_profile(
    *,
    cfg: Dict[str, Any],
    profile_name: str,
    sessions: List[Dict[str, Any]],
    outdir: Path,
    run_name: str = "ctbr_run",
    shuffle: bool = False,
    seed: int = 42,
    limit: Optional[int] = None,
    timeout_s: int = 300,
) -> Path:
    profile_cfg = _select_profile(cfg, profile_name)
    host  = str(profile_cfg["host"])
    model = str(profile_cfg["model"])
    base_options = dict(profile_cfg.get("options") or {})

    sess_list = list(sessions)
    if shuffle:
        random.Random(seed).shuffle(sess_list)
    if limit:
        sess_list = sess_list[:int(limit)]

    run_id  = _make_run_id(run_name, profile_name, model)
    outpath = outdir / f"{run_id}.jsonl"

    print(f"\n[ctbr/run] run_id={run_id}")
    print(f"[ctbr/run] profile={profile_name}  model={model}")
    print(f"[ctbr/run] sessions={len(sess_list)}  shuffle={shuffle}  seed={seed}")
    print(f"[ctbr/run] writing → {outpath}")

    total_turns = 0

    with outpath.open("w", encoding="utf-8") as f:
        for sidx, session in enumerate(sess_list):
            scenario_id = session.get("scenario_id", f"ctbr_{sidx:04d}")
            system      = session.get("system", "")
            turns       = session.get("turns", [])
            tags        = session.get("tags", []) or []
            ctbr_meta   = session.get("ctbr_meta", {})

            # Per-session context length override
            ctx_len = ctbr_meta.get("context_length", 2048)
            session_options = dict(base_options)
            session_options["num_ctx"] = ctx_len

            if not isinstance(turns, list) or not turns:
                continue

            user_turns = [t for t in turns if isinstance(t, dict) and t.get("role") == "user"]
            if not user_turns:
                continue

            # Build conversation incrementally — full history passed each turn
            history: List[Dict[str, str]] = []

            for turn_i, turn in enumerate(user_turns):
                user_text  = (turn or {}).get("content", "")
                turn_phase = (turn or {}).get("turn_phase", "unknown")
                turn_number = (turn or {}).get("turn_number", turn_i)
                sensitive_present = bool((turn or {}).get("sensitive_content_present", False))

                # Build full message list: system + history + current user turn
                messages: List[Dict[str, str]] = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.extend(history)
                messages.append({"role": "user", "content": user_text})

                started_at = _utc_now_iso()
                try:
                    assistant_text, raw, latency_ms = _ollama_chat(
                        host=host, model=model,
                        messages=messages,
                        options=session_options,
                        timeout_s=timeout_s,
                    )
                    error = None
                except RuntimeError as e:
                    assistant_text, raw, latency_ms = "", {}, -1
                    error = str(e)
                ended_at = _utc_now_iso()

                rec: Dict[str, Any] = {
                    # ── Standard v2 schema ──────────────────────────
                    "run_id":           run_id,
                    "run_name":         run_name,
                    "profile":          profile_name,
                    "scenario_id":      scenario_id,
                    "scenario_index":   sidx,
                    "turn_index":       turn_i,
                    "turn_number":      turn_number,
                    "started_at":       started_at,
                    "ended_at":         ended_at,
                    "latency_ms":       latency_ms,
                    "host":             host,
                    "model":            model,
                    "options":          session_options,
                    "system":           system,
                    "tags":             tags,
                    "user_text":        user_text,
                    "messages":         messages,
                    "assistant_text":   assistant_text,
                    "ollama_raw":       raw,
                    # ── CTBR extension fields ────────────────────────
                    "turn_phase":               turn_phase,
                    "sensitive_content_present": sensitive_present,
                    "bleed_detected":           None,   # filled by score_ctbr.py
                    "domain":                   ctbr_meta.get("domain"),
                    "memory_condition":         ctbr_meta.get("memory_condition"),
                    "context_length":           ctx_len,
                    "postswitch_task":          ctbr_meta.get("postswitch_task"),
                    "fingerprints":             ctbr_meta.get("fingerprints", []),
                    "ctbr_meta":                ctbr_meta,
                    "error":                    error,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()

                # Accumulate history for next turn
                history.append({"role": "user",      "content": user_text})
                history.append({"role": "assistant",  "content": assistant_text})
                total_turns += 1

            pct = (sidx + 1) / len(sess_list) * 100
            print(f"[ctbr/run] {sidx+1}/{len(sess_list)} ({pct:.0f}%)  {scenario_id}")

    print(f"[ctbr/run] done. profile={profile_name}  turns_logged={total_turns}  file={outpath}")
    return outpath


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Run CTBR session suite")
    ap.add_argument("--config",   required=True,  help="configs/run_config.yaml")
    ap.add_argument("--suite",    default=str(DEFAULT_SUITE))
    ap.add_argument("--outdir",   default=str(DEFAULT_OUTDIR))
    ap.add_argument("--profiles", default="", help="Comma-separated profiles (default: all)")
    ap.add_argument("--limit",    type=int, default=None)
    ap.add_argument("--shuffle",  action="store_true")
    ap.add_argument("--seed",     type=int, default=42)
    ap.add_argument("--timeout_s", type=int, default=300)
    args = ap.parse_args()

    cfg = _load_yaml(Path(args.config))
    run_cfg = cfg.get("run", {}) or {}

    suite_path = Path(args.suite)
    if not suite_path.exists():
        raise SystemExit(f"Suite not found: {suite_path}\nRun generate_ctbr_suite.py first.")
    sessions = _read_jsonl(suite_path)

    outdir = Path(args.outdir)
    _safe_mkdir(outdir)

    run_name = run_cfg.get("run_name", "ctbr_run")
    shuffle  = bool(run_cfg.get("shuffle", args.shuffle))
    seed     = int(run_cfg.get("seed",    args.seed))

    all_profiles = _profile_keys(cfg)
    profiles_to_run = (
        [p.strip() for p in args.profiles.split(",") if p.strip()]
        if args.profiles else all_profiles
    )

    print(f"[ctbr/run] profiles: {profiles_to_run}")
    print(f"[ctbr/run] suite: {suite_path} ({len(sessions)} sessions × 8 turns each)")

    for profile_name in profiles_to_run:
        run_profile(
            cfg=cfg,
            profile_name=profile_name,
            sessions=sessions,
            outdir=outdir,
            run_name=run_name,
            shuffle=shuffle,
            seed=seed,
            limit=args.limit,
            timeout_s=args.timeout_s,
        )

    print("\n[ctbr/run] All profiles complete.")


if __name__ == "__main__":
    main()