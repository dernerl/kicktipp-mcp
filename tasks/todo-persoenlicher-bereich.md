# Todo: Persönlicher Bereich überarbeiten

**Status:** ERLEDIGT (2026-06-28) · **Erfasst:** 2026-06-28

Betrifft Abschnitt C im Dashboard (`web/dashboard.html`, `sectionPersonal` /
`renderTipsTable` / `renderStats`).

## Bekannte Probleme / Wünsche

1. **Bug: Ergebnis immer grün.** In der Tipp-Tabelle wird das Ergebnis als
   `<span class="score res">` gerendert, und `.score.res` ist fest grün
   (`background: var(--green-dim); color: var(--green)`) — **unabhängig davon, ob
   der Tipp stimmte**. Ein kompletter Fehlschuss zeigt das Ergebnis trotzdem grün,
   was „richtig" suggeriert.
   → **Fix:** Ergebnis (oder die Zeile) nach **Tipp-vs-Ergebnis** einfärben —
   exakt = grün, Teiltreffer (Differenz/Tendenz) = amber/blau, daneben = rot,
   offen = grau. Konsistent mit dem „Pkt"-Badge. Die Klassifikation ist
   scoring-unabhängig (Tipp vs Ergebnis), kann also sofort gemacht werden.

2. **LLM-vs-Random-Vergleich ist mir nicht wichtig.** Die Stat-Kacheln „Ø llm /
   Ø random / beste Strategie" können raus oder stark verkleinert werden. Statt
   Strategie-Vergleich lieber: eigener Tabellenplatz, Trefferquote (exakt/Tendenz/
   daneben), Punkte gesamt.

## Offene Design-Fragen (gemeinsam klären)

- Was soll der Bereich primär zeigen? (z.B. „wie gut tippe ich" statt „welche
  Strategie ist besser")
- Sortierung/Filter: neueste zuerst? Filter nach Status (nur Treffer / nur daneben)
  statt nach Strategie?
- „Warum?"-Begründung (aus dem Log) behalten? (eher ja — ist das Highlight)
- Sollen die **echten Kicktipp-Punkte** statt der nachgerechneten gezeigt werden?
  → hängt am Punktesystem-Fix (siehe `tasks/todo-punktesystem.md`, 4/3/2/0).
  Einfärbung nach Tipp-vs-Ergebnis geht unabhängig davon sofort.

## Aufgaben
- [x] Ergebnis-/Zeilen-Einfärbung nach Tipp-vs-Ergebnis (Grün-Bug behoben:
      `.score.res-${status}`, exakt grün / Diff blau / Tendenz amber / daneben rot / offen grau).
- [x] Strategie-Vergleich entfernt; stattdessen Kacheln **Aktueller Platz · Punkte ·
      Trefferquote** (exakt/teils/daneben).
- [x] Filter entfernt (kein llm/random-Filter mehr), Tabelle **neueste zuerst**;
      Spalte „Ausgang" (Pill) statt Pkt-/Strategie-Spalte.
- [x] „Warum?"-Panel (LLM-Reasoning aus dem Log) beibehalten.
- [~] Echte Punkte anzeigen: durch den 4/3/2/0-Fix (ADR 0005) sind die Punkte jetzt
      korrekt; der „Punkte"-Wert oben kommt aus `ranking_history` (echter Tabellenstand).

## Review (2026-06-28)
Umgesetzt: Grün-Bug per Agent gefixt, Umbau interaktiv mit dem User (Vorgaben:
Platz/Punkte/Trefferquote, kein Filter, Warum behalten). Headless-Screenshot bestätigt:
daneben-Zeilen rot, Teiltreffer blau/amber, exakt grün. JS syntaxgeprüft, keine toten
Referenzen (`renderFilters`/`pFilter`/Strategie-Badge raus).
