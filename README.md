# ENTSO-E Desk v4.4

FastAPI/Python + lokal gebündeltes Plotly für das bestehende Render/GitHub-Deployment. Die fünf API-Routen und die Umgebungsvariablen bleiben kompatibel.

## Änderungen

- Panel 4 liest die vollständigen R3-XML-Elementnamen für nominalP, Generationseinheit, Produktionsanlage, PSR-Typ, Standort und Zeitgrenzen. Verfügbarkeit wird als Nennleistung minus verfügbare MW berechnet. Unbekannte Kapazitäten bleiben unbekannt, Ereignisse werden trotzdem gezählt. Stornierungen ohne Punkte, A01/A03, Revisionen und Pagination sind abgedeckt. Überlappende Meldungen desselben Ressourcen-EIC tragen maximal die größte gleichzeitig gemeldete Einschränkung bei.
- Panel 5 fragt A24/12.3.E je deutscher LFA/SCA ab: 50Hertz, Amprion, TenneT DE, TransnetBW. Primär A67/A68 (aFRR Central/Local) und A60/A61 (mFRR Scheduled/Direct). A51/A47 füllen ausschließlich fehlende aktivierte Werte desselben Gebiets, Produkts, derselben Richtung und Viertelstunde. Eine veröffentlichte Null hat Vorrang vor dem Fallback. Angebotene, aktivierte und nicht verfügbare Mengen bleiben getrennt.
- Deutschland-Aktivierung erfordert alle vier Gebiete und beide Richtungen am selben Zeitpunkt. Verfügbare Gebietsreihen bleiben bei `partial` sichtbar. Fehlende Gebiete werden nicht zu null. Die Quellenmatrix im JSON zeigt jeden Prozessstatus.
- A85 bleibt EUR/MWh, A86 bleibt MWh je ISP. A86 summiert nur gemeinsame Zeitpunkte aller vier Gebiete. Unterschiedliche Gebietspreise werden nicht zu einem erfundenen Abrechnungspreis gemittelt.
- UTC-Zeitrechnung bewahrt 92/100 Viertelstunden an Zeitumstellungstagen; Anzeige erfolgt in Europe/Berlin. Doppelte Grenzauswahl wird entfernt. Minuten in API-Zeitgrenzen bleiben erhalten; Netzwerkfehler geben keine Token-URL aus.

## Start

Python 3.12 oder 3.13:

```bash
python -m venv .venv
# Umgebung aktivieren
pip install -r requirements.txt
# .env.example nach .env kopieren und ENTSOE_API_KEY lokal setzen
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Alternativ: `docker compose up --build`. Render nutzt den bestehenden Dockerfile, `PORT` und `/health`. Der Schlüssel gehört ausschließlich in Render Environment oder eine lokale `.env`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/live_smoke.py --env-file /path/to/.env --day 2026-09-10 --output live-audit.json
python scripts/smoke_http.py --base-url http://127.0.0.1:8000 --day 2026-09-10
```

Der Live-Abgleich ist eine Regression für einen vollständig veröffentlichten Tag mit den beim Audit beobachteten Quellen. Historische Revisionen oder andere Gebietspublikationen können Vergleichsannahmen ändern und den Test gezielt fehlschlagen lassen. Die normalen Unit-Tests benötigen weder Schlüssel noch Netz.

## Datenumfang und Grenzen

- Panel 1: DE Member State, A75/A16 sowie A69/A01/A18/A40, B16/B18/B19; Erzeugungsverbrauch wird ausgeschlossen.
- Panel 2: DE Member State, A65/A16 und A01; Residuallast ist Last minus vollständige Solar-/Wind-Summe. Der DA-Vergleich benutzt DA für Last und Erneuerbare.
- Panel 3: DE-LU, elf ausgewählte Grenzen, A11 und A09 mit DA-Vertrag A01. Die API liefert Richtungswerte; Import minus Export ist die Nettozahl. Eine explizit nicht publizierte Gegenrichtung wird als `single_direction` ausgewiesen; Fehler und Lücken zwischen vorhandenen Reihen werden nicht aufgefüllt.
- Panel 4: bewusst A80 primär und A77 nur als Zonen-Fallback, wie im bisherigen Desk. Das vermeidet Hierarchie-Doppelzählung, kann aber zusätzliche, ausschließlich auf Anlagenebene publizierte A77-Ereignisse auslassen. `coverage_complete` bezeichnet die vollständige Erfassung dieses ausgewählten Quellenumfangs, kein vollständiges Kraftwerksregister.
- Panel 5: publizierte A24-Kanäle der vier LFA/SCA. Fehlende lokale aFRR- oder andere Prozesspublikationen bleiben im Quellenstatus sichtbar; `no_data` ist keine Bestätigung physischer Nullaktivierung. Fehlende sekundäre Mengen werden nie aus angebotenen Mengen abgeleitet.
- `createdDateTime` kann die Erstellung des API-Dokuments angeben und ist kein gesicherter ursprünglicher Prognose-Publikationszeitpunkt.
- Kalendarische Auflösungen P1M/P1Y werden ausdrücklich abgelehnt statt als 15 Minuten fehlinterpretiert. Für die geprüften Tagesabfragen kamen feste Auflösungen zurück.

Details, Quellen, Live-Ergebnisse und nicht ausgeführte Prüfungen: **AUDIT-v4.4.md**. Upgrade: **DEPLOY-RENDER.md**.
