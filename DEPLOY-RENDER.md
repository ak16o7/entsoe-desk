# ENTSO-E Desk – kostenlos auf Render deployen

Diese Version ist für ein Docker-basiertes Render-Deployment vorbereitet.

## 1. Was du brauchst

- einen ENTSO-E Web API Token
- ein GitHub-Konto
- ein Render-Konto

Wichtig: `.env` gehört **nicht** ins Git-Repository. Diese Distribution enthält deshalb bewusst keine `.env`-Datei.

## 2. Lokal testen (optional)

```bash
cp .env.example .env
```

Trage in `.env` deinen Token ein und starte:

```bash
docker compose up --build
```

Dann: `http://localhost:8000`

## 3. Neues GitHub-Repository anlegen

Lege z. B. `entsoe-desk` an und führe im Projektordner aus:

```bash
git init
git add .
git commit -m "Initial deploy"
git branch -M main
git remote add origin https://github.com/DEIN-NAME/entsoe-desk.git
git push -u origin main
```

Prüfe vor dem Push:

```bash
git status
git ls-files .env
```

Der zweite Befehl darf **keine Ausgabe** liefern.

## 4. Render Blueprint deployen

1. Render öffnen und GitHub verbinden.
2. `New` → `Blueprint` wählen.
3. Das Repository `entsoe-desk` auswählen.
4. Render erkennt `render.yaml`.
5. Bei den Secrets eintragen:
   - `ENTSOE_API_KEY`: dein ENTSO-E Token
   - `DASHBOARD_USERNAME`: gewünschter Loginname
   - `DASHBOARD_PASSWORD`: ein starkes Passwort
6. Blueprint anwenden/deployen.
7. Nach erfolgreichem Build die angezeigte `*.onrender.com`-URL öffnen.

Der Browser fragt beim ersten Aufruf nach Benutzername und Passwort. Der ENTSO-E-Key bleibt ausschließlich auf dem Server.

## 5. Updates veröffentlichen

Nach Änderungen lokal:

```bash
git add .
git commit -m "Update dashboard"
git push
```

Render deployt den verbundenen Branch automatisch neu.

## 6. Mobile Verhalten

Die Seite nutzt kein Geräte-Raten per User-Agent. Sie reagiert automatisch auf die tatsächlich verfügbare Bildschirmbreite:

- Desktop: mehrspaltiges Dashboard
- Tablet: reduzierte Spaltenzahl
- Smartphone: einspaltige Karten, größere Touch-Ziele, kompaktere Plotly-Charts und Tooltips

Der Umschaltpunkt liegt hauptsächlich bei 720 px; weitere Layout-Breakpoints existieren bei 1050/1150/1450 px.

## 7. Einschränkung des kostenlosen Render-Plans

Ein kostenloser Render-Webservice kann nach längerer Inaktivität einschlafen. Der erste Aufruf danach benötigt entsprechend länger. Für einen dauerhaft sofort reagierenden produktiven Dienst ist später ein kostenpflichtiger Always-on-Tarif sinnvoll.
