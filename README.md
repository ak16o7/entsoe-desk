# ENTSO-E Desk v4.3

Browser-based short-term power-market monitor for Germany / Central Europe. The backend is FastAPI/Python, polls the ENTSO-E Transparency Platform Web API, caches fan-out requests server-side and renders a responsive Plotly dashboard.

## What v4.3 changes

v4.3 is primarily a data-quality hardening release.

1. **Renewables** — Solar, Wind Onshore, Wind Offshore and complete RES total. Actual generation is compared with ENTSO-E A18 (current/latest), the fixed A40 **08:00 delivery-day intraday snapshot**, and the fixed A01 **18:00 D-1 day-ahead snapshot**. Where available, the UI also shows the document creation timestamp as separate metadata. Scope: **DE Member State**.
2. **Load / residual load** — actual load and residual load against a consistent A01 day-ahead baseline. Scope: **DE Member State**.
3. **Cross-border** — physical DE-LU flows versus day-ahead schedules. Missing borders or missing MTUs are **not silently converted to 0 MW**. The Total KPI/trace is suppressed unless every selected border contributes data on the same timestamp. Scope: **DE-LU bidding zone**.
4. **Generation outages** — A80 generation-unit outages are primary. A77 production-unit outages are only a fallback when A80 explicitly has no data for a zone; A77 and A80 are never added together. Queries paginate the ENTSO-E 200-document pages, keep the latest document revision, suppress cancelled/withdrawn documents and suppress the numeric total when source coverage is incomplete.
5. **Balancing / imbalance** — the retired legacy A83 activation feed has been removed. Activated aFRR/mFRR now uses **GL EB 12.3.E / A24 Aggregated Balancing Energy Bids** with A51 (aFRR) and A47 (mFRR). A86 Total Imbalance Volume remains a separate MWh KPI and is never mixed with MW activation data. A85 prices remain separate.

The common ENTSO-E time-series parser also understands **curveType A03 variable-size blocks** and expands omitted positions by carrying the published block value forward to the next explicit point/end of period. That prevents artificial gaps/jumps in R3-migrated feeds.

## Public-hosting safeguards

The dashboard is public by default when `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` are unset.

- `ENTSOE_API_KEY` stays server-side.
- Public API endpoints no longer accept a `force=true` cache-bypass parameter.
- The old public cache-clear endpoint has been removed.
- `Refresh now` refreshes the browser view but respects the server cache (default 240 s).
- `/health` exposes only health/version/configured state, not token values or endpoint secrets.

Optional HTTP Basic Auth is still supported locally or on a host by manually adding both `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` environment variables.

## Run locally with Docker

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

or on macOS/Linux:

```bash
cp .env.example .env
```

Set at least:

```text
ENTSOE_API_KEY=your_token_here
```

Then:

```bash
docker compose up --build
```

Open `http://localhost:8000`.

## Run without Docker

Python 3.11+ is recommended.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
# edit .env
.\run.ps1
```

macOS/Linux:

```bash
cp .env.example .env
# edit .env
./run.sh
```

## Configuration

```text
ENTSOE_API_KEY=...
ENTSOE_ENDPOINT_URL=https://web-api.tp.entsoe.eu/api
ENTSOE_REFRESH_SECONDS=300
ENTSOE_CACHE_SECONDS=240
ENTSOE_CACHE_MAX_ENTRIES=256
ENTSOE_HTTP_TIMEOUT=35
ENTSOE_MAX_REQUESTS_PER_MINUTE=300
PORT=8000

# optional, only if you want Basic Auth
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=
```

## ENTSO-E data choices

- Renewable forecasts: A69 with A18 current/latest / A40 fixed 08:00 intraday snapshot / A01 fixed 18:00 D-1 day-ahead snapshot
- Actual renewable generation: A75 / A16
- Load actual / forecast: A65 / A16 + A01
- Physical cross-border flows: A11
- Day-ahead scheduled exchanges: A09 / A01 contract
- Generation-unit unavailability: A80 primary
- Production-unit unavailability: A77 fallback only
- Activated balancing energy: A24 / GL EB 12.3.E, A51 aFRR + A47 mFRR
- Imbalance prices: A85
- Total imbalance volume: A86

## KPI semantics

- **RES forecast error** = actual complete RES − freshest available complete RES forecast at the same MTU.
- **Next 4h RES revision** = current A18 RES forecast − A01 day-ahead RES forecast over the next four delivery hours.
- **Residual load** = actual load − actual RES.
- **Residual surprise** = actual residual load − A01 day-ahead residual forecast.
- **Net physical import** = selected physical inflows to DE-LU − physical outflows, but only when the selected-border total is complete.
- **Unavailable capacity** = selected reportable outage unavailable MW at the reference time. A numeric total is withheld if outage retrieval is incomplete.
- **System imbalance** = A86 Total Imbalance Volume in MWh. Positive/negative direction is shown as surplus/excess versus deficit according to the source direction convention.
- **Activated balancing** = separate 12.3.E aFRR/mFRR MW series; it is not a fallback for A86.

## Tests

From the project folder:

```bash
python -m unittest discover -s tests -v
```

v4.3 includes tests for A03 block expansion, forecast-process separation, complete RES aggregation, gap-safe border aggregation, outage cancellation/revision handling, A80-vs-A77 hierarchy handling, unique outage event counting, A24/12.3.E parsing, unit-stable A86 balancing KPIs and removal of public cache bypass controls.

## Deploy / upgrade on Render

See `DEPLOY-RENDER.md`.

## Responsive/mobile behavior

The site adapts to viewport width rather than trying to identify iPhone/Android user agents. CSS breakpoints, larger touch controls and responsive Plotly layouts cover phones, tablets, split-screen and orientation changes.

## Operational note

This is a monitoring dashboard, not a settlement-grade or automated trading system. ENTSO-E data can be delayed, revised or absent. v4.3 deliberately prefers **missing/partial** over a plausible-looking but unjustified zero or aggregate.
