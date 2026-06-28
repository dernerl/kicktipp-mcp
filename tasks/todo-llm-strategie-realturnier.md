# Todo: LLM-Strategie — reales Turnier klarmachen + Punktesystem korrigieren

**Status:** offen · **Erfasst:** 2026-06-28

Betrifft den `claude -p`-Prompt in `strategies.py` (gebaut in `llm_tips`, Prompt-Text
ca. ab Zeile 145).

## Problem 1: Modell hält das Turnier für fiktiv
In seinen Begründungen (Log) schreibt das Modell wiederholt Sinngemäßes wie
„this is a **simulated** WM 2026 … **fictional scenarios** … web search won't yield
match-specific data". Grund: der Wissensstand von `claude -p` endet **vor** der WM
2026, also findet die Websuche zu den Spielen (scheinbar) nichts → das Modell
schließt fälschlich „fiktiv" und verschwendet jeden Lauf Aufwand damit.

**Es ist ein echtes Turnier** (FIFA WM 2026, Juni–Juli 2026, realer Kicktipp unter
Freunden) — per Websuche verifiziert (z.B. Deutschland 7:1 Curaçao, 14.06.2026,
Houston, mit realen Quoten).

**Fix:** Im Prompt explizit klarstellen:
- Dies ist die **reale FIFA Weltmeisterschaft 2026**, kein simuliertes/fiktives Szenario.
- Der Wissensstand des Modells liegt evtl. **vor** dem Turnier; Websuche kann daher
  dünn sein. Das ist normal — die bereitgestellten Daten (Ergebnisse, Form, Tabelle,
  **Quoten**) sind echt und maßgeblich. Nicht jeden Lauf neu „herleiten", ob es real ist.
- Websuche optional/leichtgewichtig halten (Quoten sind schon inline); primär aus
  Form/Quoten/Tabellen-Kontext schließen.

## Problem 2: Falsches Punktesystem im Prompt
Der Prompt nennt (Zeilen ~157–161) das **Standard**-Schema:
```
- 3 points: exact score
- 2 points: correct goal difference
- 1 point: correct tendency
- 0 points: wrong tendency
```
Eure Runde nutzt aber **4/3/2/0** (exakt=4, Differenz ohne Remis=3, Tendenz inkl.
nicht-exaktem Remis=2, falsch=0 — siehe `tracking._points`, ADR 0005). Das Modell
optimiert also für die **falschen Anreize**.

**Fix:** Im Prompt auf 4/3/2/0 umstellen und die Strategie-Hinweise daran anpassen
(z.B. Zeile ~178: das Verhältnis „Tendenz vs. exakt" ändert sich — exakt=4 ist
doppelt so viel wie Tendenz=2; Differenz=3 ist nur 1 Punkt unter exakt).

## Aufgaben
- [ ] Prompt: reales-Turnier-Framing + Websuche-Erwartung ergänzen.
- [ ] Prompt: Punktesystem auf 4/3/2/0 korrigieren + Strategie-Hinweise anpassen.
- [ ] Optional: einen Dry-Run mit `--strategy llm` prüfen, dass das Modell nicht mehr
      „fiktiv" schließt und die Punktelogik aufgreift.

## Hinweis
`strategies.py` ist die Tipp-AUSWAHL-Logik — bei früheren Tasks bewusst nicht
angefasst. Hier geht es genau um diese Datei; sauberer eigener Change.
