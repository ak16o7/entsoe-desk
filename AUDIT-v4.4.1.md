# ENTSO-E Desk v4.4.1 — Prüfbericht

Stand: 11.09.2026. Auf v4.4 aufbauendes Update für das bestehende GitHub-/Render-Deployment.

## Ergebnis

Die im Feedback bestätigten Darstellungsprobleme wurden behoben: fehlende Aktivierung wird nicht mehr als Null bezeichnet; A24 nennt die vier deutschen LFA/SCA; der Gesamtstatus unterscheidet Antworten von Datenabdeckung. Panel 4 benennt die gemeldete Nichtverfügbarkeit und zeigt getrennte Aufteilungen nach A53/A54 sowie Dauer. A85 verwendet positive/negative Imbalance.

Die Parser, die vier Gebietsanfragen, A67/A68 und A60/A61 sowie der lückenweise A51/A47-Fallback aus v4.4 bleiben erhalten. A80 bleibt Primärquelle; A77 dient als Zonen-Fallback. Der Quellenumfang entspricht keinem vollständigen Kraftwerksregister.

## Methodik der neuen Anzeige

Jede aktive Ressource trägt pro Aufteilung maximal die größte gleichzeitig gemeldete Einschränkung bei. Unterschiedliche Klassifizierungen überlappender Meldungen landen in „mixed/unknown“. Typ und Dauer sind zwei separate Partitionen desselben Totals. Geplant bedeutet nicht zwingend Wartung. Langfristig (≥30 Tage Gesamtlaufzeit) und offene Endmarkierung (lokales Endjahr ≥2100) sind ausdrücklich Desk-Konventionen. Eine offene Endmarkierung beweist keine Stilllegung.

Die Tabelle zeigt alle reportablen Tagesmeldungen im gewählten Quellenumfang, nicht nur zwölf. Typ-/Dauerfilter betreffen nur die Tabelle. Meldungs-MW sind bei Ressourcenüberlappungen nicht additiv. Eine spätere Kapazitätsstufe eines bereits begonnenen Ereignisses zählt nicht als neues bevorstehendes Ereignis.

Die API ergänzt `quality`, bei Outages außerdem `notices` und `breakdown`; bestehende Felder einschließlich `top` bleiben erhalten. `quality` beschreibt nutzbare Reihen im ausgewählten Umfang, keine Garantie lückenloser Tagesdaten oder Aktualität. Gleichheit der A85-Preise wird nur für denselben ISP zusammengefasst und ist allein kein Nachweis eines regulatorischen Preisverfahrens.

## Ausgeführte Prüfungen

- 68 Unit-, Parser- und HTTP-Tests bestanden, darunter 18 neue Tests für Klassifikation, Ressourcenüberlappung, unbekannte Kapazität, Teilabdeckung und vollständige Meldungslisten.
- Echter ENTSO-E-Abgleich für Liefertag 10.09.2026: 45 unabhängige XML-/Serienvergleiche über 4.320 Datenpunkte bestanden. Ergebnisse in `validation/live-audit.json`.
- Historische Outage-Referenz 10.09., 23:45 Europe/Berlin: 54.704,9 MW, 224 Tagesmeldungen, 183 aktive Meldungen, 169 aktive Ressourcen. Beide neuen Aufteilungen stimmen separat mit 54.704,9 MW überein.
- HTTP-Smoke-Test gegen lokalen Uvicorn mit echtem ENTSO-E-Zugriff: `/health` sowie alle fünf Panel-Endpunkte erfolgreich.
- Browserprüfung mit Live-Daten vom 11.09.: fünf Panels antworten, Balancing „partial“; drei von vier LFA/SCA verfügbar. Amprion ohne verwertbare Aktivierungsdaten bleibt ausdrücklich unbekannt.
- Browserfilter „forced + long-term“: 10 von 214 Meldungen; alle Treffer passen zu beiden Kriterien, unveränderte Gesamtkapazität. Offene Endmarkierung: Doel 2 und Rodenhuize 4, zusammen 650 MW. Dies sind Momentaufnahmen, keine dauerhaft erwarteten Werte.
- Desktop und mobile Breite 390 Pixel geprüft, kein horizontaler Seitenüberlauf; keine Browser-Konsolenfehler. Positive/negative A85-Anzeige am gleichen ISP geprüft.
- ZIP wird auf Integrität, versehentlich enthaltenen API-Schlüssel und ausgeschlossene lokale `.env` geprüft; Tests werden zusätzlich aus dem entpackten Lieferpaket ausgeführt.

## Deployment und Grenzen

Keine neuen Umgebungsvariablen oder Datenbankmigrationen. Den Inhalt des ZIP-Projektordners in den bestehenden Repository-Root übernehmen; Anleitung in `DEPLOY-RENDER.md`. Der API-Schlüssel bleibt ausschließlich lokal beziehungsweise in Render Environment.

Docker war lokal nicht verfügbar; ein Docker-/Render-Build wurde nicht ausgeführt. Das Live-Deployment wurde nicht verändert. Nach dem Push ist der Render-Build der abschließende Infrastrukturtest. Historische ENTSO-E-Daten können revidiert werden; fehlende Publikationen werden durch dieses Update nicht ersetzt.

## Spezifikationen

- [ENTSO-E: Generation/Production Unavailability 15.1.A–D](https://transparencyplatform.zendesk.com/hc/en-us/articles/16652173943828-Planned-Unavailability-Changes-in-Actual-Availability-of-Generation-Production-Units-15-1-A-15-1-B-15-1-C-15-1-D)
- [ENTSO-E: Imbalance Price category A04/A05](https://transparencyplatform.zendesk.com/hc/en-us/articles/15857085879060-Imbalance-Price-category)
- Weitere Parser-/A24-Spezifikationen und Basisprüfung: `AUDIT-v4.4.md` (historischer Bericht).
