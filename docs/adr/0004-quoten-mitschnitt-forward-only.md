# ADR 0004: Quoten-Mitschnitt forward-only (kein Backfill), Upsert pro Match

**Date:** 2026-06-28
**Status:** Accepted — teilweise korrigiert durch ADR 0007

> **Update (ADR 0007):** Die Kernannahme — Quoten seien nicht rückwirkend abrufbar,
> daher „kein Backfill" — war **falsch.** Kicktipp zeigt die Quoten auf der Tippabgabe-
> Seite für alle Spieltage (auch gespielte). Der `record_odds`-Mitschnitt pro Lauf bleibt
> gültig; „kein Backfill möglich" ist es nicht. Siehe ADR 0007.

---

## Context

Kicktipp zeigt die Buchmacher-Quoten (1 = Heimsieg, X = Unentschieden,
2 = Auswärtssieg) ausschließlich auf der **Tippabgabe-Seite** und nur für Spiele,
die **noch nicht angepfiffen** sind. Sobald ein Spiel startet, verschwinden die
Quoten aus der Ansicht, und die historische `tippuebersicht` enthält sie gar
nicht. Damit lassen sich Quoten für vergangene Spiele **nicht rückwirkend**
beschaffen — es gibt keine Quelle dafür.

Quoten sind aber wertvoll: als Markt-Konsens-Signal für die `llm`-Strategie und
als spätere Analyse-Grundlage (Quote vs. tatsächliches Ergebnis, Quote vs.
Bot-Tipp). Der Bot läuft ohnehin alle 6 Stunden via launchd und lädt dabei die
Tippabgabe-Seiten — der Moment, in dem die Quoten verfügbar sind.

Die Quote eines Spiels ändert sich zudem bis kurz vor Anpfiff. Interessant ist
vor allem die Quote möglichst nah am Anpfiff (höchster Informationsstand).

## Decision

Quoten werden **forward-only** mitgeschnitten — kein Backfill, weil technisch
unmöglich. `odds_history.py` schreibt bei jedem Bot-Lauf einen Snapshot der
aktuell offenen Spiele (mit vorhandenen Quoten) nach `data/odds_history.jsonl`.

Strategie: **Upsert pro Match**, Key = `(spieltag_index, home_team, away_team)`.
Solange ein Spiel noch offen ist, wird seine Zeile bei jedem Lauf mit der
aktuellsten Quote **überschrieben**. Nach dem letzten Lauf vor Anpfiff steht so
die Quote möglichst nah am Anpfiff im File. Bereits angepfiffene oder aus der
Ansicht verschwundene Spiele tauchen in keinem Snapshot mehr auf und bleiben
unverändert erhalten. Spiele ohne Quoten werden übersprungen.

Verdrahtung: Der Aufruf hängt im Bot-Run-Pfad (`main.py`) **nach dem Laden der
Spiele** und läuft **unabhängig vom Submit** (auch bei `--dry-run`) — Quoten
erfassen ist kein Tipp-Abgeben. Er ist **best-effort**: ein Fehler beim
Mitschnitt fängt ein `try/except` ab und darf den Bot-Lauf nie abbrechen
(eine verpasste Tipp-Deadline wäre schlimmer als ein fehlender Quoten-Snapshot).

## Consequences

**Positiv:**
- Quoten werden ab jetzt verlustfrei und ohne Zusatzaufwand erfasst (huckepack
  auf dem ohnehin laufenden 6-Stunden-Lauf).
- Upsert hält das File schlank (eine Zeile pro Match) und liefert automatisch die
  pre-kickoff-nächste Quote.
- Best-effort/defensiv: kein Risiko für den eigentlichen Tipp-Auftrag.
- Keine neue Dependency — gleicher JSONL-Stil wie `tracking.py`, `data/` ist
  bereits gitignored.

**Negativ / Trade-offs:**
- **Kein Quoten-Verlauf pro Spiel**: durch das Überschreiben geht zwischen
  früher und später Quote die Bewegung verloren; nur der letzte Stand bleibt.
  (Für den aktuellen Zweck — Konsens nah am Anpfiff — ausreichend.)
- Quoten für alles **vor** Einführung dieses Features fehlen dauerhaft.
- Granularität ist an den 6-Stunden-Takt gekoppelt: die gespeicherte Quote ist
  die des letzten Laufs vor Anpfiff, nicht zwingend die Schlussquote.

**Neutral:**
- `data/odds_history.jsonl` ist lokal und gitignored; kein Versionsverlauf.

## Considered Alternatives

| Option | Bewertet als |
|--------|--------------|
| **Backfill aus Vergangenheit** | Unmöglich — `tippuebersicht` hat keine Quoten, Tippabgabe zeigt sie nur pre-kickoff. Verworfen, weil keine Datenquelle existiert. |
| **Append statt Upsert** (jede Quote als neue Zeile) | Behält den Quoten-Verlauf, bläht das File aber pro Match × Läufen auf und braucht nachgelagerte Dedup-/„latest"-Logik. Overkill für den aktuellen Bedarf; bei Bedarf später nachrüstbar. |
| **Tippkreis als Quote** (Community-Tipps als impliziter Markt) | Deckt auch die **Vergangenheit** ab (aus `community_tips.jsonl`/`ranking_history.py` rekonstruierbar) und wird im Dashboard für „Verrückte Tipps" bereits genutzt. Ist aber eine *andere* Größe (Crowd-Konsens, nicht Buchmacher-Quote) und ersetzt den echten Quoten-Mitschnitt nicht — ergänzt ihn. |
| **Separater Cron nur für Quoten, feinere Taktung** | Würde Schlussquoten näher treffen, aber zweiter Scheduler + Login-Last. Nicht den Mehrwert wert; huckepack auf dem Bot-Lauf genügt. |
