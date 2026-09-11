# ENTSO-E Desk v4.3 – Render Deployment / Upgrade

This package is ready for the existing Render service.

## If v4.2 is already live

You do **not** need a new Render Blueprint or a new website URL. Replace/update the files in the same local Git repository and push them to the same `main` branch:

```powershell
git status
git add .
git commit -m "Upgrade ENTSO-E Desk to v4.3"
git push
```

Render should automatically deploy the new commit. Your existing `https://entsoe-desk.onrender.com/` URL stays the same.

After deployment, open Render → your `entsoe-desk` Web Service → **Events/Logs** and wait for the deploy to become live. Then hard-refresh the browser (`Ctrl+F5`) or open an InPrivate/Incognito window.

## Environment variables on Render

Required:

```text
ENTSOE_API_KEY=your ENTSO-E token
```

Recommended defaults are already in `render.yaml`:

```text
ENTSOE_ENDPOINT_URL=https://web-api.tp.entsoe.eu/api
ENTSOE_REFRESH_SECONDS=300
ENTSOE_CACHE_SECONDS=240
ENTSOE_CACHE_MAX_ENTRIES=256
ENTSOE_HTTP_TIMEOUT=35
ENTSOE_MAX_REQUESTS_PER_MINUTE=300
```

For a public site, **do not create** `DASHBOARD_USERNAME` or `DASHBOARD_PASSWORD`. If those variables still exist from an older deployment, delete them in Render → Web Service → Environment and redeploy.

Optional Basic Auth can still be enabled later by adding both variables manually.

## Security check before pushing

This distribution intentionally contains no `.env` file. Check:

```powershell
git ls-files .env
```

It must print nothing. `.env.example` is safe and should remain tracked.

## What changed operationally in v4.3

- Public `force=true` cache bypass was removed.
- Public `/api/cache/clear` was removed.
- `Refresh now` respects the server cache instead of hammering ENTSO-E.
- `/health` is a minimal Render health endpoint.
- The service retries transient 429/5xx network responses with bounded backoff.
- Outage requests paginate 200-document pages and suppress totals on incomplete retrieval.
- Cross-border totals are only shown when all selected borders have compatible MTUs.

## Verify the live deployment

After Render reports a successful deploy, verify:

1. `https://entsoe-desk.onrender.com/` opens without a password prompt.
2. The footer says **Desk v4.3**.
3. Panel 5 is titled **Balancing / imbalance**, not System stress.
4. The source chip is **12.3.E**, not the old A83 activation source.
5. Cross-border shows a coverage line such as `physical 11/11` or explicitly suppresses Total if incomplete.
6. Outages show A80/A77 status and selected source per zone; an incomplete source must not show a misleading 0 MW headline.
7. On a phone, the layout collapses to mobile cards and Plotly remains usable.

## Local test before push (optional)

```powershell
Copy-Item .env.example .env
# add ENTSOE_API_KEY to .env
python -m unittest discover -s tests -v
docker compose up --build
```

Open `http://localhost:8000`.

## Free Render limitation

A free Render Web Service can sleep after inactivity. The first request after sleep may therefore take noticeably longer. That is a hosting limitation, not an ENTSO-E data error.
