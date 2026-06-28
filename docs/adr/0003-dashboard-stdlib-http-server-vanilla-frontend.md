# ADR 0003: Dashboard als stdlib-`http.server` + Vanilla-Frontend, ohne neue Dependencies

**Date:** 2026-06-27
**Status:** Accepted

---

## Context

Das Ergebnis-Dashboard soll lokal laufen (localhost) und drei Ansichten bieten:
Positionsverlauf (interaktiver Bump-Chart mit Slider), "verrückte Tipps"
(farbcodiert) und einen persönlichen Bereich mit Tipp-Liste, Eingetroffen-Status
und ausklappbarer Claude-Begründung.

Das Projekt ist bewusst schlank: nur `requests`, `beautifulsoup4`,
`python-dotenv`, `mcp`. Es gibt keinen Build-Step, kein Node-Toolchain, kein
Web-Framework. Ein privates Hobby-Tool für einen einzelnen Nutzer auf dem
eigenen Mac.

## Decision

Das Dashboard wird mit der **Python-Standardbibliothek** (`http.server`,
`ThreadingHTTPServer`) serviert (`dashboard.py`). Das Frontend ist eine
**einzelne statische HTML-Datei** (`web/dashboard.html`) mit Vanilla-JavaScript
und handgezeichnetem **SVG** für den Bump-Chart — kein Chart.js, kein CDN, kein
Framework, kein Bundler.

Datenfluss: `GET /api/data` aggregiert `tips_history.jsonl` +
`ranking_history.jsonl` + die geparsten Log-Begründungen zu einem JSON;
`GET /api/refresh` stößt den Standings-Scrape live an. Server bindet an
`127.0.0.1`.

## Consequences

**Positiv:**
- **Null neue Dependencies** — passt zur bestehenden Schlankheit; `uv run python
  dashboard.py` genügt.
- Offline-tauglich (kein CDN); funktioniert ohne Internet bis auf den Refresh.
- Eine HTML-Datei, kein Build — trivial zu verstehen, anzupassen, zu versionieren.
- Localhost-only Bind → keine Exposition nach außen.

**Negativ / Trade-offs:**
- Bump-Chart, Slider/Play und Tabellen sind **handgeschrieben** (mehr JS-Code als
  mit einer Chart-Lib). ~12 KB Inline-Skript.
- `http.server` ist ein Dev-Server (Single-Purpose, kein Prod-Hardening) — für
  ein lokales Einzelnutzer-Tool akzeptabel.
- Kein Hot-Reload/Komponentenmodell; Änderungen am UI sind reines DOM/SVG.

**Neutral:**
- Aggregations- und Craziness-Logik liegt serverseitig in `dashboard.py`, das
  Frontend bleibt dünn (Rendering + Interaktion).

## Considered Alternatives

| Option | Bewertet als |
|--------|--------------|
| Flask/FastAPI + Chart.js (CDN) | Kompakterer Code, hübschere Charts out-of-the-box — aber neue Python-Dep + CDN-/Internet-Abhängigkeit; Overkill für ein lokales Hobby-Tool |
| Statisches HTML ohne Server (file://) | Scheitert an `fetch()`-CORS für lokale JSON; kein Live-Refresh möglich |
| React/Svelte + Vite | Build-Toolchain, Node-Abhängigkeit — widerspricht der Projekt-Schlankheit |
