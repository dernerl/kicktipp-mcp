"""CLI entry point for the kicktipp-ai bot."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

from kicktipp import (
    KicktippClient,
    LoginFailed,
    assign_global_indices,
    editable_matches,
    tippable_matches,
)
from odds_history import record_odds
from strategies import llm_tips, weighted_random_tip
from tracking import record_tips, update_scores


def main() -> int:
    load_dotenv()

    print(f"\n=== kicktipp-ai run {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    parser = argparse.ArgumentParser(description="Automated kicktipp bot")
    parser.add_argument(
        "--strategy",
        choices=["random", "llm"],
        default="random",
        help="random = weighted Poisson; llm = Claude with web search",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print tips without submitting")
    parser.add_argument(
        "--max-hours-ahead",
        type=int,
        default=None,
        help="Only tip matches starting within this many hours from now",
    )
    parser.add_argument(
        "--community",
        default=None,
        help="Override KICKTIPP_COMMUNITY from the environment",
    )
    parser.add_argument(
        "--debug-html",
        action="store_true",
        help="On parse failure, dump the tippabgabe HTML to debug-tippabgabe.html",
    )
    args = parser.parse_args()

    email = os.environ.get("KICKTIPP_EMAIL")
    password = os.environ.get("KICKTIPP_PASSWORD")
    community = args.community or os.environ.get("KICKTIPP_COMMUNITY")

    missing = [
        name
        for name, val in (
            ("KICKTIPP_EMAIL", email),
            ("KICKTIPP_PASSWORD", password),
            ("KICKTIPP_COMMUNITY", community),
        )
        if not val
    ]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}. Copy .env.example to .env.", file=sys.stderr)
        return 2

    client = KicktippClient(email, password, community)
    try:
        client.login()
    except LoginFailed as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 3

    try:
        past_results = client.fetch_past_results()
    except requests.RequestException as e:
        # Don't let a transient network hiccup here block tip submission below -
        # missing a tip deadline is worse than a missed score-tracking update.
        print(f"Could not fetch past results, skipping score tracking this run: {e}", file=sys.stderr)
        past_results = []

    if past_results:
        score_summary = update_scores(past_results)
        if score_summary.get("newly_scored"):
            print(f"Scored {score_summary['newly_scored']} newly completed match(es).")
        if score_summary.get("total_matches"):
            for strat, s in score_summary["by_strategy"].items():
                avg = s["points"] / s["matches"]
                print(f"  [{strat}] {s['points']} pts / {s['matches']} matches (avg {avg:.2f})")

    try:
        pages = client.fetch_all_open()
    except RuntimeError as e:
        if args.debug_html:
            url = f"https://www.kicktipp.de/{community}/tippabgabe"
            resp = client.session.get(url)
            with open("debug-tippabgabe.html", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("Wrote debug-tippabgabe.html", file=sys.stderr)
        print(f"Could not parse tip page: {e}", file=sys.stderr)
        return 4

    assign_global_indices(pages)

    # Snapshot bookmaker odds for still-open matches before anything else.
    # Odds only exist pre-kickoff and can't be fetched retroactively, so we
    # capture them on every run (independent of --dry-run — recording odds is
    # not submitting a tip). Best-effort: never let this abort the bot run.
    try:
        open_with_odds = [m for page in pages for m in editable_matches(page.matches)]
        captured = record_odds(open_with_odds)
        if captured:
            print(f"Captured odds for {captured} open match(es) -> data/odds_history.jsonl")
    except Exception as e:  # noqa: BLE001 - odds capture must never break the run
        print(f"Odds snapshot skipped (non-fatal): {e}", file=sys.stderr)

    # Kicktipp's tippabgabe page defaults to whichever Spieltag it considers
    # "current" — which only advances once that Spieltag is fully played,
    # not once it's fully tipped. fetch_all_open() instead walks every
    # Spieltag link so the next one is already visible as soon as it has
    # untipped matches, even while the current one is still pending results.
    all_open = [m for page in pages for m in tippable_matches(page.matches)]
    match_to_page = {m.index: page for page in pages for m in page.matches}

    pending = all_open
    if args.max_hours_ahead is not None:
        cutoff = datetime.now() + timedelta(hours=args.max_hours_ahead)
        pending = [m for m in pending if m.kickoff is None or m.kickoff <= cutoff]

    print(
        f"Open matches: {len(all_open)} across {len(pages)} Spieltag(e), "
        f"tippable now: {len(pending)}"
    )
    if not pending:
        return 0

    if args.strategy == "random":
        tips = [weighted_random_tip() for _ in pending]
    else:
        print(f"Using {len(past_results)} completed matches as tournament context...")
        ranking = client.fetch_ranking()
        self_entry = next((e for e in ranking if e.is_self), None)
        if self_entry:
            print(f"  Standing: rank {self_entry.rank}/{len(ranking)}, {self_entry.points} pts.")
        print("Asking Claude for predictions (this may take a minute)...")
        tips = llm_tips(pending, past_results=past_results, ranking=ranking)

    for m, (h, a) in zip(pending, tips):
        kickoff = m.kickoff.strftime("%a %d %b %H:%M") if m.kickoff else "?"
        print(f"  [{kickoff}] {m.home_team} {h} : {a} {m.away_team}")

    if args.dry_run:
        print("--dry-run: nothing submitted")
        return 0

    by_page: dict[int, dict[int, tuple[int, int]]] = {}
    for m, tip in zip(pending, tips):
        page = match_to_page[m.index]
        by_page.setdefault(page.spieltag_index, {})[m.index] = tip

    page_by_st = {p.spieltag_index: p for p in pages}
    for st_idx, tips_map in sorted(by_page.items()):
        client.submit_tips(page_by_st[st_idx], tips_map)

    record_tips(pending, tips, args.strategy)
    print(f"Submitted {len(pending)} tips.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
