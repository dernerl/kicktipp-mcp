# ADR 0005: Abweichendes Punktesystem 4/3/2/0 — Entdeckung und Korrektur

**Date:** 2026-06-28
**Status:** Accepted

---

## Context

`tracking._points` berechnete Punkte nach dem **Standard-Kicktipp-Schema 3/2/1/0**
(exakt = 3, richtige Tordifferenz = 2, richtige Tendenz = 1, falsche Tendenz = 0).
Die Tipprunde „wm-tipp-von-mischa" verwendet jedoch ein **abweichendes Schema**,
das erst durch Analyse der echten Zellenpunkte in `data/community_tips.jsonl`
(Feld `points`, direkt aus `<sub class="p">` geparst) identifiziert wurde.

**Belegtes Schema** (Häufigkeitsanalyse über alle Einträge in community_tips.jsonl):

| Kategorie | Punkte | Häufigkeit |
|-----------|:------:|:----------:|
| Exakt (Tipp == Ergebnis) | 4 | 85× → immer 4 |
| Richtige Tordifferenz, kein Remis | 3 | 87× → immer 3 |
| Richtige Tendenz (Differenz falsch oder Remis) | 2 | 346× → immer 2 |
| Falsche Tendenz | 0 | 294× → immer 0 |

Kritischer Sonderfall: Ein nicht-exaktes Remis (z.B. Tipp 1:1, Ergebnis 3:3)
hat Tordifferenz 0 auf beiden Seiten — Tordifferenz ist trivial korrekt, aber
das Remis wird dennoch nur mit **2 Punkten** (Tendenz) statt 3 bewertet. Das ist
die beobachtete Regel in den echten Daten.

Das abweichende Schema verfälschte:
- Die `points`-Werte in `data/tips_history.jsonl` (zu niedrig, falsches Schema)
- Den `status`-Wert in `dashboard.py → _enrich_tip` (abgeleitet aus Punktwert,
  damit schemaabhängig und für ein nicht-exaktes Remis falsch: `"diff"` statt
  `"tendency"`)
- Die Strategy-Averages (llm/random) im Dashboard und im launchd-Log

---

## Decision

### 1. `tracking._points` auf 4/3/2/0 + Remis-Sonderfall umgestellt

```python
def _points(h_tip, a_tip, h_res, a_res):
    if h_tip == h_res and a_tip == a_res:
        return 4                                   # exakt
    diff_tip, diff_res = h_tip - a_tip, h_res - a_res
    tend_tip = (diff_tip > 0) - (diff_tip < 0)
    tend_res = (diff_res > 0) - (diff_res < 0)
    if tend_tip != tend_res:
        return 0                                   # falsche Tendenz
    return 3 if (diff_tip == diff_res and diff_res != 0) else 2
```

Verifiziert: 68/68 `is_self`-Tipps aus `community_tips.jsonl` stimmen 100 % mit
den echten Kicktipp-Punkten überein.

### 2. `dashboard._enrich_tip` auf scoring-unabhängige Status-Klassifikation umgestellt

`status` wird jetzt direkt aus Tipp vs. Ergebnis berechnet — nicht mehr aus dem
Punktwert. Damit bleibt er korrekt unabhängig vom Punkteschema:

- `"exact"` — Tipp == Ergebnis
- `"diff"` — richtige Tendenz, richtige Tordifferenz, kein Remis
- `"tendency"` — richtige Tendenz, falsche Differenz oder Remis
- `"miss"` — falsche Tendenz
- `"open"` — kein Ergebnis

Ein nicht-exaktes Remis ergibt jetzt korrekt `"tendency"` (vorher `"diff"`).

### 3. Historische Punkte neu berechnet (Migration `tips_history.jsonl`)

Einmalige Migration aller 54 Einträge mit vorhandenen Ergebnissen; Backup unter
`data/tips_history.jsonl.bak`. Ergebnis: 33 Einträge geändert, Punktsumme
56 → 89 (korrekt, da exakt 4 statt 3, Differenz 3 statt 2).

---

## Alternatives Considered

**Punkte direkt aus Live-Seite übernehmen** — `community_tips.jsonl` enthält
bereits die echten Kicktipp-Punkte je Tipp-Zelle. Statt `_points` nachzurechnen
könnte man die eigenen Punkte aus dieser Quelle übernehmen. Vorteil: immun gegen
zukünftige Schema-Abweichungen. Nachteil: erfordert regelmäßigen Abgleich und
eine Zuordnung der `community_tips`-Zeilen auf `tips_history`-Einträge (verschiedene
Quellen mit leicht unterschiedlichen Match-Labeln). Verworfen für jetzt — die
korrigierte `_points`-Funktion ist einfacher und durch 100%-Übereinstimmung
verifiziert. Die Alternative bleibt als Robustisierungsmaßnahme offen.

---

## Consequences

- `tracking._points` liefert ab sofort die richtigen Punkte für neue Tipps.
- `update_scores()` füllt `points == null`-Einträge korrekt; ältere Einträge
  wurden einmalig per Migration korrigiert.
- Dashboard-`status` und Strategy-Averages sind jetzt konsistent mit den echten
  Kicktipp-Punkten.
- `README.md` Performance-Tracking-Abschnitt korrigiert (4/3/2/0 statt 3/2/1).
