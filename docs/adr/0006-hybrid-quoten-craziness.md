# ADR 0006: Hybrid-Quoten-Craziness für „Verrückte Tipps"

**Datum:** 2026-06-28
**Status:** Akzeptiert

> **Update (ADR 0007):** Die hier erwähnte Einschränkung „echte Quoten nur forward-only,
> kein Backfill" gilt nicht mehr — die Quoten wurden direkt aus Kicktipp rückwirkend
> nachgefüllt (68/68 Spiele). Die Quoten-basierte Craziness greift damit für alle bereits
> gespielten Spiele, nicht erst für künftige. Der Hybrid-Fallback bleibt für Spiele ohne Quote.

## Kontext

Der Dashboard-Bereich „Verrückte Tipps" bewertet bisher exakte Treffer und Fehlschüsse
*gegen das Feld* (Tippkreis als implizite Quote). Seit 2026-06-28 werden echte
Buchmacher-Quoten (1/X/2) in `data/odds_history.jsonl` mitgeschnitten (ADR 0004).

Problem: Die Quoten werden nur **forward-only** erfasst (Kicktipp zeigt Quoten nur
pre-Kickoff). Für alle bereits beendeten Spiele liegen keine Quoten vor und sind nicht
nachträglich beschaffbar. Eine reine Quoten-Craziness würde deshalb anfangs fast
alle Spiele auf den Fallback verweisen.

## Entscheidung

**Hybrid-Ansatz:** Beide Craziness-Dimensionen auf einer gemeinsamen ~0..2-Skala.

- **Wo Quoten vorliegen** (Join `community_tips` × `odds_history` über
  `(spieltag_index, home, away)`): Quoten-basierte Craziness.
  - Treffer: `tend_unlikely = 1 - p(Ergebnis-Tendenz)` (Außenseiter traf = hoch)
  - Miss: `boldness = p(getippte Tendenz)` (klarer Favorit verlor = peinlich)
  - Badge im Frontend: `Außenseiter · Quote X.X` / `Favorit verlor · Quote X.X`
- **Wo keine Quoten vorliegen** (alle bisherigen Spiele): Feld-Fallback.
  - Treffer: `tend_unlikely = (n - n_tend) / n`
  - Miss: `boldness = (n - n_tend) / n`
  - Badge im Frontend: `nur X/12 exakt` / `X/12 Tendenz`

Gemeinsame Formel:
```
Treffer: craziness = tend_unlikely + (n - n_exact) / n
Miss:    craziness = boldness + min(error, 6) / 6
```

Die Scoring-Logik ist in `_score_crazy_row()` extrahiert (testbar ohne Datei-I/O).

## Begründung

- **Kein Backfill** möglich → Forward-only-Daten erfordern Hybrid statt reiner
  Quoten-Metrik.
- **Vergleichbare Skala**: Beide Pfade liefern ~0..2, deshalb gemeinsam sortierbar
  und im selben Ranking mischbar.
- **Quoten sind genauer**: Sobald Spiele mit erfassten Quoten beendet sind, wertet
  das System echte Marktwahrscheinlichkeiten aus (Overround-normiert), nicht nur
  das Verhalten der 12 Tipper.
- **Einfachheit**: Keine neuen Abhängigkeiten, keine Datenbank. Join zur Laufzeit
  in `build_crazy()`.

## Konsequenzen

- Die Hybrid-Formel greift sichtbar erst, wenn Spiele **nach 2026-06-28** beendet
  sind und Quoten in `odds_history.jsonl` stehen (Join nicht leer).
- Die neue normalisierte Feld-Formel weicht leicht von der früheren unnormierten ab:
  Bei unterschiedlichen Spieleranzahlen (n=11 vs n=12) ändert sich die Gewichtung.
  Die Top-Karte für Treffer (Japan vs Schweden) bleibt dieselbe; bei Fehlschüssen
  wird Bubukiller's 6:0-Tipp auf das 0:0 von Spanien vs Kap Verde korrekt zur
  craziness=2.0 (Maximum) — beides Dimensionen voll ausgeschöpft.
- `tracking.py`, `odds_history.py` und das Scoring bleiben unverändert (nur
  `build_crazy` + `crazyCard`).
