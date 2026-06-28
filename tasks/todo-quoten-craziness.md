# Todo: „Verrückte Tipps" mit den Buchmacher-Quoten verbinden

**Status:** ERLEDIGT (2026-06-28) · **Erfasst:** 2026-06-28

> **Update:** Die unten genannte „forward-only / kein Backfill"-Einschränkung war falsch.
> Kicktipp zeigt die ODDSET-Quoten auf der Tippabgabe-Seite für ALLE Spieltage (auch
> gespielte). Die echten historischen Quoten wurden direkt nachgefüllt
> (`odds_history.py --backfill`, ADR 0007): **68/68 Community-Spiele mit Quote**, alle
> Crazy-Cards jetzt `odds_based` mit echten ODDSET-Quoten („Außenseiter · Quote 3.5" /
> „Favorit verlor · Quote 1.1"). Der Hybrid-Fallback (ADR 0006) bleibt für Spiele ohne Quote.

## Idee

Statt (bzw. zusätzlich zum) Tippkreis-als-Quote die **echten Buchmacher-Quoten
(1/X/2)** als Maß für Verrücktheit nutzen:

- **Wahnsinns-Treffer** = jemand hat auf den laut Quote **unwahrscheinlichen**
  Ausgang gesetzt (hohe Quote) und lag **richtig**. Außenseiter getippt und
  getroffen → maximal verrückt. Exakter Treffer auf einen Außenseiter-Score = top.
- **Komplett daneben** = jemand hat den **klaren Favoriten** (niedrige Quote)
  getippt und lag daneben (Favorit verloren) → der peinlichste Fehlschuss. Oder:
  Ergebnis war laut Quote ein krasser Schock.

→ Nicht „abstrakte Distanz zur Quote", sondern die **implizite Wahrscheinlichkeit
des getippten Ausgangs**: niedrige Wahrscheinlichkeit + richtig = verrückt.

## Mathematik (Vorschlag)

Quoten je Spiel: `odds_home (1)`, `odds_draw (X)`, `odds_away (2)`.
Implizite Wahrscheinlichkeit (über Overround normiert):

```
inv = 1/odds_home + 1/odds_draw + 1/odds_away
p(outcome) = (1/odds_outcome) / inv
```

- **Treffer-Craziness** ∝ Unwahrscheinlichkeit der **getippten & eingetroffenen
  Tendenz**: z.B. `craziness = 1 - p(getippte_tendenz)` oder direkt die Dezimalquote
  des Ausgangs (8.0 = verrückter als 1.3). Exakter Score als Tiebreaker
  (Wucht/Seltenheit wie bisher).
- **Miss-Craziness** ∝ Stärke des getippten Favoriten, der verlor: niedrige Quote
  auf den getippten (falschen) Ausgang → hohe Craziness. Plus Fehler-Magnitude.

Quoten betreffen nur die **Tendenz** (1/X/2), nicht den exakten Score → Quote
liefert die Tendenz-Dimension, Exaktheit/Wucht bleibt sekundär.

## ⚠️ Dat+en-Einschränkung (wichtig)

Echte Quoten gibt es **nur forward-only** in `data/odds_history.jsonl`
(`odds_history.py`, ab Einführung 2026-06-28). Für **vergangene** Spiele liegen
**keine** Quoten vor und sind nicht rückwirkend holbar (Kicktipp zeigt Quoten nur
pre-kickoff). → Reine Quoten-Craziness deckt anfangs fast nichts ab.

**Empfohlener Ansatz: Hybrid.**
- Wo Quoten vorliegen (Join `community_tips` × `odds_history` über
  `spieltag_index, home_team, away_team`) → Quoten-basierte Craziness, Badge z.B.
  „Quote 8.0".
- Wo keine Quoten → Fallback auf die bestehende Tippkreis-als-Quote-Metrik
  (`dashboard.build_crazy`), Badge „nur X/12 exakt".
- Beide Maße auf eine vergleichbare Skala bringen, damit gemeinsam sortierbar.

## Aufgaben
- [x] Join `community_tips.jsonl` × `odds_history.jsonl` in `dashboard.py`.
- [x] Implizite Wahrscheinlichkeit + Craziness-Formel (Treffer/Miss) implementieren.
- [x] Hybrid-Logik (Quote wenn vorhanden, sonst Tippkreis-Fallback) + einheitliche
      Skala/Sortierung (~0..2 für beide Pfade).
- [x] Frontend: Quoten-Badge auf den Karten („Außenseiter · Quote X.X" / „Favorit
      verlor · Quote X.X"), sonst weiter „nur X/12 exakt" / „X/12 Tendenz".
- [x] Entscheiden: Quoten **ergänzen** den Tippkreis-Ansatz (Hybrid, ADR 0006).
- [ ] Verifikation an echten Beispielen, sobald genug Quoten gesammelt sind.

## Offene Entscheidung
- Quoten-Metrik **ersetzt** oder **ergänzt** den Tippkreis-Ansatz? → **Ergänzt/Hybrid**
  (ADR 0006, wegen forward-only). Implementiert 2026-06-28.
- Geht es nur um Tendenz-Quoten, oder soll der exakte Score weiter mit reingewichtet
  werden? → Tendenz liefert die Quote; exact_rarity bleibt Tiebreaker-Dimension.

## Review (2026-06-28)
Implementiert. Geänderte Dateien: `dashboard.py`, `web/dashboard.html`,
`docs/adr/0006-hybrid-quoten-craziness.md`.

Verifikation:
- `py_compile` + `node --check`: OK.
- Alle aktuellen Cards `odds_based=False` (Join leer, da Quoten erst ab
  2026-06-28 erfasst werden und noch keine dieser Spiele beendet ist).
- Top-Treffer unverändert: Japan vs Schweden (Zeitschieber).
- Top-Fehlschuss: Spanien vs Kap Verde (Bubukiller 6:0 → 0:0, craziness=2.0 =
  Maximum beider Dimensionen — korrekteres Ergebnis der neuen normalisierten Formel).
- Synthetischer Test bewiesen: Außenseiter-Treffer (Quote 8.0, p≈0.12) rankt
  höher als Favoriten-Treffer (Quote 2.20, p≈0.34); großer Favorit der verlor
  (1.33, p≈0.71) rankt höher als ausgeglichener Tipp (2.10, p≈0.44).

**Hinweis:** Die Quote-basierte Craziness greift sichtbar erst, wenn Spiele mit
erfassten Quoten (ab Spieltag 11, Sechzehntelfinale 2026) beendet sind.
