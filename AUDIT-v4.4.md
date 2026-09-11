# ENTSO-E Desk v4.4 – Prüfbericht

Stand: 11. September 2026. Ausgangspunkt: bereitgestelltes v4.3-ZIP und https://entsoe-desk.onrender.com/. Der vorhandene Render-Dienst wurde nur gelesen, nicht verändert. Der vom Nutzer benannte lokale API-Schlüssel wurde ausschließlich für autorisierte ENTSO-E-Abfragen verwendet; das Lieferpaket enthält keine Zugangsdaten.

## Ergebnis

**50 Unit-, Parser-, Integrations- und HTTP-Tests bestanden.** Zusätzlich stimmen **45 unabhängig aus den Live-XML-Punkten expandierte Reihen / 4.320 Messpunkte** mit v4.4 überein. Zulässige Abweichung: höchstens 0,0011 wegen der JSON-Rundung auf drei Nachkommastellen. Der Vergleich betrifft Solar/Wind samt drei Prognoseprozessen, Last, beide Flussmetriken aller elf Grenzen, verfügbare A24-Gebiete, A85 und A86.

Alle fünf lokalen HTTP-Endpunkte und `/health` antworteten erfolgreich. Im Browser wurden zehn Plotly-Diagramme und alle fünf geladenen Panels beobachtet; keine JavaScript-Fehler in der Browserkonsole. Desktop und mobile 390-Pixel-Ansicht geprüft: kein horizontaler Seitenüberlauf. Datumswechsel zum historischen Prüftag getestet.

## Panel 4: Ursache und Korrektur

v4.3 suchte `nominalP` als vollständigen Elementnamen. Die tatsächlich gelieferten Dokumente enthalten hingegen `production_RegisteredResource.pSRType.powerSystemResources.nominalP`. Dadurch blieb die Nennleistung unbekannt; nachgelagerte Filter entfernten die Ereignisse und meldeten fälschlich null.

v4.4 liest diese punktierten Elementnamen und weitere R3-Felder ausdrücklich. Beispiel aus der Live-API: BERGKAMEN_A, Generationseinheit `11WD7BERG1S--A-X`, Produktionsanlage `11WD7BERG1S--KWB`: 717 MW nominal minus 640 MW verfügbar = **77 MW Einschränkung**. Der alte Parser konnte diese Differenz nicht berechnen. Das Beispiel liegt als Regression im ZIP.

Weitere Korrekturen: Generationseinheitenname statt pauschalem Anlagenname; PSR-Typ und Standort; Ereigniszeitgrenzen; Reason-Felder; A01 versus A03; sortierte Positionspunkte; Zeitbereich des ausgewählten Tages; höchste Dokumentrevision; Stornierungen ohne TimeSeries/Punkte; Fehlerstatus bei ungültigem XML; unbekannte Kapazität bleibt null mit sichtbarer Ereigniszahl. Überlappende absolute Verfügbarkeitsmeldungen derselben Ressourcen-ID werden für MW mit ihrem Maximum berücksichtigt, nicht addiert.

**Live-Prüftag 10.09.2026:** DE-LU lieferte 157 A80- und 30 A77-Dokumente. Im bestehenden ausgewählten Umfang DE-LU/FR/NL/BE erkennt v4.4 **224 Ereignisse im Tag**, davon **183 aktiv um 23:45 Europe/Berlin**. Kapazität nach Ressourcen-Deduplizierung: **54.704,9 MW**. Keine unbekannten Kapazitäten im ausgewählten Live-Ergebnis. Die Zahl ist eine Momentaufnahme revidierbarer Publikationen.

**Bewusst beibehaltener Umfang:** A80 ist je Zone primär, A77 nur Fallback. Diese konservative Auswahl verhindert Hierarchie-Doppelzählung; sie ist keine Vereinigung aller A77- und A80-Meldungen und kann zusätzliche ausschließlich auf Anlagenebene veröffentlichte Ausfälle auslassen. Der UI-Umfang und README benennen dies. `coverage_complete` bedeutet vollständig innerhalb dieser Auswahl.

## Panel 5: 12.3.E

A24 verwendet `area_Domain` für die Scheduling Areas/LFA/SCA:

| Gebiet | EIC |
|---|---|
| 50Hertz | 10YDE-VE-------2 |
| Amprion | 10YDE-RWENET---I |
| TenneT DE | 10YDE-EON------1 |
| TransnetBW | 10YDE-ENBW-----N |

Primärprozesse: A67/A68 für aFRR Central/Local und A60/A61 für mFRR Scheduled/Direct. A51/A47 werden nur zum Füllen fehlender aktivierter Werte verwendet. Auswahl erfolgt pro Gebiet, Produkt, Richtung und Zeitpunkt. Split-Werte einschließlich null werden nie zusammen mit einem generischen Fallback addiert. Nicht spezifizierte Produktaggregate werden nicht neben bereits ausgewählten Produkten addiert. Dokumentlokale TimeSeries-mRID wie „1“ oder „2“ dürfen weder Regelzonen noch Produkte zusammenfallen lassen.

`quantity` ist angeboten, `secondaryQuantity` ist aktiviert, `unavailable_Quantity.quantity` ist nicht verfügbar. Fehlende sekundäre Mengen sind keine Null und kein Angebot. Im Live-Beispiel A47 gibt es angebotene Mengen ohne Aktivierung; A60/A61 liefern gleichzeitig explizite Nullen. Diese Nullen bleiben erhalten.

| Gebiet am 10.09.2026 | aFRR | mFRR |
|---|---|---|
| 50Hertz | A67, 96 Netto-MTUs | A60/A61, 96 Netto-MTUs |
| Amprion | no_data | no_data |
| TenneT DE | A67, 96 Netto-MTUs | A60/A61, 96 Netto-MTUs |
| TransnetBW | A67, 96 Netto-MTUs | A60/A61, 96 Netto-MTUs |

A68 meldete im historischen Test `no_data`; ein nicht publizierter Kanal bleibt im API-Quellenstatus erkennbar. Amprion lieferte auch im Browser-Livetest für den 11.09. keine Aktivierungsdaten. Darum ist **`partial` fachlich richtig**. Die sechs vorhandenen Gebietsreihen werden angezeigt; die Deutschlandsumme bleibt unterdrückt. Das ist keine Garantie, dass der fehlende Netzbetreiber physisch nichts aktiviert hat.

A85 bleibt EUR/MWh, A86 bleibt MWh je ISP. A86 erfordert gemeinsame Zeitpunkte aller vier Regelgebiete; A85 fällt im beobachteten Live-Ergebnis auf die vorhandene DE-Publikation zurück. Gebietspreise werden nur zusammengeführt, wenn sie übereinstimmen.

## Übrige Panels

| Panel | Abfragen / Prüfung | Ergebnis |
|---|---|---|
| 1 Erneuerbare | A75/A16, A69/A01/A18/A40, B16/B18/B19, DE | Alle 12 Rohreihen mit je 96 MTUs abgeglichen; getrennte Forecast-Prozesse, vollständige RES-Summen; Verbrauchsreihen ausgeschlossen. |
| 2 Last/Residuallast | A65/A16 und A01, DE | 96 tatsächliche und 96 Prognose-MTUs abgeglichen; Formeltest 100−30=70 und DA 90−25=65, Überraschung 5 MW. |
| 3 Grenzen | A11 und A09 mit DA-Vertrag A01, DE-LU | Alle 11 Grenzen, je physisch und geplant, je 96 Netto-MTUs abgeglichen; doppelte Auswahl entfernt; fehlende Gesamtdeckung unterdrückt Total. |

Zeitrechnung erfolgt intern in UTC. Regressionen bestätigen 92 Viertelstunden im März und 100 im Oktober. API-Perioden erhalten ihre Minuten. Nicht unterstützte kalendarische Auflösungen werden ausdrücklich abgelehnt. `createdDateTime` kann ein API-Erstellungszeitpunkt sein und wird nicht als gesicherter ursprünglicher Prognosezeitpunkt interpretiert.

## Test- und Lieferumfang

- 15 bestehende Tests aktualisiert/beibehalten, 35 neue Tests: Parser, echte XML-Fixtures, Fallback, Revisionen, Ausfall-Deduplizierung, unbekannte Werte, Gebietsvollständigkeit, DST, Residuallast, Auth, HTTP-Routen und Fehlerbehandlung.
- `scripts/live_smoke.py`: reproduzierbarer Live-XML-Abgleich für den publizierten historischen Tag. Bei anderen Tagen/Publikationsumfängen können die bewusst strikten Vergleichsannahmen fehlschlagen.
- `scripts/smoke_http.py`: read-only Prüfung nach dem Render-Deployment.
- `validation/live-audit.json`: vollständige historische Panelantworten und Vergleichsergebnisse, ohne Tokens.
- Python 3.13.14 unter Windows; Abhängigkeiten installiert, `pip check` erfolgreich. Top-Level-Runtime-Abhängigkeiten auf geprüfte Versionen festgesetzt.

**Nicht ausgeführt:** Docker-Image-Build (kein Docker verfügbar), echter Render-Build/Deploy, Langzeit-Lasttest. Dockerfile, Render-Service-Name, PORT und Healthcheck bleiben kompatibel. Ein tatsächlicher Render-Build ist der abschließende Infrastrukturtest; siehe DEPLOY-RENDER.md. Fehlende Publikationen und spätere Revisionen bleiben externe Datenrisiken.

## Offizielle Quellen

- [ENTSO-E REST API: Parameter und Prozesscodes](https://documenter.getpostman.com/view/7009892/2s93JtP3F6)
- [ENTSO-E Übersicht der gültigen XML-Schemata und Beispiele](https://transparencyplatform.zendesk.com/hc/en-us/articles/17260622859412-Transparency-Platform-Help-page)
- [A24 XML-Beispiel, Schema 4:1](https://gitlab.entsoe.eu/transparency/xml-examples/-/blob/main/Balancing/Aggregated%20balancing%20energy%20bids%20%5BGL%20EB%2012.3.E%5D%20-%20XSD4%3A1.xml)
- [Outage XML-Beispiel, Schema 4:0](https://gitlab.entsoe.eu/transparency/xml-examples/-/blob/main/Outages/Unavailability%20of%20Production%20and%20Generation%20Units%20%5B15.1.A%26B%26C%26D%5D%20-%20XSD4%3A0.xml)
- [12.3.E R3: Gebietstypen, Mengen und Reservearten](https://transparencyplatform.zendesk.com/hc/en-us/articles/24433096274193-AggregatedBalancingEnergyBids-12-3-E-r3)
- [Outage-Definitionen und Kapazitätssemantik](https://transparencyplatform.zendesk.com/hc/en-us/articles/16652173943828-Planned-Unavailability-Changes-in-Actual-Availability-of-Generation-Production-Units-15-1-A-15-1-B-15-1-C-15-1-D)
- [Query Limits einschließlich 200 Outage-Dokumenten](https://transparencyplatform.zendesk.com/hc/en-us/articles/15854536354964-API-Query-Size-Limit)

Die offiziellen XML-Beispiele dienen als Formatdokumentation; die enthaltenen Kommentare wurden nicht als Arbeitsanweisungen übernommen. Die mitgelieferten Test-XMLs stammen aus den tatsächlich abgefragten Live-Antworten.
