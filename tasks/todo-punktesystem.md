# Todo: Abweichendes Punktesystem der Tipprunde korrigieren

**Status:** offen · **Priorität:** hoch (verfälscht aktuell Punkte & llm/random-Vergleich)
**Erfasst:** 2026-06-28

## Problem

Der Bot/Dashboard rechnet überall mit dem **Standard-Kicktipp-Schema 3/2/1/0**
(`tracking._points`). Die Tipprunde „wm-tipp-von-mischa" nutzt aber ein **anderes
Schema**. Dadurch stimmen die Punkte im „Persönlichen Bereich", die
`llm`-vs-`random`-Schnitte und die `[strategy] … (avg …)`-Zeilen im launchd-Log
**nicht** mit den echten Kicktipp-Punkten überein.

## Belegtes echtes Schema (aus `data/community_tips.jsonl`, echte Zellen-Punkte)

| Kategorie | Punkte | Beleg (Häufigkeit in den Daten) |
|-----------|:------:|----------------------------------|
| Exakt (Ergebnis genau) | **4** | 85× → immer 4 |
| Richtige Tordifferenz, **kein** Remis | **3** | 87× → 3 |
| Richtige Tendenz (Sieger korrekt, Differenz falsch) | **2** | 330× → 2 |
| **Remis** getippt, Remis passiert, aber falsches Ergebnis | **2** | 16× → 2 (nicht 3!) |
| Falsche Tendenz | **0** | 294× → 0 |

→ Also **4 / 3 / 2 / 0**, mit Sonderregel: ein **nicht-exaktes Remis** zählt nur
als Tendenz (**2**), nicht als Differenz — weil die „Tordifferenz" beim Remis
trivial 0 ist und keinen Differenz-Bonus gibt.

## Korrigierte `_points`-Logik (Vorschlag für `tracking.py`)

```python
def _points(h_tip, a_tip, h_res, a_res) -> int:
    if h_tip == h_res and a_tip == a_res:
        return 4                                   # exakt
    diff_tip, diff_res = h_tip - a_tip, h_res - a_res
    tend_tip = (diff_tip > 0) - (diff_tip < 0)
    tend_res = (diff_res > 0) - (diff_res < 0)
    if tend_tip != tend_res:
        return 0                                   # falsche Tendenz
    # richtige Tordifferenz nur bei Nicht-Remis = 3, sonst (inkl. Remis) = 2
    return 3 if (diff_tip == diff_res and diff_res != 0) else 2
```

## Betroffen / zu erledigen

- [ ] **Schema final gegenprüfen** an der Live-Seite (idealerweise inkl. eines
      exakten Remis-Tipps, falls in den Daten auffindbar) — `community_tips.jsonl`
      ist die Wahrheit (echte Zellen-Punkte). Optional: Schema konfigurierbar
      machen, da Communities abweichen.
- [ ] `tracking._points` auf 4/3/2/0 + Remis-Sonderfall umstellen.
- [ ] **Historische Punkte neu berechnen** in `data/tips_history.jsonl`.
      Achtung: `update_scores()` füllt nur `points == null` — für bereits
      bepunktete Einträge braucht es eine einmalige Migration (alle `points`
      neu aus Tipp+Ergebnis berechnen).
- [ ] Prüfen, dass `dashboard.py` `build_payload()`-`summary` (llm/random avg)
      danach die korrigierten Punkte zeigt.
- [ ] `README.md` anpassen: der Satz „standard Kicktipp scoring (3 pts exact …)"
      (Abschnitt *Performance tracking*) beschreibt das falsche Schema.
- [ ] ADR `docs/adr/000X-abweichendes-punktesystem.md` (Nygard) für die
      Entdeckung + Korrektur.

## Elegantere Alternative (statt nachrechnen)

`community_tips.jsonl` enthält bereits die **echten Kicktipp-Punkte pro Tipp**
(direkt aus der Zelle, `<sub class="p">`). Statt im Bot nachzurechnen, könnte man
die eigenen Punkte **direkt aus der Live-Seite** übernehmen — dann ist man
immun gegen jede Schema-Abweichung. Abwägen: `tips_history` ist die Bot-Quelle,
`community_tips` die Live-Wahrheit; ggf. zusammenführen.

## Wichtige Nebenbefunde

- Die frühen `random`-Einträge in `tips_history.jsonl` sind teils **veraltete
  Testdaten**, die von der Live-Seite abweichen (z.B. dernerl Frankreich–Senegal:
  History `3:1`, live tatsächlich `2:1`). Bei der Migration beachten:
  Neuberechnung aus `tips_history`-Tipps kann von den echten Live-Punkten
  abweichen — `community_tips` als Cross-Check nutzen.
- **Nicht betroffen:** „Verrückte Tipps" im Dashboard. Die Klassifikation läuft
  über Tipp-vs-Ergebnis (scoring-unabhängig), nicht über den Punktwert.

## Verifikation nach Fix

- `_points` gegen `community_tips.jsonl` testen: für dernerls Tipps muss der neu
  berechnete Wert exakt den dort gespeicherten Zellen-Punkten entsprechen.
- llm/random-Schnitte vor/nach dem Fix vergleichen und plausibilisieren.
