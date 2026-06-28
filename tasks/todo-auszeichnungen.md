# Todo: Auszeichnungen / „Trophäenschrank" (Shooter-Style Medals)

**Status:** OFFEN (Feature vom User bestätigt 2026-06-28) · **Erfasst:** 2026-06-28

## Idee

Wie in gängigen Shooter-Games (Medals / Awards / „MVP des Spiels") für jeden
**Spieler im Tippkreis** automatisch Auszeichnungen vergeben — basierend auf seiner
Saison-Bilanz. Das Dashboard bekommt einen neuen Bereich „🏆 Auszeichnungen": ein
Raster aus Medaillen-Karten, jede mit Titel, Emoji, Gewinner und Kennzahl
(„Josia · 7 Wahnsinns-Treffer"), optional Runner-up.

Reizvoll ist der **community-weite** Blick (alle Spieler, nicht nur der Bot) — das ist
der soziale/spaßige Aspekt. Die Daten dafür liegen schon vollständig vor.

## Datenlage (alles vorhanden, keine neue Beschaffung nötig)

- **`data/community_tips.jsonl`** — pro Spieler **pro Spiel**: `home_tip/away_tip`,
  `home_goals/away_goals`, `points` (4/3/2/0), `spieltag_index`, `player`, `is_self`.
  → Das ist die Goldgrube für fast alle Awards.
- **`data/ranking_history.jsonl`** — pro Spieltag-Ende: `rank`, `points`, `player`.
  → Tabellenführung, Comeback, Konstanz.
- **`data/ranking_steps.jsonl`** — Rang-/Punkteverlauf **pro Match-Step**, inkl.
  `bonus` (Bonusfragen-Punkte). → Bonus-Held, feinere Streak-Auswertung.
- Craziness-Logik existiert bereits in `dashboard.py`
  (`_score_crazy_row` → `status` „exact"/„miss", `craziness`, `odds_based`, `p`).
  Awards sollten diese Klassifikation **wiederverwenden**, nicht duplizieren.

## Award-Katalog (Vorschlag)

Vom User explizit gewünscht: ⭐ Wahnsinns-Treffer, 🎯 meiste Tipps, 👑 Tageserfolge.
Darüber hinaus sinnvoll und aus den Daten ableitbar:

| Medaille | Titel (Vorschlag) | Kriterium | Quelle |
|---|---|---|---|
| 🃏 | **Verrückter Vogel** | meiste Wahnsinns-Treffer (exakt/Außenseiter, hohe Quote richtig) | community_tips × odds, `status=="exact"` |
| 🎯 | **Scharfschütze** | meiste exakte Treffer (Punkte == 4) | community_tips `points==4` |
| 🔫 | **Dauerfeuer** | meiste abgegebene Tipps überhaupt (Teilnahme) | community_tips Zeilen/Spieler |
| 👑 | **Spieltagskönig** | meiste Spieltagssiege (bester Punktwert eines Spieltags) | community_tips, Punkte je `spieltag_index` |
| 🥇 | **Dauergast an der Spitze** | meiste Spieltage auf Rang 1 | ranking_history `rank==1` |
| 💪 | **Eisern** | wenigste Nuller-Tipps (Quote falscher Tendenz) bei ≥N Tipps | community_tips `points==0` |
| 🤡 | **Schuss in den Ofen** | meiste „Komplett daneben" (Favorit getippt, verloren) | community_tips × odds, `status=="miss"` |
| 🎲 | **Draufgänger** | meiste Außenseiter-Tipps (gegen den Favoriten laut Quote) | odds-Join, `p(getippte_tendenz)` niedrig |
| 📈 | **Comeback-König** | größter Rang-Aufstieg über die Saison (schlechtester → bester Rang) | ranking_history |
| 🔥 | **Heißer Lauf** | längste Serie an Spieltagen mit Punkten/über Schnitt | ranking_history / steps |
| ⚡ | **Effizienz-Bestie** | höchster Punkteschnitt pro Tipp (min. N Tipps) | community_tips avg points |
| 🧠 | **Bonus-Held** | meiste Punkte aus Bonusfragen | ranking_steps `bonus` (spieltag 0) |
| ⚽ | **Torfabrik** vs. 🧱 **Beton** | höchster / niedrigster Tor-Schnitt pro Tipp | community_tips `home_tip+away_tip` |
| 🤝 | **Remis-Riecher** | meiste korrekt getippte Unentschieden | community_tips, beide diff==0 |

→ Beim Bauen ggf. auf ~8–10 „schöne" Medaillen eindampfen, nicht alle 14 zeigen.
Der Bot selbst (`is_self==true`) bekommt eigene Hervorhebung wenn er gewinnt.

## Architektur (Vorschlag — bewusst minimal, Konventionen-treu)

- **Neues Modul `awards.py`** (stdlib + bestehende Reader). Liest dieselben jsonl-
  Dateien wie `dashboard.py`, liefert eine Liste:
  ```python
  {"id": "crazy_bird", "emoji": "🃏", "title": "Verrückter Vogel",
   "desc": "Meiste Wahnsinns-Treffer",
   "winner": "Josia", "value": "7 Treffer", "is_self": False,
   "runner_up": {"player": "...", "value": "5 Treffer"}}
  ```
- **Wiederverwendung statt Duplikat:** Craziness-Klassifikation aus `dashboard.py`
  (`_score_crazy_row`/`_sign`) teilen — ggf. die Helfer in ein gemeinsames Modul
  ziehen, damit `awards.py` und `dashboard.py` dieselbe Definition nutzen. **Scoring-
  Pfad (`tracking._points`, 4/3/2/0) nicht anfassen** (siehe CLAUDE.md / ADR 0005).
- **Einbindung:** `build_payload()` um `"awards": build_awards()` erweitern.
- **Frontend:** neuer Abschnitt in `web/dashboard.html` (Vanilla JS/SVG, kein Build-
  Step) — Medaillen-Grid, Self-Cards farblich abgesetzt. Konsistent mit den
  bestehenden Sektionen (Crazy-Cards als Stil-Vorlage).
- **Keine neuen Dependencies**, kein Test-Framework — Verifikation via
  `uv run python -m py_compile awards.py dashboard.py` + Dashboard-Reload.

## Offene Design-Fragen (vor Implementierung klären)

1. **Mindest-Tipps (N)** für Schnitt-/Quoten-Awards, damit ein Spieler mit 2 Tipps
   nicht „Effizienz-Bestie" wird. Vorschlag: N = 50 % der maximal möglichen Tipps.
2. **Gleichstand:** beide nennen, alphabetisch, oder Tiebreaker (z. B. Craziness-Summe)?
3. **Zeitraum:** ganze Saison fix, oder Spieltag-Slider wie beim Bump-Chart
   (Awards „bis Spieltag X")? Vorschlag v1: ganze Saison.
4. **Negativ-Awards** (🤡 „Schuss in den Ofen") — gewünscht oder nur positive Medaillen?
   (Im Tippkreis vermutlich lustig, aber kurz abstimmen.)
5. ADR nötig? Die Award-Definitionen sind eine nicht-triviale fachliche Entscheidung
   → bei Umsetzung **ADR 0008 „Auszeichnungen-Katalog & Berechnung"** anlegen.

## Plan (in Umsetzung 2026-06-28)

Design-Fragen entschieden (Solo-Owner): N = ⌈0,5 × max. Teilnahme⌉ für Quoten-/
Schnitt-Awards · Gleichstand → alle Sieger mit „&" nennen, Runner-up = nächste
Wertgruppe (alphabetisch) · Zeitraum = ganze Saison · 1 Negativ-Award (🤡) dabei.

Katalog (9): 🃏 Verrückter Vogel · 🎯 Scharfschütze · 🔫 Dauerfeuer ·
👑 Spieltagskönig · 🥇 Dauergast an der Spitze · 💪 Eisern · ⚡ Effizienz-Bestie ·
🤝 Remis-Riecher · 🤡 Schuss in den Ofen.

- [x] Award-Katalog final festlegen
- [x] Craziness-Helfer wiederverwenden (awards.py importiert `_score_crazy_row` aus dashboard.py; build_payload importiert build_awards lazy → kein Zirkel)
- [x] `awards.py` mit `build_awards()` implementieren
- [x] `build_payload()` um `awards` erweitern
- [x] Dashboard-Sektion „🏆 Auszeichnungen" rendern (Grid, Self-Hervorhebung)
- [x] Verifikation: py_compile + Werte gegen Rohdaten plausibilisieren
- [x] ADR 0008 schreiben (`docs/adr/0008-auszeichnungen-katalog-und-berechnung.md`)

## Review (abgeschlossen 2026-06-28)

**Umgesetzt:** neues Modul `awards.py` (`build_awards()`), eingebunden via
`dashboard.build_payload()` (lazy import → kein Zyklus), neue Frontend-Sektion
„🏆 Auszeichnungen" in `web/dashboard.html` (Grid, Self-Karten gold umrandet).
9 Medaillen, Craziness-Definition aus `dashboard._score_crazy_row` wiederverwendet,
Scoring-Pfad (4/3/2/0) unangetastet. ADR 0008 angelegt.

**Verifikation:** `py_compile` (awards.py, dashboard.py) grün · `build_payload()`
liefert 9 valide, JSON-serialisierbare Karten · Werte 1:1 gegen Rohdaten geprüft
(Scharfschütze DeGaens 11×, Eisern Josia 23 Nuller, Rang-1 Josia 10× — alle korrekt)
· `node --check` des inline-JS sauber · Server-Endpunkte `/` und `/api/data` ok.
Visuelle Browser-Verifikation entfiel (Chrome-Extension nicht verbunden) — headless
verifiziert stattdessen.

**Bekannte Schwäche:** „Dauerfeuer" (meiste Tipps) ist bei voller Teilnahme
degeneriert (9er-Gleichstand). Behalten wie gewünscht; Frontend kürzt zu „N geteilt".

**Offen / Ideen für v2:** Spieltag-Slider („Awards bis Spieltag X"), Award-Historie,
ggf. gemeinsames `craziness.py` falls die Kopplung an Dashboard-Helfer wächst.
