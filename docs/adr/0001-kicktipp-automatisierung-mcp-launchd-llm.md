# ADR 0001: Kicktipp-Automatisierung via kicktipp-mcp + launchd + LLM-Strategie

**Date:** 2026-06-16
**Status:** Accepted

---

## Context

Für ein privates WM-2026-Tippspiel auf kicktipp.de (Gruppe "wm-tipp-von-mischa") sollen Tipps
automatisch abgegeben werden — täglich für Spiele die in den nächsten ~24 Stunden anstehen.
Kicktipp hat keine öffentliche API; alle Interaktionen laufen über die Website.

Anforderungen:
- Tipps sollen ca. 1 Tag vor Anstoß abgegeben werden, damit aktuelle Infos (Aufstellungen, Verletzungen) einfließen können
- Die Lösung soll ohne offene Claude-Code-Session laufen (vollständige Automation)
- Interaktive Abfragen ("wie stehe ich gerade?", "tip die heutigen Spiele") sollen direkt in Claude Code möglich sein
- Ziel: Platz 1 in der Gruppe — d.h. die Tipp-Qualität muss besser sein als reine Zufallsstrategie

Ausgangspunkt: Erster Versuch mit Playwright (MCP-Playwright-Plugin in Claude Code) war funktionstüchtig, aber extrem token-hungrig — ein einzelner Seiten-Snapshot verbrauchte tausende Tokens.

---

## Decision

Wir verwenden [kicktipp-mcp](https://github.com/Cloudy261/kicktipp-mcp) als Basis: ein reines
HTTP-Client-Projekt (Python, requests + BeautifulSoup) ohne Browser-Abhängigkeit, das sowohl
einen MCP-Server als auch einen CLI-Bot mitliefert.

- **MCP-Server** (`run-mcp.sh`) ist in `~/.claude/.mcp.json` eingetragen → Tools `list_open_matches`, `list_submitted_tips`, `submit_tips`, `get_ranking` stehen in jeder Claude-Code-Session zur Verfügung
- **CLI-Bot** läuft via macOS launchd alle 6 Stunden (`~/Library/LaunchAgents/com.kicktipp-ai.bot.plist`)
- **Strategie**: `llm` — der Bot ruft `claude -p` mit WebSearch auf und bekommt einen Prompt der das Kicktipp-Punktesystem (3 Pkt Exakt / 2 Pkt Differenz / 1 Pkt Tendenz) und Spieltheorie (Crowd-Differenzierung) berücksichtigt
- **Tipp-Fenster**: `--max-hours-ahead 30` — tippt Spiele die in den nächsten 30 Stunden anstehen
- **Credentials**: Passwort liegt im macOS Login-Keychain (`cli/kicktipp` / `kicktipp.de`), wird beim Setup einmalig in `.env` geschrieben

Erweiterung gegenüber dem Original-Repo: Funktion `fetch_ranking()` + MCP-Tool `get_ranking`
wurden nachträglich ergänzt (Gesamtübersicht-Seite, Tabelle `id="ranking"`).

---

## Consequences

**Positiv:**
- Kein Browser-Overhead — reine HTTP-Requests, minimaler Token-Verbrauch
- Vollautomatisch über launchd, keine offene Session nötig
- LLM-Strategie berücksichtigt aktuelle Infos (Verletzungen, Rotation, Form) die in Wettquoten nicht eingepreist sind
- Interaktive Nutzung in Claude Code ohne Playwright möglich

**Negativ / Trade-offs:**
- `.env`-Datei mit Klartext-Passwort liegt im Repo-Verzeichnis (git-ignored, aber lokales Risiko)
- `llm`-Strategie kostet Claude-Pro-Tokens und braucht ~1-2 Min pro Lauf
- Wenn kicktipp.de das HTML-Layout ändert, bricht der Parser — kein offizieller API-Vertrag

**Neutral:**
- Der launchd-Agent läuft nur wenn der Mac eingeschaltet und nicht im Schlafmodus ist
- `RunAtLoad: false` — kein unbeabsichtigter Sofort-Lauf beim Laden (Lektion aus erstem Setup-Versuch)

---

## Considered Alternatives

| Option | Bewertet als |
|--------|--------------|
| Playwright (MCP-Plugin in Claude Code) | Funktioniert, aber ~5000+ Tokens pro Seite — untragbar für Automation |
| kicktipp-bot (antonengelhardt, Selenium) | Browserbasiert wie Playwright; standalone ok, aber keine MCP-Integration; LLM-Strategie fehlt |
| kicktipp-agent (christianheidorn, TypeScript + Playwright) | Hat Leaderboard eingebaut, aber Playwright-Abhängigkeit; 3 Monate älter; Projekt läuft bereits in Python |
| kicktipp-api (PaulThiede) | 0 Stars, kein README, Qualität unklar |
| Eigener HTTP-Client from scratch | Kicktipp-mcp löst das bereits — kein Mehrwert durch Neuimplementierung |
| Claude Desktop MCP | Nur sinnvoll wenn Claude Desktop primär genutzt wird; User arbeitet in Claude Code |
