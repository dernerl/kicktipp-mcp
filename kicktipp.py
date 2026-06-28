"""HTTP client for kicktipp.de — login, fetch open matches, submit tips."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://www.kicktipp.de"
LOGIN_PAGE = f"{BASE_URL}/info/profil/login"
LOGIN_ACTION = f"{BASE_URL}/info/profil/loginaction"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class Match:
    index: int              # global sequential index across all Spieltage
    spieltag_index: int     # e.g. 1, 2, …, 15
    tippsaison_id: int
    spieltag_label: str     # e.g. "1. Spieltag", "Finale"
    home_team: str
    away_team: str
    kickoff: datetime | None
    home_input_name: str
    away_input_name: str
    already_tipped: bool
    home_score: int | None = None   # populated when already_tipped=True
    away_score: int | None = None
    # Bookmaker odds (1/X/2) scraped from the "quoten" cell, when present.
    odds_home: float | None = None
    odds_draw: float | None = None
    odds_away: float | None = None
    # Hidden fields inside the tipp cell (e.g. tippAbgegeben=true).
    # Must be included in the POST for every match in the form.
    tipp_hidden_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class TippabgabePage:
    form_action: str
    spieltag_index: int
    tippsaison_id: int
    spieltag_label: str
    hidden_fields: dict[str, str] = field(default_factory=dict)
    matches: list[Match] = field(default_factory=list)


@dataclass
class PastResult:
    spieltag_label: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    kickoff: datetime | None = None
    group: str | None = None


@dataclass
class RankingEntry:
    rank: int
    player: str
    points: int
    tendency_points: int | None = None
    difference_points: int | None = None
    exact_points: int | None = None
    is_self: bool = False


@dataclass
class PlayerSpieltag:
    """One player's row in a Spieltag's Tippübersicht.

    `total` is the cumulative Gesamtpunkte after this Spieltag; `per_match` are
    the points earned in each individual match (column order = chronological),
    which is what lets the dashboard step the standings forward match-by-match
    rather than only once per Spieltag.
    """
    player: str
    rank: int
    total: int
    is_self: bool
    per_match: list[int]                      # points per match (chronological)
    per_match_tips: list[tuple[int, int] | None]  # the (home, away) tip per match


@dataclass
class SpieltagDetail:
    spieltag_index: int
    spieltag_label: str
    matches: list[dict]          # [{home, away, home_goals, away_goals}], chronological
    players: list[PlayerSpieltag]


@dataclass
class BonusSelect:
    name: str                   # form field name of the <select>
    options: dict[str, str]     # option text → option value (excludes "not tipped")
    current: str | None         # currently selected option text, None if not tipped


@dataclass
class BonusQuestion:
    index: int                  # sequential index on the bonus page
    question: str               # e.g. "Wer wird Weltmeister?"
    deadline: datetime | None   # Tipptermin
    selects: list[BonusSelect]  # one per required answer (e.g. 4 for semifinals)
    # Hidden fields inside the question row (e.g. tippAbgegeben=true).
    hidden_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class BonusPage:
    form_action: str
    hidden_fields: dict[str, str] = field(default_factory=dict)
    questions: list[BonusQuestion] = field(default_factory=list)


class LoginFailed(Exception):
    pass


class KicktippClient:
    def __init__(self, email: str, password: str, community: str):
        self.email = email
        self.password = password
        self.community = community
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

        # requests' default adapter retries 0 times, so a single dropped
        # connection (seen in practice: kicktipp.de closing the connection
        # mid-response during fetch_past_results) crashes the whole run.
        # Retry GET/HEAD/etc. with backoff; POST (login, submit_tips) is
        # intentionally excluded since we can't tell if it was already
        # processed server-side before the connection dropped.
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def login(self) -> None:
        # Prime the session (cookies, any CSRF the login page sets)
        self.session.get(LOGIN_PAGE, timeout=15)

        resp = self.session.post(
            LOGIN_ACTION,
            data={"kennung": self.email, "passwort": self.password},
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Heuristic: after a successful login kicktipp redirects away from the
        # login URL and the response no longer contains the login form.
        if 'name="kennung"' in resp.text or "loginaction" in resp.url:
            raise LoginFailed("kicktipp rejected the credentials")

    def fetch_tippabgabe(
        self,
        spieltag_index: int | None = None,
        tippsaison_id: int | None = None,
    ) -> TippabgabePage | None:
        """Fetch a single Spieltag page.  Returns None if no tippable table found."""
        url = f"{BASE_URL}/{self.community}/tippabgabe"
        params: dict[str, str | int] = {}
        if spieltag_index is not None:
            params["spieltagIndex"] = spieltag_index
        if tippsaison_id is not None:
            params["tippsaisonId"] = tippsaison_id
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return parse_tippabgabe(resp.text, fallback_action=url)

    def fetch_all_editable(self) -> list[TippabgabePage]:
        """Return all Spieltage with at least one not-yet-started match (tipped or not).

        Use this when you need the full picture — both open and already-tipped
        matches — so that indices are consistent across list/submit/overwrite calls.
        """
        return self._fetch_all(filter_fn=editable_matches)

    def fetch_all_open(self) -> list[TippabgabePage]:
        """Return all Spieltage that have at least one tippable match."""
        return self._fetch_all(filter_fn=tippable_matches)

    def _fetch_all(self, filter_fn) -> list[TippabgabePage]:
        """Shared fetch loop — includes pages where filter_fn returns non-empty."""
        url = f"{BASE_URL}/{self.community}/tippabgabe"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        html = resp.text

        first = parse_tippabgabe(html, fallback_action=url)
        links = _parse_spieltag_links(html)

        pages: list[TippabgabePage] = []
        if first and filter_fn(first.matches):
            pages.append(first)

        seen = {first.spieltag_index} if first else set()
        for st_idx, _label, tsid in links:
            if st_idx in seen:
                continue
            seen.add(st_idx)
            page = self.fetch_tippabgabe(spieltag_index=st_idx, tippsaison_id=tsid)
            if page and filter_fn(page.matches):
                pages.append(page)

        pages.sort(key=lambda p: p.spieltag_index)
        return pages

    def fetch_past_results(self) -> list[PastResult]:
        """Fetch all completed match results from tippuebersicht pages."""
        url = f"{BASE_URL}/{self.community}/tippuebersicht"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()

        links = _parse_spieltag_links(resp.text)
        all_results: list[PastResult] = []

        for st_idx, label, tsid in links:
            r = self.session.get(
                url,
                params={"spieltagIndex": st_idx, "tippsaisonId": tsid},
                timeout=15,
            )
            r.raise_for_status()
            all_results.extend(parse_past_results(r.text, spieltag_label=label))

        return all_results

    def fetch_ranking(self) -> list[RankingEntry]:
        """Fetch the Gesamtübersicht and return the current standings."""
        url = f"{BASE_URL}/{self.community}/gesamtuebersicht"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return parse_ranking(resp.text)

    def fetch_spieltag_details(self) -> list[SpieltagDetail]:
        """Per-Spieltag breakdown for every completed Spieltag.

        Each Tippübersicht page carries, per player, both the cumulative
        Gesamtpunkte and the points earned in each individual match — enough to
        reconstruct the standings after any single match.  The Gesamtübersicht
        can't be used (its spieltagIndex param is ignored).  Future Spieltage
        without results are skipped.
        """
        url = f"{BASE_URL}/{self.community}/tippuebersicht"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()

        details: list[SpieltagDetail] = []
        for st_idx, label, tsid in _parse_spieltag_links(resp.text):
            r = self.session.get(
                url,
                params={"spieltagIndex": st_idx, "tippsaisonId": tsid},
                timeout=15,
            )
            r.raise_for_status()
            if not _spieltag_has_results(r.text):
                continue
            details.append(parse_spieltag_detail(r.text, st_idx, label))
        return details

    def fetch_all_odds(self) -> list[dict]:
        """Scrape 1/X/2 odds for every Spieltag from the Tippabgabe pages.

        Kicktipp shows the ODDSET odds on the Tippabgabe page for *all* Spieltage,
        including already-played ones, so this works retroactively.  The reliable
        Spieltag list comes from the Tippübersicht nav (the Tippabgabe nav only
        links prev/next).
        """
        links = _parse_spieltag_links(
            self.session.get(f"{BASE_URL}/{self.community}/tippuebersicht", timeout=15).text
        )
        url = f"{BASE_URL}/{self.community}/tippabgabe"
        out: list[dict] = []
        for st_idx, label, tsid in links:
            r = self.session.get(
                url, params={"spieltagIndex": st_idx, "tippsaisonId": tsid}, timeout=15
            )
            r.raise_for_status()
            out.extend(parse_tippabgabe_odds(r.text, st_idx, label))
        return out

    def fetch_bonus_page(self) -> BonusPage | None:
        """Fetch the bonus-question page.  Returns None if there are no questions."""
        url = f"{BASE_URL}/{self.community}/tippabgabe"
        resp = self.session.get(url, params={"bonus": "true"}, timeout=15)
        resp.raise_for_status()
        return parse_bonus_page(resp.text, fallback_action=url)

    def submit_bonus_tips(
        self,
        page: BonusPage,
        answers_by_index: dict[int, list[str]],
    ) -> requests.Response:
        """Submit bonus-question answers (option texts, matched per select).

        Questions not in answers_by_index keep their current selection.
        """
        data: dict[str, str] = dict(page.hidden_fields)

        # The browser sends every question's fields, so start from current state.
        for q in page.questions:
            data.update(q.hidden_fields)
            for sel in q.selects:
                current_value = sel.options.get(sel.current) if sel.current else None
                data[sel.name] = current_value or "-1"

        # Overlay the answers we're actually submitting.
        by_index = {q.index: q for q in page.questions}
        for idx, answers in answers_by_index.items():
            q = by_index.get(idx)
            if q is None:
                raise ValueError(f"no bonus question with index {idx}")
            if len(answers) != len(q.selects):
                raise ValueError(
                    f"question {idx} ({q.question!r}) needs {len(q.selects)} "
                    f"answer(s), got {len(answers)}"
                )
            for sel, answer in zip(q.selects, answers):
                value = sel.options.get(answer)
                if value is None:  # forgive case/whitespace differences
                    folded = answer.strip().casefold()
                    value = next(
                        (v for t, v in sel.options.items() if t.casefold() == folded),
                        None,
                    )
                if value is None:
                    raise ValueError(
                        f"invalid answer {answer!r} for question {idx} "
                        f"({q.question!r}); valid: {sorted(q.selects[0].options)}"
                    )
                data[sel.name] = value

        action = page.form_action
        if not action.startswith("http"):
            action = BASE_URL.rstrip("/") + "/" + action.lstrip("/")

        resp = self.session.post(action, data=data, timeout=20)
        resp.raise_for_status()
        return resp

    def submit_tips(
        self,
        page: TippabgabePage,
        tips_by_index: dict[int, tuple[int, int]],
    ) -> requests.Response:
        """Submit tips for one Spieltag page."""
        data: dict[str, str] = dict(page.hidden_fields)

        # The browser sends tippAbgegeben for EVERY match in the form.
        for match in page.matches:
            data.update(match.tipp_hidden_fields)

        # Overlay the scores we're actually submitting.
        for match in page.matches:
            if match.index not in tips_by_index:
                continue
            home, away = tips_by_index[match.index]
            data[match.home_input_name] = str(home)
            data[match.away_input_name] = str(away)

        action = page.form_action
        if not action.startswith("http"):
            action = BASE_URL.rstrip("/") + "/" + action.lstrip("/")

        resp = self.session.post(action, data=data, timeout=20)
        resp.raise_for_status()
        return resp


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def parse_tippabgabe(html: str, fallback_action: str) -> TippabgabePage | None:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="tippabgabeSpiele")
    if table is None:
        return None  # this Spieltag isn't open for tipping yet

    form = _find_enclosing_form(table) or soup.find("form")
    if form is None:
        return None

    action = form.get("action") or fallback_action
    hidden_fields = _collect_form_fields(form, exclude_table=table)

    spieltag_index = int(hidden_fields.get("spieltagIndex") or 1)
    tippsaison_id = int(hidden_fields.get("tippsaisonId") or 0)
    spieltag_label = _spieltag_label_from_links(html, spieltag_index)

    matches: list[Match] = []
    last_seen_kickoff: datetime | None = None
    data_index = 0  # filled in later by the caller when combining Spieltage

    for row in table.find_all("tr"):
        classes = row.get("class") or []

        # ── header / date rows ────────────────────────────────────────────
        # Old layout: class="rowheader"   New layout: class="label"
        if "rowheader" in classes or "label" in classes:
            last_seen_kickoff = _kickoff_from_row(row) or last_seen_kickoff
            continue

        # ── detect match row ──────────────────────────────────────────────
        # Old layout: class="datarow"
        # New layout: no class, but has a <td class="kicktipp-tippabgabe">
        tipp_cell = row.find("td", class_="kicktipp-tippabgabe")
        if "datarow" not in classes and tipp_cell is None:
            continue

        # ── kickoff time ──────────────────────────────────────────────────
        # Simultaneous kickoffs share one time cell via rowspan, so only the
        # first match row in such a pair has its own "kicktipp-time" cell —
        # the next one must inherit it via last_seen_kickoff.
        if tipp_cell is not None:
            time_cell = row.find("td", class_="kicktipp-time")
            kickoff = (
                _kickoff_from_row(time_cell) if time_cell else None
            ) or last_seen_kickoff
        else:
            kickoff = _kickoff_from_row(row) or last_seen_kickoff
        if kickoff is not None:
            last_seen_kickoff = kickoff

        # ── score inputs & per-match hidden fields ────────────────────────
        search_node = tipp_cell if tipp_cell is not None else row
        score_inputs = _find_score_inputs(search_node)
        if len(score_inputs) < 2:
            continue
        home_input, away_input = score_inputs[0], score_inputs[1]

        home_name = home_input.get("name")
        away_name = away_input.get("name")
        if not home_name or not away_name:
            continue

        tipp_hidden: dict[str, str] = {}
        if tipp_cell is not None:
            for inp in tipp_cell.find_all("input", type="hidden"):
                n = inp.get("name")
                if n:
                    tipp_hidden[n] = inp.get("value") or ""

        # ── team names ────────────────────────────────────────────────────
        if tipp_cell is not None:
            teams = _extract_teams_typed(row)
        else:
            teams = _extract_teams(row)
        if teams is None:
            continue
        home_team, away_team = teams

        home_val = (home_input.get("value") or "").strip()
        away_val = (away_input.get("value") or "").strip()
        already_tipped = bool(home_val and away_val)

        odds_home, odds_draw, odds_away = _extract_odds(row)

        home_score: int | None = None
        away_score: int | None = None
        if already_tipped:
            try:
                home_score = int(home_val)
                away_score = int(away_val)
            except ValueError:
                pass

        matches.append(
            Match(
                index=data_index,  # placeholder; reassigned by fetch_all_open
                spieltag_index=spieltag_index,
                tippsaison_id=tippsaison_id,
                spieltag_label=spieltag_label,
                home_team=home_team,
                away_team=away_team,
                kickoff=kickoff,
                home_input_name=home_name,
                away_input_name=away_name,
                already_tipped=already_tipped,
                home_score=home_score,
                away_score=away_score,
                odds_home=odds_home,
                odds_draw=odds_draw,
                odds_away=odds_away,
                tipp_hidden_fields=tipp_hidden,
            )
        )
        data_index += 1

    return TippabgabePage(
        form_action=action,
        spieltag_index=spieltag_index,
        tippsaison_id=tippsaison_id,
        spieltag_label=spieltag_label,
        hidden_fields=hidden_fields,
        matches=matches,
    )


def parse_bonus_page(html: str, fallback_action: str) -> BonusPage | None:
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="tippabgabeFragen")
    if table is None:
        return None  # no bonus questions in this Tipprunde

    form = _find_enclosing_form(table) or soup.find("form")
    if form is None:
        return None

    action = form.get("action") or fallback_action
    hidden_fields = _collect_form_fields(form, exclude_table=table)

    questions: list[BonusQuestion] = []
    for row in table.find_all("tr"):
        select_tags = row.find_all("select")
        if not select_tags:
            continue  # header row, or question already locked (rendered as text)

        deadline = _kickoff_from_row(row)
        question = _extract_question_text(row)
        if question is None:
            continue

        selects: list[BonusSelect] = []
        for tag in select_tags:
            name = tag.get("name")
            if not name:
                continue
            options: dict[str, str] = {}
            current: str | None = None
            for opt in tag.find_all("option"):
                value = opt.get("value", "")
                text = opt.get_text(strip=True)
                if value == "-1":  # the "-- Nicht getippt --" placeholder
                    continue
                options[text] = value
                if opt.has_attr("selected"):
                    current = text
            selects.append(BonusSelect(name=name, options=options, current=current))
        if not selects:
            continue

        row_hidden: dict[str, str] = {}
        for inp in row.find_all("input", type="hidden"):
            n = inp.get("name")
            if n:
                row_hidden[n] = inp.get("value") or ""

        questions.append(
            BonusQuestion(
                index=len(questions),
                question=question,
                deadline=deadline,
                selects=selects,
                hidden_fields=row_hidden,
            )
        )

    return BonusPage(form_action=action, hidden_fields=hidden_fields, questions=questions)


def parse_ranking(html: str) -> list[RankingEntry]:
    soup = BeautifulSoup(html, "html.parser")

    # Kicktipp uses id="ranking" with class="tippuebersicht ktable"
    table = (
        soup.find("table", id="ranking")
        or soup.find("table", id="rangliste")
        or soup.find("table", id="gesamtuebersicht")
    )
    if table is None:
        return []

    entries: list[RankingEntry] = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            continue

        # First cell: rank like "1." or "1"
        rank_text = tds[0].get_text(strip=True).rstrip(".")
        try:
            rank = int(rank_text)
        except ValueError:
            continue

        # Second cell: player name (may be wrapped in <a>)
        a = tds[1].find("a")
        player = a.get_text(strip=True) if a else tds[1].get_text(strip=True)

        # Last cell: total points (Gesamtpunkte)
        total_text = tds[-1].get_text(strip=True).replace(".", "").replace(",", "")
        try:
            points = int(total_text)
        except ValueError:
            continue

        # Kicktipp marks the logged-in user's own row with an extra "treffer"
        # class on the <tr> (in addition to the always-present "teilnehmer…" id).
        row_classes = row.get("class") or []
        is_self = "treffer" in row_classes

        entries.append(
            RankingEntry(rank=rank, player=player, points=points, is_self=is_self)
        )

    return entries


def _spieltag_has_results(html: str) -> bool:
    """True if the Spieltag's match table already has at least one final score."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="spielplanSpiele")
    if table is None:
        return False
    for row in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if cells and re.match(r"^\d+:\d+$", cells[-1]):
            return True
    return False


def _parse_spieltag_matches(soup: BeautifulSoup) -> list[dict]:
    """Match list (chronological) from the spielplanSpiele table."""
    matches: list[dict] = []
    table = soup.find("table", id="spielplanSpiele")
    if table is None:
        return matches
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 5:
            continue
        cells = [c.get_text(strip=True) for c in tds]
        home, away, result = cells[1], cells[2], cells[-1]
        m = re.match(r"^(\d+):(\d+)$", result)
        hg, ag = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        matches.append({"home": home, "away": away, "home_goals": hg, "away_goals": ag})
    return matches


def parse_spieltag_detail(
    html: str, spieltag_index: int, spieltag_label: str
) -> SpieltagDetail:
    """Parse a per-Spieltag Tippübersicht into match list + per-player points.

    The ranking table (id="ranking") has a column per match whose cell looks
    like ``<td class="… ereignisN">2:0<sub class="p">2</sub></td>`` — the score
    is the tip, the <sub class="p"> the points earned (absent → 0 points).  The
    Gesamtpunkte cell (class "gesamtpunkte") gives the cumulative total.
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = _parse_spieltag_matches(soup)
    n = len(matches)

    table = soup.find("table", id="ranking")
    players: list[PlayerSpieltag] = []
    if table is not None:
        for row in table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) < 3:
                continue
            rank_text = tds[0].get_text(strip=True).rstrip(".")
            if not rank_text.isdigit():
                continue

            name_cell = row.find("td", class_="mg_class") or tds[2]
            player = name_cell.get_text(strip=True)
            if not player:
                continue

            per_match = [0] * n
            per_match_tips: list[tuple[int, int] | None] = [None] * n
            for td in tds:
                for cls in (td.get("class") or []):
                    if cls.startswith("ereignis") and cls != "ereignis":
                        try:
                            i = int(cls[len("ereignis"):])
                        except ValueError:
                            continue
                        if 0 <= i < n:
                            sub = td.find("sub", class_="p")
                            txt = sub.get_text(strip=True) if sub else ""
                            per_match[i] = int(txt) if txt.isdigit() else 0
                            # the tip is the first text node of the cell ("2:0"),
                            # the points live in the trailing <sub class="p">
                            first = td.find(string=True)
                            mt = re.match(r"\s*(\d+):(\d+)", first) if first else None
                            if mt:
                                per_match_tips[i] = (int(mt.group(1)), int(mt.group(2)))

            total_cell = row.find("td", class_="gesamtpunkte")
            total_text = (total_cell or tds[-1]).get_text(strip=True).replace(".", "")
            try:
                total = int(total_text)
            except ValueError:
                continue

            is_self = "treffer" in (row.get("class") or [])
            players.append(PlayerSpieltag(
                player=player, rank=int(rank_text), total=total,
                is_self=is_self, per_match=per_match, per_match_tips=per_match_tips,
            ))

    return SpieltagDetail(
        spieltag_index=spieltag_index,
        spieltag_label=spieltag_label,
        matches=matches,
        players=players,
    )


def parse_past_results(html: str, spieltag_label: str) -> list[PastResult]:
    """Parse completed match results from a tippuebersicht page.

    Skips rows where the result is '-:-' (match not yet played).
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="spielplanSpiele")
    if table is None:
        return []

    results: list[PastResult] = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 5:
            continue
        date_text = tds[0].get_text(strip=True)
        home_team = tds[1].get_text(strip=True)
        away_team = tds[2].get_text(strip=True)
        group = tds[3].get_text(strip=True) or None
        result_text = tds[4].get_text(strip=True)

        if "-" in result_text or not result_text:
            continue

        parts = result_text.split(":")
        if len(parts) != 2:
            continue
        try:
            home_goals = int(parts[0].strip())
            away_goals = int(parts[1].strip())
        except ValueError:
            continue

        kickoff = _kickoff_from_text(date_text)

        results.append(PastResult(
            spieltag_label=spieltag_label,
            home_team=home_team,
            away_team=away_team,
            home_goals=home_goals,
            away_goals=away_goals,
            kickoff=kickoff,
            group=group,
        ))
    return results


def _kickoff_from_text(text: str) -> datetime | None:
    date_match = _DATE_RE.search(text)
    time_match = _TIME_RE.search(text)
    if not (date_match and time_match):
        return None
    day, month, year = (int(x) for x in date_match.groups())
    if year < 100:
        year += 2000
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def _extract_question_text(row: Tag) -> str | None:
    """The question is the td that holds neither the Tipptermin nor the selects."""
    for td in row.find_all("td"):
        if td.find("select") is not None:
            continue
        text = td.get_text(" ", strip=True)
        if not text or _DATE_RE.search(text):
            continue
        return text
    return None


def open_bonus_questions(questions: Iterable[BonusQuestion]) -> list[BonusQuestion]:
    """Questions whose deadline hasn't passed (or has no deadline)."""
    now = datetime.now()
    return [
        q for q in questions
        if q.deadline is None or q.deadline > now
    ]


def _spieltag_label_from_links(html: str, spieltag_index: int) -> str:
    """Find the human-readable label for the given spieltag_index in the nav links."""
    for idx, label, _tsid in _parse_spieltag_links(html):
        if idx == spieltag_index and label:
            return label
    return f"Spieltag {spieltag_index}"


def _parse_spieltag_links(html: str) -> list[tuple[int, str, int]]:
    """Return [(spieltag_index, label, tippsaison_id), …] from the nav selector.

    Skips bonus-question links (those with bonus=true in the URL).  Prefers a
    non-empty label over an empty one when the same index appears multiple times.
    """
    soup = BeautifulSoup(html, "html.parser")
    by_index: dict[int, tuple[str, int]] = {}  # spieltag_index → (label, tsid)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "spieltagIndex" not in href:
            continue
        qs = parse_qs(urlparse(href).query)
        if qs.get("bonus"):          # skip bonus-question navigation links
            continue
        try:
            idx = int(qs["spieltagIndex"][0])
            tsid = int(qs.get("tippsaisonId", ["0"])[0])
        except (KeyError, ValueError, IndexError):
            continue
        label = a.get_text(strip=True)
        existing_label = by_index.get(idx, ("", 0))[0]
        # Keep the first non-empty label we see for this index.
        if idx not in by_index or (not existing_label and label):
            by_index[idx] = (label, tsid)
    return [(idx, label, tsid) for idx, (label, tsid) in sorted(by_index.items())]


def _find_enclosing_form(node: Tag) -> Tag | None:
    parent = node.parent
    while parent is not None:
        if getattr(parent, "name", None) == "form":
            return parent
        parent = parent.parent
    return None


def _collect_form_fields(form: Tag, exclude_table: Tag) -> dict[str, str]:
    """Collect all form values outside the tippabgabe match table.

    Handles <input>, <select> (reads the selected <option>), and <textarea>.
    """
    fields: dict[str, str] = {}
    for inp in form.find_all(["input", "select", "textarea"]):
        if _is_descendant_of(inp, exclude_table):
            continue
        name = inp.get("name")
        if not name:
            continue

        if inp.name == "select":
            # Value comes from the selected <option>, not the <select> itself.
            selected_opt = inp.find("option", selected=True)
            if selected_opt is None:
                selected_opt = inp.find("option")  # fallback: first option
            fields[name] = selected_opt.get("value", "") if selected_opt else ""
            continue

        itype = (inp.get("type") or "").lower()
        if itype in ("submit", "button", "reset"):
            continue
        if itype == "checkbox" and not inp.has_attr("checked"):
            continue
        fields[name] = inp.get("value", "") or ""

    # Include the primary submit button so kicktipp recognises the request.
    submit = form.find("input", {"name": "submitbutton"}) or form.find(
        "button", {"name": "submitbutton"}
    )
    if submit is not None:
        fields["submitbutton"] = submit.get("value") or "submit"

    return fields


def _is_descendant_of(node: Tag, ancestor: Tag) -> bool:
    parent = node.parent
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.parent
    return False


def _find_score_inputs(node: Tag) -> list[Tag]:
    result: list[Tag] = []
    for inp in node.find_all("input"):
        itype = (inp.get("type") or "").lower()
        if itype in ("hidden", "submit", "button", "reset", "checkbox", "radio"):
            continue
        name = inp.get("name")
        if not name:
            continue
        result.append(inp)
    return result


def _extract_odds(row: Tag) -> tuple[float | None, float | None, float | None]:
    """Read bookmaker odds (1/X/2) from the row's "quoten" cell, if present.

    Kicktipp embeds these as affiliate links (class quoteheim/quoteremis/
    quotegast) with a nested <span class="quote-text"> holding the value.
    Present on open matches too — no need to web-search for odds.
    """
    quoten_cell = row.find("td", class_="quoten")
    if quoten_cell is None:
        return None, None, None

    def _read(cls: str) -> float | None:
        a = quoten_cell.find("a", class_=cls)
        if a is None:
            return None
        span = a.find("span", class_="quote-text")
        if span is None:
            return None
        try:
            return float(span.get_text(strip=True))
        except ValueError:
            return None

    return _read("quoteheim"), _read("quoteremis"), _read("quotegast")


def _extract_teams_typed(row: Tag) -> tuple[str, str] | None:
    """Extract teams from new-layout rows that use explicit TD classes.

    Skips td.kicktipp-time, td.quoten, td.kicktipp-tippabgabe — the remaining
    non-empty cells are the home and away team names.
    """
    SKIP = {"kicktipp-time", "quoten", "kicktipp-tippabgabe"}
    teams: list[str] = []
    for td in row.find_all("td"):
        td_classes = set(td.get("class") or [])
        if td_classes & SKIP:
            continue
        text = td.get_text(" ", strip=True)
        if text:
            teams.append(text)
    if len(teams) < 2:
        return None
    return teams[-2], teams[-1]


def parse_tippabgabe_odds(
    html: str, spieltag_index: int, spieltag_label: str
) -> list[dict]:
    """Parse the read-only odds rows of a Tippabgabe page (any Spieltag).

    Unlike `parse_tippabgabe` (which reads the editable tip-entry form — empty
    once a Spieltag has been played), this reads the always-present
    `tippabgabeSpiele` table: each row has the date, the two teams, the result
    and the ODDSET 1/X/2 odds cell.  So odds are retrievable for *every*
    Spieltag, including ones already played — Kicktipp keeps showing them.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="tippabgabeSpiele")
    out: list[dict] = []
    if table is None:
        return out

    for row in table.find_all("tr"):
        if row.find("td", class_="quoten") is None:
            continue
        oh, od, oa = _extract_odds(row)
        if oh is None and od is None and oa is None:
            continue
        tds = row.find_all("td")
        # Layout: time | home | away | result | quoten — teams sit right after
        # the time cell, which is robust against the result/quoten columns.
        time_idx = next(
            (i for i, td in enumerate(tds) if "kicktipp-time" in (td.get("class") or [])),
            None,
        )
        if time_idx is None or time_idx + 2 >= len(tds):
            continue
        home = tds[time_idx + 1].get_text(strip=True)
        away = tds[time_idx + 2].get_text(strip=True)
        if not home or not away:
            continue
        kickoff = _kickoff_from_text(tds[time_idx].get_text(strip=True))
        out.append({
            "spieltag_index": spieltag_index,
            "spieltag_label": spieltag_label,
            "home_team": home,
            "away_team": away,
            "kickoff": kickoff.isoformat() if kickoff else None,
            "odds_home": oh,
            "odds_draw": od,
            "odds_away": oa,
        })
    return out


def _extract_teams(row: Tag) -> tuple[str, str] | None:
    cells: list[str] = []
    for td in row.find_all("td"):
        inputs_in_cell = td.find_all("input")
        text = td.get_text(" ", strip=True)
        if inputs_in_cell and not text:
            continue
        if text:
            cells.append(text)

    candidates = [
        c for c in cells
        if not _TIME_RE.fullmatch(c) and not _DATE_RE.fullmatch(c) and len(c) >= 2
    ]
    if len(candidates) < 2:
        return None
    return candidates[-2], candidates[-1]


def _kickoff_from_row(row: Tag) -> datetime | None:
    text = row.get_text(" ", strip=True)
    date_match = _DATE_RE.search(text)
    time_match = _TIME_RE.search(text)
    if not (date_match and time_match):
        return None
    day, month, year = (int(x) for x in date_match.groups())
    if year < 100:
        year += 2000
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def tippable_matches(matches: Iterable[Match]) -> list[Match]:
    """Matches not yet tipped and not yet kicked off."""
    now = datetime.now()
    out = []
    for m in matches:
        if m.already_tipped:
            continue
        if m.kickoff is not None and m.kickoff <= now:
            continue
        out.append(m)
    return out


def editable_matches(matches: Iterable[Match]) -> list[Match]:
    """All matches not yet kicked off — tipped or not.  Safe to submit or overwrite."""
    now = datetime.now()
    return [
        m for m in matches
        if m.kickoff is None or m.kickoff > now
    ]


def assign_global_indices(pages: list[TippabgabePage]) -> None:
    """Assign sequential global indices to all matches across all Spieltage.

    Kicktipp's tippabgabe page only exposes one Spieltag at a time, each with
    its own 0-based match indices. Callers that work across several Spieltage
    (e.g. when the current one is fully tipped and the next is already inside
    the tipping window) need indices that stay unique across pages.
    """
    i = 0
    for page in pages:
        for m in page.matches:
            m.index = i
            i += 1
