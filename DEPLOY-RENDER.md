# Upgrade des bestehenden Render-Dienstes auf v4.4.1

1. ZIP entpacken. Den **Inhalt** von `entsoe-desk-v4.4.1-web` in das bestehende Repository übernehmen, sodass `Dockerfile`, `render.yaml` und `app/` weiterhin direkt im bisherigen Repository-/Render-Root liegen. Keine zusätzliche verschachtelte Projektebene anlegen.
2. Bestehende Render-Variablen, insbesondere `ENTSOE_API_KEY`, erhalten. Das Paket enthält keine `.env`. Optional eingerichtete Basic Auth unverändert beibehalten.
3. Lokal prüfen:

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
git diff --stat
git status
```

4. Die geprüften Änderungen auf den bereits von Render verwendeten Branch committen und pushen. Bei aktivem Auto-Deploy baut Render den vorhandenen Service neu; kein neues Blueprint und keine neue URL nötig.
5. Nach erfolgreichem Build `/health` aufrufen: `version` muss `4.4.1` und `configured` muss `true` sein. Browser vollständig neu laden.
6. HTTP-Smoke-Test:

```bash
python scripts/smoke_http.py --base-url https://entsoe-desk.onrender.com --day 2026-09-10
```

Panel 4 muss Meldungen und eine plausible Kapazität anzeigen oder fehlende Abdeckung ausdrücklich melden. Panel 5 muss bei nicht publizierenden Gebieten `partial` und verfügbare Gebietsreihen zeigen. `partial` allein ist kein Deploymentfehler. Niemals fehlende Gebiete durch eine Null ersetzen.

## Betrieb

Docker startet einen Uvicorn-Prozess auf `${PORT:-8000}`. Der bestehende Cache, optionale Basic Auth und der prozesslokale API-Limiter bleiben erhalten. Der Limiter ist nicht zwischen mehreren Instanzen synchronisiert; zusätzliche Worker/Instanzen erhöhen das gemeinsame ENTSO-E-Abfragevolumen. Browser-Refresh respektiert den Servercache. Free-Tier-Kaltstarts können länger dauern.

## Rollback

Den vorherigen v4.4-Commit im bestehenden Render-Service erneut deployen. Keine Datenbankmigration und keine neuen Secrets erforderlich.

## Prüfstand

Python-/HTTP-/Browser- und echte ENTSO-E-Tests wurden lokal ausgeführt. Docker/Render selbst wurde in dieser Umgebung nicht gebaut beziehungsweise deployt. Das bestehende Live-Deployment wurde nicht verändert. Das ZIP ist für den bestehenden Buildablauf vorbereitet; der Render-Build bleibt der abschließende Infrastrukturtest.
