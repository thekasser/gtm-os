"""Generate ConvIntelligence call summaries via Claude API for each corpus account.

Reads each account JSON in corpus/, generates archetype-aware call summaries,
appends them to the file. The numerical structure (call_id, dates, roles,
conv_intelligence_score) is computed in code; the LLM produces only the
qualitative content (transcript_summary, sentiment fields, objections, etc.).

Cost expectation: ~50 accounts × 1 LLM call each at Haiku tier ≈ $1-3 total.

Usage:
    cd /Users/connorkasser/gtm-os/synth
    pip install anthropic                            # one-time
    export ANTHROPIC_API_KEY=sk-ant-...              # one-time
    python3 conversations.py                         # generate for all accounts
    python3 conversations.py --limit 3               # test on 3 accounts first
    python3 conversations.py --force                 # regenerate (re-spend tokens)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.stderr.write(
        "ERROR: anthropic package not installed.\n"
        "Run: pip install anthropic\n"
    )
    raise SystemExit(1)

from archetypes import ARCHETYPES, Archetype, ConversationProfile


MAX_CALLS_PER_ACCOUNT = 12   # cap so each account fits in one LLM call
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
CACHE_DIR = Path("cache/conversations")


# ─────────────────────────────────────────────────────────────────────
# Skeleton: dates + owner roles (computed in code, before LLM)
# ─────────────────────────────────────────────────────────────────────

def n_calls_for_account(profile: ConversationProfile, contract_age_days: int) -> int:
    months = max(1.0, contract_age_days / 30.0)
    natural = int(months * profile.calls_per_month)
    return max(1, min(natural, MAX_CALLS_PER_ACCOUNT))


def distribute_call_dates(
    n: int,
    contract_start: datetime,
    contract_age_days: int,
    departure_day,
    rng: random.Random,
) -> list[datetime]:
    """Distribute n call dates across contract age, clustering near departure if applicable."""
    if departure_day is not None and 0 < departure_day < contract_age_days:
        # Cluster more calls before departure to capture pre/post inflection
        n_pre = max(1, int(n * 0.65))
        n_post = max(1, n - n_pre)
        pre = sorted(rng.uniform(7, departure_day) for _ in range(n_pre))
        post = sorted(rng.uniform(departure_day, contract_age_days) for _ in range(n_post))
        days = pre + post
    else:
        days = sorted(rng.uniform(7, contract_age_days) for _ in range(n))
    return [contract_start + timedelta(days=int(d)) for d in days]


def assign_call_role(call_day: int, contract_age_days: int,
                     archetype_key: str, rng: random.Random) -> str:
    """Pick call_owner_role based on archetype and call timing."""
    if archetype_key in ("activating", "stalled_onboarding"):
        # Onboarding-heavy mix
        return rng.choices(["CSM", "AE", "SE"], weights=[0.6, 0.2, 0.2])[0]
    relative = call_day / max(1, contract_age_days)
    if relative < 0.15:
        return rng.choices(["CSM", "AE", "SE"], weights=[0.5, 0.3, 0.2])[0]
    return rng.choices(["CSM", "AM", "AE"], weights=[0.6, 0.3, 0.1])[0]


# ─────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────

CALL_SCHEMA = """{
  "transcript_summary": "1-2 sentence summary of what was discussed",
  "duration_minutes": 30,
  "overall_sentiment": "positive | neutral | negative",
  "prospect_sentiment": "positive | neutral | negative",
  "rep_sentiment": "positive | neutral | negative",
  "sentiment_drivers": ["short driver phrase", ...],
  "next_steps": [{"description": "...", "owner": "rep | prospect | both", "due_date_offset_days": 7}],
  "next_step_committed": true | false,
  "missing_next_step_flag": true | false,
  "competitors_mentioned": ["competitor name"],
  "new_competitor_flag": true | false,
  "objections_raised": [{"category": "pricing | technical | scope | timing | authority", "summary": "short phrase"}],
  "unaddressed_showstopper": true | false
}"""


def build_prompt(account: dict, archetype: Archetype, profile: ConversationProfile,
                 calls_skeleton: list[dict]) -> str:
    if profile.champion_present:
        if profile.champion_departure_day:
            champion_note = (
                f"Champion was present early but DEPARTED at day {profile.champion_departure_day}. "
                f"Calls AT or AFTER day {profile.champion_departure_day} should reflect: "
                f"champion absent, new contacts struggling to fill the gap, declining engagement."
            )
        else:
            champion_note = "Champion is present and engaged throughout the contract."
    else:
        champion_note = "No clear champion ever emerged at this account."

    objection_note = ", ".join(profile.objection_themes) if profile.objection_themes else "none specifically"

    calls_list = "\n".join(
        f"  - Call {i+1}: day_offset={c['day_offset']}, owner_role={c['owner_role']}"
        for i, c in enumerate(calls_skeleton)
    )

    return f"""You are generating realistic synthetic ConvIntelligence call summaries for a fictional B2B SaaS account in a GTM-OS prototype. Output is calibration data — not real customer information.

Account context:
- Company: {account['company_name']}
- Segment: {account['segment']}
- Vertical: {account['vertical']}
- ARR: ${account['arr_usd']:,.0f}
- Contract age: {account['contract_age_days_at_corpus_gen']} days

Archetype: {archetype.name}
Description: {archetype.description}

Conversation profile:
- Sentiment baseline: {profile.sentiment_baseline}
- Sentiment trajectory over time: {profile.sentiment_trajectory}
- Champion: {champion_note}
- Common objection themes: {objection_note}

Generate {len(calls_skeleton)} call summaries. The day_offset and owner_role for each call are pre-assigned — match that timing in the content (e.g., a CSM call at day_offset 30 sounds like onboarding; an AE call at day_offset 350 sounds like renewal).

Pre-assigned skeleton:
{calls_list}

Each call should:
1. Match the archetype's profile and trajectory direction
2. Be internally consistent with the day_offset (events at that point in the contract)
3. Vary realistically — sentiment drifts within the trajectory; not every call sounds the same
4. For champion-departure archetypes: clearly reflect the inflection at the departure day

Return a JSON array of {len(calls_skeleton)} objects, in the order given. Each object matches this schema exactly:

{CALL_SCHEMA}

Output ONLY the JSON array. No preamble. No commentary. No markdown fences."""


# ─────────────────────────────────────────────────────────────────────
# API + parsing
# ─────────────────────────────────────────────────────────────────────

def call_anthropic(prompt: str, max_tokens: int = 4096) -> str:
    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def parse_calls(text: str, expected_count: int) -> list[dict]:
    """Parse LLM JSON response, tolerating markdown fences and minor formatting issues."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")
    if len(data) != expected_count:
        # Tolerate count mismatch — truncate or pad
        if len(data) > expected_count:
            data = data[:expected_count]
        else:
            sys.stderr.write(f"WARN: expected {expected_count} calls, got {len(data)}\n")
    return data


# ─────────────────────────────────────────────────────────────────────
# Per-call assembly + sequence-aware fields
# ─────────────────────────────────────────────────────────────────────

def compute_conv_intelligence_score(call: dict) -> int:
    """AGT-407 spec: 0-3 from next_step_committed + positive sentiment + no showstopper."""
    score = 0
    if call.get("next_step_committed"):
        score += 1
    if call.get("overall_sentiment") == "positive":
        score += 1
    if not call.get("unaddressed_showstopper"):
        score += 1
    return score


def assemble_call_record(call_llm: dict, account_id: str, skeleton: dict) -> dict:
    return {
        "conv_intelligence_id": str(uuid.uuid4()),
        "account_id": account_id,
        "opportunity_id": None,
        "call_date": skeleton["call_date"].isoformat() + "Z",
        "call_owner_role": skeleton["owner_role"],
        "duration_minutes": call_llm.get("duration_minutes", 30),
        "transcript_summary": call_llm.get("transcript_summary", ""),
        "overall_sentiment": call_llm.get("overall_sentiment", "neutral"),
        "prospect_sentiment": call_llm.get("prospect_sentiment", "neutral"),
        "rep_sentiment": call_llm.get("rep_sentiment", "neutral"),
        "sentiment_drivers": call_llm.get("sentiment_drivers", []),
        "next_steps": call_llm.get("next_steps", []),
        "next_step_committed": call_llm.get("next_step_committed", False),
        "missing_next_step_flag": call_llm.get("missing_next_step_flag", False),
        "competitors_mentioned": call_llm.get("competitors_mentioned", []),
        "new_competitor_flag": call_llm.get("new_competitor_flag", False),
        "objections_raised": call_llm.get("objections_raised", []),
        "unaddressed_showstopper": call_llm.get("unaddressed_showstopper", False),
        "conv_intelligence_score": compute_conv_intelligence_score(call_llm),
        "sentiment_trajectory": None,    # filled in by fill_sentiment_trajectory
        "created_at": (skeleton["call_date"] + timedelta(hours=1)).isoformat() + "Z",
    }


def fill_sentiment_trajectory(calls: list[dict]) -> list[dict]:
    """Compute trailing-3-call sentiment trajectory across the sequence."""
    sent_score = {"negative": -1, "neutral": 0, "positive": 1}
    for i, call in enumerate(calls):
        if i < 2:
            call["sentiment_trajectory"] = "stable"
            continue
        window = [sent_score.get(c["overall_sentiment"], 0) for c in calls[max(0, i-2):i+1]]
        delta = window[-1] - window[0]
        if delta > 0.5:
            call["sentiment_trajectory"] = "improving"
        elif delta < -0.5:
            call["sentiment_trajectory"] = "declining"
        else:
            call["sentiment_trajectory"] = "stable"
    return calls


# ─────────────────────────────────────────────────────────────────────
# Per-account orchestration
# ─────────────────────────────────────────────────────────────────────

def generate_for_account(corpus_file: str, base_seed: int,
                         force: bool = False) -> int | None:
    """Generate ConvIntelligence calls for one account. Cache by account_id."""
    with open(corpus_file) as f:
        corpus = json.load(f)

    account_id = corpus["account"]["account_id"]
    archetype_key = corpus["archetype_key"]
    archetype = ARCHETYPES[archetype_key]
    profile = archetype.conversation

    if "conversation_intelligence_log" in corpus and not force:
        return None

    cache_path = CACHE_DIR / f"{account_id}.json"

    if cache_path.exists() and not force:
        with cache_path.open() as f:
            calls = json.load(f)
    else:
        contract_start = datetime.fromisoformat(corpus["account"]["contract_start_date"])
        contract_age = corpus["account"]["contract_age_days_at_corpus_gen"]
        # Per-account RNG seed: deterministic across runs for a given account
        rng = random.Random(base_seed + (hash(account_id) % 100000))

        n = n_calls_for_account(profile, contract_age)
        call_dates = distribute_call_dates(
            n, contract_start, contract_age, profile.champion_departure_day, rng,
        )

        skeletons: list[dict] = []
        for cd in call_dates:
            day_offset = (cd - contract_start).days
            role = assign_call_role(day_offset, contract_age, archetype_key, rng)
            skeletons.append({
                "call_date": cd,
                "day_offset": day_offset,
                "owner_role": role,
            })

        prompt = build_prompt(corpus["account"], archetype, profile, skeletons)

        try:
            response_text = call_anthropic(prompt)
            llm_calls = parse_calls(response_text, n)
        except Exception as e:
            sys.stderr.write(f"  ERROR for {corpus['account']['company_name']}: {e}\n")
            return None

        # Fill in any LLM-output gaps if count was short
        while len(llm_calls) < n:
            llm_calls.append({})

        calls = [
            assemble_call_record(llm_call, account_id, skel)
            for skel, llm_call in zip(skeletons, llm_calls)
        ]
        calls = fill_sentiment_trajectory(calls)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w") as f:
            json.dump(calls, f, indent=2, default=str)

    # Append to corpus
    corpus["conversation_intelligence_log"] = calls
    corpus.setdefault("summary", {})
    corpus["summary"]["call_count"] = len(calls)
    role_counts: dict[str, int] = {}
    for c in calls:
        role = c["call_owner_role"]
        role_counts[role] = role_counts.get(role, 0) + 1
    corpus["summary"]["call_count_by_role"] = role_counts

    with open(corpus_file, "w") as f:
        json.dump(corpus, f, indent=2, default=str)

    return len(calls)


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--corpus", type=str, default="corpus")
    parser.add_argument("--force", action="store_true",
                        help="regenerate even when conversation log already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of accounts processed (testing)")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write(
            "ERROR: ANTHROPIC_API_KEY not set.\n"
            "Set it in your environment before running:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
        )
        raise SystemExit(1)

    files = sorted(glob.glob(f"{args.corpus}/*.json"))
    files = [f for f in files if "ground_truth" not in f]
    if args.limit:
        files = files[:args.limit]

    print(f"Processing {len(files)} accounts using model: {MODEL}")
    print()

    total_calls = 0
    skipped = 0

    for i, f in enumerate(files):
        result = generate_for_account(f, args.seed, force=args.force)
        if result is None:
            skipped += 1
            print(f"  [{i+1}/{len(files)}] {Path(f).name}: skipped (existing or error)")
        else:
            total_calls += result
            print(f"  [{i+1}/{len(files)}] {Path(f).name}: {result} calls")
        time.sleep(0.5)   # polite to API

    print()
    print(f"Done. Generated {total_calls} call summaries across {len(files) - skipped} accounts.")
    print(f"  Cache: {CACHE_DIR}/")
    print(f"  Skipped (already had calls): {skipped}")


if __name__ == "__main__":
    main()
