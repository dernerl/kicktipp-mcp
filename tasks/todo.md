# Todo: Localhost-Dashboard für Tipp-Ergebnisse

Lokale Seite, die Tipp-Ergebnisse visualisiert: Positionsverlauf der Community
über die Spieltage (Schieberegler), farbliche Hervorhebung "verrückter" Tipps,
persönlicher Bereich mit allen eigenen/Claude-Tipps + ob sie eingetroffen sind.

## Entscheidungen (bestätigt)
- Positions-Slider = **echter Community-Rang aller 12 Spieler über die Spieltage**,
  rückwirkend rekonstruiert aus `tippuebersicht?spieltagIndex=N` (Tabelle `id="ranking"`,
  Spalten Pos + P = kumulierte Position/Punkte). Verifiziert gegen Gesamtstand.
- Serving: **stdlib `http.server`**, keine neuen Dependencies, Vanilla-JS/SVG-Frontend.
- Bot-Run-Pfad bleibt unangetastet (rein additiv).

## Aufgaben
- [x] `kicktipp.py`: additive `StandingRow` + `parse_spieltag_standings()` + `fetch_standings_history()`
- [x] `ranking_history.py`: rekonstruiert `data/ranking_history.jsonl` (Spieltag × Spieler × Rang/Punkte)
- [x] `logparse.py`: parst launchd-Log → LLM-Begründungen je Match + Standings-Timeline
- [x] `dashboard.py`: stdlib-Server; `/` → HTML, `/api/data` → aggregiertes JSON, `/api/refresh`
- [x] `web/dashboard.html`: A) Positionsverlauf (Bump-Chart + Spieltag-Slider/Play),
      B) Verrückte Tipps (craziness-Score, farbcodiert), C) Persönlicher Bereich (Tipps + "Warum?")
- [x] README-Abschnitt + ADRs (0002 retroaktive Rekonstruktion, 0003 stdlib statt Framework)
- [x] Verifikation: Daten gegen Gesamtstand geprüft, JS syntax + Logik gegen echte Daten geprüft

## Review

**Umgesetzt:** Lokales Dashboard unter `http://localhost:8765` (`uv run python dashboard.py`).
Datenschicht rein additiv — Bot-Run-Pfad unangetastet.

**Verifiziert:**
- Standings-Rekonstruktion: Spieltag 9 == Gesamtübersicht exakt (Zeitschieber 149 …
  dernerl 127 … Wodan 121); 108 Zeilen = 12 Spieler × 9 Spieltage, `is_self` korrekt.
- Payload: 54 Tipps (llm Ø 1.05 vs random Ø 0.88), 6 exakte Treffer, 17 Fehlschüsse,
  29 Begründungen aus dem Log.
- Frontend: JS syntaxgeprüft (node --check), Bump-Model gegen echte Daten getestet
  (alle Spieler farbig, keine Lücken).

**Nachtrag (feinere Granularität + Bonus-Toggle):**
- Positionsverlauf jetzt **pro Einzelspiel** statt pro Spieltag: Per-Spiel-Punkte
  aus den `ereignisN`-Zellen (`<sub class="p">`) geparst, match-by-match kumuliert.
  67 Steps (Step 0 = Bonusfragen). Validiert: Per-Spiel-Summe == Spieltagspunkte
  (108/108), Endstand == Gesamtübersicht.
- **Bonusfragen-Toggle**: rechnet die vor Spieltag 1 gutgeschriebenen Bonuspunkte
  ein/aus und rankt client-seitig neu. Ohne Bonus: dernerl Platz 6 statt 11
  (reine Tipp-Leistung), Führung Zeitschieber statt Josia.
- End-Label-Entzerrung gegen Überlappung bei Punktgleichheit (z.B. Jonas/Teresa).

**Nachtrag 2 (flüssige Animation + Politur):**
- Play-Animation von diskreten `setInterval`-Sprüngen (420 ms, „ruckelt") auf
  `requestAnimationFrame` mit Interpolation umgestellt — Punkte/Linien gleiten
  kontinuierlich zwischen den Schritten (verifiziert: cy interpoliert linear,
  Mitte = exakter Mittelwert). Dots sind jetzt persistente Elemente (kein
  innerHTML pro Frame).
- Linien als glatte Bézier-S-Kurven statt Polylines.
- Slider-Label rechts zeigt nur noch den Spieltag (kein Einzelspiel mehr).
- „Bonus"-x-Label entfernt (kollidierte mit ST1 am linken Rand).
- Verifikation diesmal **headless via Chrome-Screenshot** (Extension nicht
  verbunden) + node-DOM-Stub-Test der Interpolation.

**Nachtrag 3 (Verrückte Tipps community-weit):**
- `parse_spieltag_detail` parst jetzt auch den **Tipp je Match** (nicht nur die
  Punkte) → `data/community_tips.jsonl` mit allen Tipps aller 12 Spieler.
- „Verrückte Tipps" nutzt diese Quelle statt `tips_history`; keine llm/random-
  Unterscheidung mehr, Spielername wird angezeigt.
- **Wichtige Erkenntnis:** die Community nutzt **nicht** das Standard-3/2/1,
  sondern abweichende Punkte (beobachtet: Tendenz=2, Differenz=3). Daher
  Klassifikation „verrückt" über **Tipp-vs-Ergebnis** statt Punktwert. → Folge:
  die Punkte/Ø im „Persönlichen Bereich" (aus `tracking._points`, Standard-3/2/1)
  spiegeln evtl. nicht die echten Kicktipp-Punkte wider — offener Punkt.
- Verifiziert: exakte Treffer sind wirklich Tipp==Ergebnis; headless-Screenshot.

**Nachtrag 4 (Craziness „gegen das Feld"):**
- Craziness nicht mehr über Ergebnis-Wucht, sondern über den Tippkreis als Quote:
  pro Spiel n_exakt / n_tendenz-richtig gezählt. Seltener exakter Treffer auf ein
  Ergebnis, das das Feld verhaute = am verrücktesten. Badge „nur X/12 exakt".
- Pro Spiel dedupliziert (ein Card je Match) für Abwechslung.
- Verifiziert: Zeitschieber Japan 1:1 (1/12 exakt), Bubukiller Spanien 6:0→0:0.

**Offen / Einschränkung:**
- Visuelles Rendering konnte NICHT im Browser geprüft werden (Chrome-Extension nicht
  verbunden). HTML/JS ist syntaktisch und datenseitig korrekt, aber die tatsächliche
  Darstellung sollte der User einmal sichten.
- `ranking_history.jsonl` muss bei neuen Ergebnissen via „↻"-Button oder
  `uv run python ranking_history.py` aktualisiert werden (kein Auto-Update).

---

## Nachtrag 5 (Quoten: MCP-Ausgabe + forward-only Mitschnitt)

Zwei additive Features rund um die Buchmacher-Quoten (1/X/2). Tipp-/Scoring-Logik
(`tracking.py`, `strategies.py`) unangetastet. Keine neuen Dependencies. Siehe
ADR `docs/adr/0004-quoten-mitschnitt-forward-only.md`.

### Aufgaben
- [x] **Feature A** — `mcp_server.py`: `OpenMatch` um `odds_home/odds_draw/odds_away`
      (float|null, dokumentiert 1=Heim, X=Remis, 2=Auswärts) erweitert und in
      `list_open_matches()` aus `m.odds_*` befüllt; Tool-Docstring ergänzt.
- [x] **Feature B** — neue `odds_history.py` (Stil wie `tracking.py`): `record_odds()`
      schreibt Snapshots offener Spiele mit Quoten nach `data/odds_history.jsonl`,
      **Upsert pro Match** (Key = spieltag_index, home_team, away_team). Spiele ohne
      Quoten übersprungen, angepfiffene bleiben unverändert.
- [x] Verdrahtung in `main.py` nach dem Laden der Spiele, **unabhängig vom Submit**
      (auch `--dry-run`), **best-effort** (try/except, kurze Log-Zeile, nie fatal).
- [x] README: `list_open_matches` liefert Quoten; Projekt-Layout + Performance-Tracking
      um `odds_history.py` / `data/odds_history.jsonl` ergänzt.
- [x] ADR 0004 angelegt.

### Review
- `uv run python -m py_compile kicktipp.py mcp_server.py main.py odds_history.py` → OK.
- Dry-Run (`--strategy random --dry-run --max-hours-ahead 100000`): 14 offene Spiele
  mit Quoten erfasst, **nichts submitted**. `data/odds_history.jsonl` = 14 Zeilen,
  `odds_*` gefüllt (z.B. Brasilien–Japan 1.7/3.7/5.0).
- Upsert bewiesen: zweiter Lauf → weiterhin 14 Zeilen, `captured_at` aktualisiert
  (09:09:50 → 09:10:11), keine Duplikate.
- Feature A: `OpenMatch`-Objekte aus dem Tool-Pfad tragen jetzt `odds_home/draw/away`
  (13 von 31 offenen Spielen mit Quoten — die übrigen ohne Quote bzw. bereits getippt).

### Einschränkung
- Forward-only: Quoten **vor** Einführung fehlen dauerhaft (kein Backfill möglich,
  weil Kicktipp Quoten nur pre-kickoff zeigt). Upsert behält keinen Quoten-*Verlauf*
  pro Spiel, nur den letzten Stand vor Anpfiff.
