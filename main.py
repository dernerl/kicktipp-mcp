"""CLI entry point for the kicktipp-ai bot."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

from kicktipp import KicktippClient, LoginFailed, tippable_matches
from strategies import llm_tips, weighted_random_tip


def main() -> int:
    load_dotenv()

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
        page = client.fetch_tippabgabe()
    except RuntimeError as e:
        if args.debug_html:
            url = f"https://www.kicktipp.de/{community}/tippabgabe"
            resp = client.session.get(url)
            with open("debug-tippabgabe.html", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("Wrote debug-tippabgabe.html", file=sys.stderr)
        print(f"Could not parse tip page: {e}", file=sys.stderr)
        return 4

    pending = tippable_matches(page.matches)

    if args.max_hours_ahead is not None:
        cutoff = datetime.now() + timedelta(hours=args.max_hours_ahead)
        pending = [m for m in pending if m.kickoff is None or m.kickoff <= cutoff]

    print(f"Open matches: {len(page.matches)}, tippable now: {len(pending)}")
    if not pending:
        return 0

    if args.strategy == "random":
        tips = [weighted_random_tip() for _ in pending]
    else:
        print("Asking Claude for predictions (this may take a minute)...")
        tips = llm_tips(pending)

    for m, (h, a) in zip(pending, tips):
        kickoff = m.kickoff.strftime("%a %d %b %H:%M") if m.kickoff else "?"
        print(f"  [{kickoff}] {m.home_team} {h} : {a} {m.away_team}")

    if args.dry_run:
        print("--dry-run: nothing submitted")
        return 0

    tips_by_index = {m.index: tip for m, tip in zip(pending, tips)}
    client.submit_tips(page, tips_by_index)
    print(f"Submitted {len(pending)} tips.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
