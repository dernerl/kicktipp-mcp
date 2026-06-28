# ADR 0008: Auszeichnungen-Katalog & Berechnung („Trophäenschrank")

**Date:** 2026-06-28
**Status:** Accepted

---

## Context

Das Dashboard zeigte bisher Bot-zentrierte Sichten (Positionsverlauf, Verrückte
Tipps, persönlicher Bereich). Der soziale Reiz im Tippkreis ist aber der
**community-weite** Blick: Wer ist über die Saison wie aufgefallen? Gewünscht war
ein „Trophäenschrank" im Shooter-Stil — automatisch vergebene Medaillen pro Spieler
auf Basis der Saison-Bilanz.

Die Daten liegen vollständig vor (`community_tips.jsonl` mit Tipp, Ergebnis und
`points` je Spieler/Spiel; `ranking_history.jsonl` mit Rang je Spieltag;
`odds_history.jsonl` mit 1/X/2-Quoten). Keine neue Beschaffung nötig.

Zwei fachliche Festlegungen waren nicht-trivial: **welche** Awards (aus einem
14er-Vorschlag) und **wie** „Wahnsinns-Treffer" bzw. „Schuss in den Ofen" gemessen
werden, ohne eine zweite, von der Crazy-Tips-Sektion abweichende Definition zu
schaffen.

## Decision

**Neues Modul `awards.py`** mit `build_awards() -> list[dict]`, eingebunden über
`dashboard.build_payload()` (lazy import bricht den Zyklus, da `awards` die
Dashboard-Helfer wiederverwendet). Neue Frontend-Sektion „🏆 Auszeichnungen"
(Vanilla-JS-Grid, Self-Karten gold umrandet).

**Wiederverwendung statt Duplikat:** Die Craziness-Klassifikation
(`dashboard._score_crazy_row`, 0..2-Skala) wird direkt importiert. „Verrückter
Vogel" = exakte Treffer mit `craziness ≥ 1.0` (Status `exact`), „Schuss in den
Ofen" = Fehltipps mit `craziness ≥ 1.0` (Status `miss`). Damit bedeutet ein
Wahnsinns-Treffer in den Awards exakt dasselbe wie in der Crazy-Tips-Sektion.
Der **Scoring-Pfad** (`tracking._points`, 4/3/2/0) bleibt unangetastet — die
gespeicherten `points` werden 1:1 verwendet (siehe ADR 0005).

**Katalog (9 Medaillen):** 🃏 Verrückter Vogel · 🎯 Scharfschütze · 🔫 Dauerfeuer ·
👑 Spieltagskönig · 🥇 Dauergast an der Spitze · 💪 Eisern · ⚡ Effizienz-Bestie ·
🤝 Remis-Riecher · 🤡 Schuss in den Ofen (ein bewusst humorvoller Negativ-Award).

**Design-Entscheidungen (Solo-Owner-Defaults):**
- **Mindest-Teilnahme** für Quoten-/Schnitt-Awards (Eisern, Effizienz-Bestie):
  N = ⌈0,5 × maximale Tippanzahl⌉ — verhindert, dass ein Spieler mit wenigen
  Tipps „Effizienz-Bestie" wird.
- **Gleichstand:** alle Sieger werden genannt (`"A & B"`); Runner-up = nächste
  distinkte Wertgruppe (alphabetisch). Float-Werte werden auf 3 Nachkommastellen
  gerundet verglichen. Das Frontend kürzt lange Gleichstandslisten zu „N geteilt".
- **Zeitraum:** ganze Saison (kein Spieltag-Slider in v1).

## Consequences

**Positiv:**
- Eine einzige Craziness-Definition für Dashboard und Awards — keine Drift.
- Keine neuen Dependencies, kein Build-Step, kein Test-Framework (Konventionen-treu).
- Werte 1:1 gegen Rohdaten verifiziert (exakt/Nuller/Tipps/Rang-1 stimmen).

**Negativ / Trade-offs:**
- Bei nahezu vollständiger Teilnahme ist „Dauerfeuer" degeneriert (hier 9er-
  Gleichstand bei 72 Tipps). Award wurde auf expliziten Wunsch behalten; das
  Frontend fängt den langen Sieger-String ab.
- `awards.py` koppelt an interne Dashboard-Helfer (`_score_crazy_row`, `_load_odds`).
  Bewusst in Kauf genommen statt eines vorzeitigen Refactorings in ein drittes Modul;
  bei wachsender Kopplung wäre ein gemeinsames `craziness.py` der nächste Schritt.

**Verworfen:**
- Eigenständige Award-Craziness-Logik (Duplikat) — abgelehnt zugunsten der
  Wiederverwendung.
- Negativ-Awards komplett weglassen — ein einzelner (🤡) bleibt als sozialer Spaß.
