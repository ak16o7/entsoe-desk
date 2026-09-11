# ENTSO-E Desk v4

A local, browser-based short-term power-market overview for Germany / Central Europe. It polls the ENTSO-E Transparency Platform Web API and renders five interactive desk panels plus explicit data-freshness and KPI-change diagnostics.

## What is in the dashboard

1. **Renewables matrix** — Solar, Wind Onshore, Wind Offshore, plus consolidated total. Every graph shows Actual, Current (A18), Intraday 08:00 (A40) and Day-Ahead 18:00 D-1 (A01).
2. **Load / residual load** — actual load and residual load against a consistent day-ahead baseline.
3. **Cross-border** — physical DE-LU net flows versus day-ahead scheduled exchanges, total or by selected border.
4. **Generation outages** — active/upcoming reportable A77/A80 events for DE-LU, FR, NL and BE. If there are no events, the UI shows a compact no-event state instead of an empty zero-line chart.
5. **System stress** — ENTSO-E A83 activated balancing (MW), A85 imbalance prices (€/MWh) and A86 total imbalance volumes (MWh per ISP/MTU) where published. Missing feeds are shown explicitly as source-health states rather than zero values.

Desk additions in v4:

- Permanent **data freshness strip**: latest RES actual, load, physical-flow and system-stress MTUs plus outage reference time.
- **Δ15m / Δ30m / Δ60m** on the main single-MTU KPIs.
- **Next 4h RES revision**: average `Current A18 RES forecast − Day-ahead A01 RES forecast` over the next four delivery hours, including low/high range.
- KPI info popovers with formula, sign convention and timing logic.
- Revised outage and system-stress cards that do not waste a full chart area when ENTSO-E returns no usable data.

ENTSO-E is not a push websocket feed. This app polls the API every 5 minutes by default and caches expensive fan-out requests locally.

## Fastest start: Docker

Requirements: Docker Desktop on Windows/macOS, or Docker Engine + Compose on Linux.

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set:

```text
ENTSOE_API_KEY=your_token_here
```

Then:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000
```

Stop with `Ctrl+C`. If desired afterwards:

```bash
docker compose down
```

## Run without Docker

Python 3.11+ recommended.

### macOS / Linux

```bash
cp .env.example .env
# edit .env, add token
./run.sh
```

### Windows PowerShell

```powershell
Copy-Item .env.example .env
# edit .env, add token
.\run.ps1
```

Then open `http://localhost:8000`.

## Controls

- **Delivery date**: inspect today or another delivery day.
- **Auto refresh**: polling on/off.
- **Refresh now**: bypasses the local cache.
- **Cross-border**: Total or a specific border; the Borders dropdown controls the aggregation scope.
- **Plotly**: zoom, pan, hover and legend trace toggles.
- **KPI info icon**: formula, sign logic, timing and interpretation.

## Configuration

`.env` supports:

```text
ENTSOE_API_KEY=...
ENTSOE_ENDPOINT_URL=https://web-api.tp.entsoe.eu/api
ENTSOE_REFRESH_SECONDS=300
ENTSOE_CACHE_SECONDS=240
ENTSOE_HTTP_TIMEOUT=35
PORT=8000
```

The API token is read only by the backend. It is never sent to browser JavaScript.

## ENTSO-E data choices

- Wind & solar forecasts: **A69** with Current **A18**, Intraday **A40**, Day-ahead **A01**
- Actual renewable generation: **A75 / A16**
- Load actual / forecast: **A65 / A16 + A01**
- Physical cross-border flows: **A11**
- Day-ahead scheduled exchanges: **A09 / A01 contract**
- Production/generation unavailability: **A77 + A80**
- Activated balancing: **A83**, aFRR **A96**, mFRR **A97**
- Imbalance prices: **A85**
- Imbalance volumes: **A86**

The consolidated RES totals only sum timestamps where Solar + Onshore + Offshore are all present. A missing component is never silently treated as zero.

For A83/A85/A86, the backend queries German control areas and uses DE/DE-LU fallbacks where appropriate. ENTSO-E does not publish every balancing item for every German scope/day; the UI reports availability explicitly. ZIP responses from A85/A86 are parsed natively, and duplicate document revisions are de-duplicated before aggregation.

## KPI definitions

- **RES forecast error** = actual RES − freshest complete RES forecast for the same MTU.
- **Next 4h RES revision** = average current RES forecast − day-ahead RES forecast for the next four delivery hours.
- **Residual load** = actual load − actual RES.
- **Residual surprise** shown below the residual KPI = actual residual load − day-ahead residual forecast.
- **Net physical import** = physical inflows to DE-LU − physical outflows over the selected borders.
- **Unavailable capacity** = reportable A77/A80 unavailable MW active at the reference time.
- **System stress** prefers A86 total imbalance volume (MWh per ISP/MTU); if unavailable it falls back to A83 net activated aFRR+mFRR (MW). Panel 5 keeps A86 and A83 on separate charts because they have different physical units. A85 prices are displayed separately in Panel 5.

## Tests

From the project folder:

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

The included tests cover the XML/ZIP parsers, forecast-vintage separation, complete RES aggregation, KPI change windows and system-stress source precedence.

## Operational note

This is a strategic monitoring dashboard, not a settlement-grade or automated trading system. ENTSO-E data can be delayed, revised or absent. Before using it for automated decisions, add persistent storage, source redundancy, quality alarms and historical calibration.

## Deploy to the web (Render)

This distribution includes a `render.yaml` Blueprint and a Dockerfile that honors the hosting provider's `PORT` environment variable. It also supports optional HTTP Basic authentication via `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`.

For the complete deployment walkthrough, see `DEPLOY-RENDER.md`.

### Responsive/mobile behavior

The dashboard adapts by viewport width rather than user-agent sniffing. CSS media queries switch the grid, controls, KPI cards, tables, tooltips, touch targets and chart heights for tablets and phones. Plotly is responsive and uses reduced margins/modebar behavior on narrow screens.
