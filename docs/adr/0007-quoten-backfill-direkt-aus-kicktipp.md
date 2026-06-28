# ADR 0007: Quoten-Backfill direkt aus Kicktipp (korrigiert die forward-only-Annahme)

**Date:** 2026-06-28
**Status:** Accepted — korrigiert ADR 0004 und die Backfill-Notiz in ADR 0006

---

## Context

ADR 0004 (und darauf aufbauend 0006) gingen davon aus, dass Kicktipp Buchmacher-Quoten
**nur vor Anpfiff** zeigt und sie **nie rückwirkend** abrufbar seien — deshalb „forward-only"
und „kein Backfill möglich; externe APIs als einzige historische Quelle".

Diese Annahme war **falsch.** Tatsächlich zeigt die **Tippabgabe-Seite**
(`tippabgabe?spieltagIndex=N`) die ODDSET-Quoten für **jeden** Spieltag — auch für
bereits gespielte. Die read-only Tabelle `id="tippabgabeSpiele"` enthält pro Spiel
Datum, Teams, Ergebnis und die `td.quoten`-Zelle (verifiziert: Mexiko–Südafrika
1.43 / 4.40 / 7.75). Der Grund, warum es bisher „verborgen" war: `parse_tippabgabe`
liest nur die **editierbaren** Eingabe-Formularzeilen, die es nach Anpfiff nicht mehr
gibt — die read-only Quotenzeilen wurden nie geparst.

## Decision

Wir holen die **echten** historischen Quoten direkt aus Kicktipp statt aus einer
externen API:

- `parse_tippabgabe_odds()` (in `kicktipp.py`) parst die `tippabgabeSpiele`-Tabelle
  (Teams positionsbasiert relativ zur Zeit-Zelle, Quoten via bestehendem `_extract_odds`).
- `KicktippClient.fetch_all_odds()` iteriert über alle Spieltage (Spieltag-Liste aus
  der Tippübersicht-Nav) und sammelt die Quoten.
- `odds_history.backfill_odds()` schreibt sie einmalig nach `data/odds_history.jsonl`
  (Upsert pro Match; vorhandene/forward-erfasste Zeilen bleiben erhalten; neue Zeilen
  `source: "kicktipp-backfill"`). CLI: `uv run python odds_history.py --backfill`.

Die zuvor begonnene externe Web-Scraping-Lösung (ADR-Entwurf, Agent) wurde **verworfen**
— sie hätte nur Näherungswerte anderer Buchmacher geliefert.

## Consequences

**Positiv:**
- **Exakte ODDSET-Quoten**, die die Mitspieler tatsächlich sahen — nicht Näherungen.
- Vollständig: 68/68 gespielte Community-Spiele haben jetzt eine Quote → die
  „gegen die Quote"-Verrücktheit (ADR 0006) greift **rückwirkend** für alle Spiele.
- Kein externer Dienst, kein API-Key, keine Kosten, kein Team-Namen-Mapping.

**Negativ / Trade-offs:**
- Hängt am HTML-Layout der Tippabgabe-Seite (wie der übrige Parser).
- Ein Backfill macht N+1 HTTP-Requests (Login + ein GET pro Spieltag).

**Neutral:**
- `record_odds` (forward, pro Lauf) bleibt für offene Spiele bestehen; `backfill_odds`
  ist die einmalige/ergänzende Nachfüllung und re-runnable (füllt nur fehlende Keys).
- Mittelfristig könnte der Lauf-Capture ganz auf „alle Spieltage scrapen" umgestellt
  werden (dann ist forward vs. backfill kein Unterschied mehr) — bewusst noch offen.

## Lesson

Eine Behauptung eines LLM in einem Log („fiktives Turnier") und eine unbelegte
Annahme („keine historischen Quoten") wurden zu lange als Fakt behandelt. Beide
hat erst die Realität (User-Screenshot, Live-Probe) widerlegt. Annahmen über externe
Systeme am lebenden System prüfen, bevor man Architektur darauf baut.
