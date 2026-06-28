# ADR 0002: Positionsverlauf retroaktiv aus per-Spieltag-Tippübersicht rekonstruieren

**Date:** 2026-06-27
**Status:** Accepted

---

## Context

Für das lokale Ergebnis-Dashboard soll ein Positionsverlauf gezeigt werden:
"wer stand wann auf welchem Platz" — alle 12 Community-Mitglieder über die
Spieltage hinweg, scrubbar per Schieberegler.

Das Problem: Kicktipp speichert keinen historischen Tabellenstand. Persistiert
wird im Projekt nur der *eigene* Tipp-Verlauf (`data/tips_history.jsonl`) und im
launchd-Log der *eigene* Rang zu Laufzeitpunkten (sparse, 8 Datenpunkte). Den
vollen 12er-Tabellenverlauf gibt es nirgends gespeichert.

Geprüfte Datenquellen am lebenden System:
- `gesamtuebersicht` liefert nur den **aktuellen** Gesamtstand. Der Parameter
  `spieltagIndex` wird dort **ignoriert** (Probe: Stand für idx 3/5/9 identisch).
- `tippuebersicht?spieltagIndex=N` enthält die Tabelle `id="ranking"` mit den
  Spalten `Pos | +/- | Name | <pro Match> | P`. Verifiziert: `Pos` und `P` sind
  bereits **kumuliert** (Stand *nach* Spieltag N), nicht spieltagsweise. Die
  rekonstruierten Stände konvergieren exakt gegen den Gesamtstand
  (z.B. dernerl 127 Pkt, Platz 11 @ Spieltag 9 == Gesamtübersicht).

## Decision

Wir rekonstruieren den Positionsverlauf **rückwirkend** durch Scrapen jeder
abgeschlossenen `tippuebersicht?spieltagIndex=N`-Seite. Statt nur die kumulierte
`Pos`/`P` je Spieltag zu nehmen, parsen wir die **Punkte pro Einzelspiel** je
Spieler (`<td class="… ereignisN">2:0<sub class="p">2</sub></td>` — Tipp + Punkte,
fehlendes `<sub>` = 0) sowie die Gesamtpunkte (`parse_spieltag_detail` /
`fetch_spieltag_details` in `kicktipp.py`).

`ranking_history.py` baut daraus zwei Dateien (re-runnable, on-demand via CLI
oder „↻"-Button):
- `ranking_history.jsonl` — Stand nach jedem Spieltag (für „aktueller Platz").
- `ranking_steps.jsonl` — Stand nach **jedem einzelnen Spiel** (Timeline), plus
  ein Step 0 für die Bonusfragen.

**Bonuspunkte:** verifiziert wurde, dass `Gesamtpunkte = Bonus + Σ Spielpunkte`
und der Bonus komplett vor Spieltag 1 gutgeschrieben wird (danach konstant). Der
Bonus wird daher einmalig aus Spieltag 1 (`total − Σ per_match`) zurückgerechnet
und als Startbasis verwendet; das Dashboard kann ihn per Toggle ein-/ausrechnen.

Der Bot-Run-Pfad bleibt **unangetastet** (rein additive Methoden).

## Consequences

**Positiv:**
- Voller, historisch korrekter 12er-Verlauf ab Spieltag 1 — keine Datenlücke,
  obwohl nie etwas mitgeloggt wurde.
- Keine Änderung am Bot/launchd-Lauf; Feature ist additiv und reversibel.
- Jederzeit reproduzierbar/aktualisierbar aus der Quelle.

**Negativ / Trade-offs:**
- Abhängig vom HTML-Layout der Tippübersicht (Spalte `Name` über Header
  ermittelt, Fallback Index 2) — bricht bei Layout-Änderung wie der restliche
  Parser auch.
- Ein Scrape macht N HTTP-Requests (ein Login + ein GET pro Spieltag).

**Neutral:**
- `is_self` wird über die `treffer`-CSS-Klasse der Zeile erkannt (wie
  `parse_ranking`).
- Nur Spieltage mit mindestens einem Endergebnis werden aufgenommen
  (`_spieltag_has_results`).

## Considered Alternatives

| Option | Bewertet als |
|--------|--------------|
| Vorwärts-Snapshot bei jedem Bot-Lauf in neue JSONL | Berührt den Run-Pfad; füllt sich erst ab jetzt, kann Vergangenheit nicht nachholen |
| `gesamtuebersicht?spieltagIndex=N` | Untauglich — Parameter wird ignoriert, liefert immer Gesamtstand |
| Eigenen Rang aus dem Log (8 Punkte) | Nur eigene Linie, keine Mitspieler; zu sparse |
| Kumulieren aus `tips_history` | Nur eigene Punkte bekannt, nicht die der 11 anderen |
| Granularität nur pro Spieltag (`Pos`/`P`-Spalten) | Funktioniert, aber Slider springt nur spieltagweise; innerhalb eines Spieltags ändert sich die Tabelle nach jedem Spiel — daher Per-Spiel-Schritte aus den `ereignisN`-Punkten |
