from __future__ import annotations

import base64
import hmac
import io
import json
import math
import os
import statistics
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

BERLIN = ZoneInfo("Europe/Berlin")
UTC = timezone.utc
ENDPOINT = os.getenv("ENTSOE_ENDPOINT_URL", "https://web-api.tp.entsoe.eu/api")
API_KEY = os.getenv("ENTSOE_API_KEY", "").strip()
HTTP_TIMEOUT = int(os.getenv("ENTSOE_HTTP_TIMEOUT", "35"))
REFRESH_SECONDS = int(os.getenv("ENTSOE_REFRESH_SECONDS", "300"))
CACHE_SECONDS = int(os.getenv("ENTSOE_CACHE_SECONDS", "240"))
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
AUTH_ENABLED = bool(DASHBOARD_USERNAME and DASHBOARD_PASSWORD)

AREAS = {
    "DE": "10Y1001A1001A83F",
    "DE_LU": "10Y1001A1001A82H",
    "AT": "10YAT-APG------L",
    "BE": "10YBE----------2",
    "CH": "10YCH-SWISSGRIDZ",
    "CZ": "10YCZ-CEPS-----N",
    "DK_1": "10YDK-1--------W",
    "DK_2": "10YDK-2--------M",
    "FR": "10YFR-RTE------C",
    "NL": "10YNL----------L",
    "NO_2": "10YNO-2--------T",
    "PL": "10YPL-AREA-----S",
    "SE_4": "10Y1001A1001A47J",
    # German control areas, useful for balancing
    "50HERTZ": "10YDE-VE-------2",
    "AMPRION": "10YDE-RWENET---I",
    "TENNET_DE": "10YDE-EON------1",
    "TRANSNETBW": "10YDE-ENBW-----N",
}

PSR = {"B16": "Solar", "B18": "Wind Offshore", "B19": "Wind Onshore"}
ALL_NEIGHBORS = ["FR", "NL", "BE", "DK_1", "DK_2", "AT", "CH", "CZ", "PL", "SE_4", "NO_2"]
DEFAULT_NEIGHBORS = list(ALL_NEIGHBORS)
BALANCING_AREAS = ["50HERTZ", "AMPRION", "TENNET_DE", "TRANSNETBW"]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "entsoe-desk/1.0 (+local dashboard)"})


class TTLCache:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._d.get(key)
            if not item:
                return None
            expires, value = item
            if time.time() >= expires:
                self._d.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: int) -> Any:
        with self._lock:
            self._d[key] = (time.time() + ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


CACHE = TTLCache()
CACHE_LOCKS: dict[str, threading.Lock] = {}
CACHE_LOCKS_GUARD = threading.Lock()


def local_name(tag: str) -> str:
    return tag.split("}")[-1].lower()


def text_of(elem: ET.Element, *names: str) -> str | None:
    wanted = {n.lower() for n in names}
    for node in elem.iter():
        if local_name(node.tag) in wanted and node.text:
            return node.text.strip()
    return None


def elements(elem: ET.Element, name: str):
    target = name.lower()
    for node in elem.iter():
        if local_name(node.tag) == target:
            yield node


def parse_iso_duration(value: str | None) -> timedelta:
    if not value:
        return timedelta(minutes=15)
    value = value.upper()
    if value == "PT15M":
        return timedelta(minutes=15)
    if value == "PT30M":
        return timedelta(minutes=30)
    if value in ("PT60M", "PT1H"):
        return timedelta(hours=1)
    if value.startswith("PT") and value.endswith("M"):
        return timedelta(minutes=float(value[2:-1]))
    if value.startswith("PT") and value.endswith("H"):
        return timedelta(hours=float(value[2:-1]))
    return timedelta(minutes=15)


def parse_dt(value: str) -> datetime:
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def xml_documents(content: bytes) -> list[bytes]:
    if content[:2] == b"PK":
        out: list[bytes] = []
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(".xml"):
                    out.append(zf.read(name))
        return out
    return [content]


def safe_error_text(content: bytes) -> str:
    try:
        root = ET.fromstring(content)
        for node in root.iter():
            if local_name(node.tag) == "text" and node.text:
                return node.text.strip()
    except Exception:
        pass
    return content[:500].decode("utf-8", "ignore").strip()


def day_bounds(day: str | None) -> tuple[datetime, datetime, Date]:
    d = Date.fromisoformat(day) if day else datetime.now(BERLIN).date()
    start = datetime(d.year, d.month, d.day, tzinfo=BERLIN)
    end = start + timedelta(days=1)
    return start, end, d


def entsoe_request(params: dict[str, Any], start: datetime, end: datetime) -> bytes:
    if not API_KEY:
        raise RuntimeError("ENTSOE_API_KEY fehlt. Lege ihn in .env ab.")
    payload = dict(params)
    payload.update(
        {
            "securityToken": API_KEY,
            "periodStart": start.astimezone(UTC).strftime("%Y%m%d%H00"),
            "periodEnd": end.astimezone(UTC).strftime("%Y%m%d%H00"),
        }
    )
    try:
        r = SESSION.get(ENDPOINT, params=payload, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"ENTSO-E Netzwerkfehler: {e}") from e
    if r.status_code >= 400:
        msg = safe_error_text(r.content) or f"HTTP {r.status_code}"
        msg = msg.replace(API_KEY, "***")
        raise RuntimeError(f"ENTSO-E API: {msg}")
    # Since 2025 ENTSO-E sometimes returns HTTP 200 for no-data messages.
    ctype = r.headers.get("content-type", "")
    if "xml" in ctype and b"No matching data found" in r.content:
        raise LookupError("No matching data found")
    return r.content


def parse_timeseries(content: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in xml_documents(content):
        try:
            root = ET.fromstring(doc)
        except ET.ParseError:
            continue
        doc_created = text_of(root, "createdDateTime", "createddatetime")
        revision = text_of(root, "revisionNumber", "revisionnumber")
        for ts in elements(root, "timeseries"):
            psr_type = text_of(ts, "psrType", "psrtype")
            business_type = text_of(ts, "businessType", "businesstype")
            flow_direction = text_of(ts, "flowDirection.direction", "flowdirection.direction")
            in_domain = text_of(ts, "in_Domain.mRID", "in_domain.mrid", "inBiddingZone_Domain.mRID", "inbiddingzone_domain.mrid")
            out_domain = text_of(ts, "out_Domain.mRID", "out_domain.mrid", "outBiddingZone_Domain.mRID", "outbiddingzone_domain.mrid")
            is_consumption = any(local_name(n.tag) == "outbiddingzone_domain.mrid" for n in ts.iter())
            for period in [n for n in ts.iter() if local_name(n.tag) == "period"]:
                start_txt = text_of(period, "start", "timeInterval.start", "timeinterval.start")
                resolution_txt = text_of(period, "resolution")
                if not start_txt:
                    continue
                pstart = parse_dt(start_txt)
                step = parse_iso_duration(resolution_txt)
                for point in [n for n in period.iter() if local_name(n.tag) == "point"]:
                    pos_txt = text_of(point, "position")
                    if not pos_txt:
                        continue
                    value_txt = text_of(
                        point,
                        "quantity",
                        "price.amount",
                        "imbalance_Price.amount",
                        "imbalance_price.amount",
                        "activation_Price.amount",
                        "activation_price.amount",
                    )
                    if value_txt is None:
                        continue
                    try:
                        value = float(value_txt.replace(",", ""))
                        pos = int(pos_txt)
                    except ValueError:
                        continue
                    ts_utc = pstart + (pos - 1) * step
                    category = text_of(
                        point,
                        "imbalance_Price.category",
                        "imbalance_price.category",
                        "price.category",
                    )
                    rows.append(
                        {
                            "ts": ts_utc.astimezone(BERLIN),
                            "value": value,
                            "psr": psr_type,
                            "business": business_type,
                            "direction": flow_direction,
                            "category": category,
                            "in_domain": in_domain,
                            "out_domain": out_domain,
                            "resolution": resolution_txt,
                            "created": doc_created,
                            "revision": revision,
                            "consumption": is_consumption,
                        }
                    )
    return rows


def series(rows: list[dict[str, Any]], psr: str | None = None, consumption: bool | None = None) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for r in rows:
        if psr and r.get("psr") != psr:
            continue
        if consumption is not None and bool(r.get("consumption")) != consumption:
            continue
        out[r["ts"]] = float(r["value"])
    return out


def flow_series(rows: list[dict[str, Any]]) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    for r in rows:
        out[r["ts"]] = float(r["value"])
    return out


def as_points(s: dict[datetime, float]) -> list[dict[str, Any]]:
    return [{"t": k.isoformat(), "v": round(v, 3)} for k, v in sorted(s.items())]


def add_series(*items: dict[datetime, float]) -> dict[datetime, float]:
    keys = set().union(*(x.keys() for x in items)) if items else set()
    out: dict[datetime, float] = {}
    for k in keys:
        vals = [x.get(k) for x in items]
        if any(v is not None for v in vals):
            out[k] = sum(v or 0.0 for v in vals)
    return out


def add_series_complete(*items: dict[datetime, float]) -> dict[datetime, float]:
    """Sum only timestamps present in every input series.

    For the consolidated RES chart we do not want a missing Solar/Onshore/Offshore
    component to be silently treated as zero.
    """
    if not items or any(not item for item in items):
        return {}
    keys = set(items[0])
    for item in items[1:]:
        keys &= set(item)
    return {k: sum(item[k] for item in items) for k in keys}


def subtract_series(a: dict[datetime, float], b: dict[datetime, float]) -> dict[datetime, float]:
    keys = set(a) & set(b)
    return {k: a[k] - b[k] for k in keys}


def latest_point(s: dict[datetime, float], now: datetime | None = None) -> tuple[datetime, float] | None:
    if not s:
        return None
    now = now or datetime.now(BERLIN)
    candidates = [(k, v) for k, v in s.items() if k <= now]
    if not candidates:
        return None
    return max(candidates, key=lambda kv: kv[0])


def latest_before(s: dict[datetime, float], now: datetime | None = None) -> float | None:
    point = latest_point(s, now)
    return point[1] if point else None


def max_created(rows: list[dict[str, Any]]) -> str | None:
    """Latest document creation timestamp exposed by ENTSO-E, if present."""
    vals: list[datetime] = []
    for r in rows:
        raw = r.get("created")
        if not raw:
            continue
        try:
            vals.append(parse_dt(raw))
        except Exception:
            continue
    return max(vals).astimezone(BERLIN).isoformat() if vals else None


def latest_timestamp(s: dict[datetime, float], now: datetime | None = None) -> str | None:
    point = latest_point(s, now)
    return point[0].isoformat() if point else None


def point_at_or_before(
    s: dict[datetime, float], target: datetime, tolerance: timedelta = timedelta(minutes=20)
) -> tuple[datetime, float] | None:
    candidates = [(k, v) for k, v in s.items() if k <= target]
    if not candidates:
        return None
    point = max(candidates, key=lambda kv: kv[0])
    if target - point[0] > tolerance:
        return None
    return point


def change_windows(
    s: dict[datetime, float], as_of: datetime | None = None, windows: tuple[int, ...] = (15, 30, 60)
) -> dict[str, float | None]:
    """Change versus approximately 15/30/60 minutes earlier.

    We require a nearby historical MTU instead of silently comparing a 15-minute
    metric with a point several hours old when a source is sparse or delayed.
    """
    ref = latest_point(s, as_of)
    if not ref:
        return {f"d{m}_mw": None for m in windows}
    ref_t, ref_v = ref
    out: dict[str, float | None] = {}
    for minutes in windows:
        prev = point_at_or_before(s, ref_t - timedelta(minutes=minutes))
        out[f"d{minutes}_mw"] = round(ref_v - prev[1], 3) if prev else None
    return out


def mean_series(rows: list[dict[str, Any]], category: str | None = None) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = {}
    for r in rows:
        if category is not None and r.get("category") != category:
            continue
        buckets.setdefault(r["ts"], []).append(float(r["value"]))
    return {t: float(statistics.mean(vals)) for t, vals in buckets.items() if vals}


def latest_revision_rows(rows: list[dict[str, Any]], identity_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Keep only the latest ENTSO-E revision for each logical time-series point."""
    chosen: dict[tuple[Any, ...], tuple[tuple[int, datetime], dict[str, Any]]] = {}
    for r in rows:
        try:
            rev = int(r.get("revision") or 0)
        except (TypeError, ValueError):
            rev = 0
        try:
            created = parse_dt(r.get("created")) if r.get("created") else datetime.min.replace(tzinfo=UTC)
        except Exception:
            created = datetime.min.replace(tzinfo=UTC)
        key = tuple(r.get(field) for field in identity_fields)
        rank = (rev, created)
        if key not in chosen or rank >= chosen[key][0]:
            chosen[key] = (rank, r)
    return [item[1] for item in chosen.values()]


def signed_quantity_series(rows: list[dict[str, Any]]) -> dict[datetime, float]:
    """Aggregate quantities using ENTSO-E flow direction convention.

    A01 is positive / in, A02 negative / out, A03 symmetric/positive.
    """
    out: dict[datetime, float] = {}
    for r in rows:
        sign = 1.0 if r.get("direction") in (None, "A01", "A03") else -1.0 if r.get("direction") == "A02" else 1.0
        out[r["ts"]] = out.get(r["ts"], 0.0) + sign * float(r["value"])
    return out


def cached(key: str, ttl: int, force: bool, fn):
    if not force:
        hit = CACHE.get(key)
        if hit is not None:
            return hit
    with CACHE_LOCKS_GUARD:
        lock = CACHE_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if not force:
            hit = CACHE.get(key)
            if hit is not None:
                return hit
        value = fn()
        return CACHE.set(key, value, ttl)


def fetch_renewables(day: str | None, force: bool = False) -> dict[str, Any]:
    start, end, d = day_bounds(day)
    key = f"renewables:v4:{d.isoformat()}"

    def maybe_forecast(process_type: str) -> list[dict[str, Any]]:
        try:
            content = entsoe_request(
                {"documentType": "A69", "processType": process_type, "in_Domain": AREAS["DE"]},
                start,
                end,
            )
            return parse_timeseries(content)
        except (LookupError, RuntimeError):
            return []

    def work():
        actual_b = entsoe_request(
            {"documentType": "A75", "processType": "A16", "in_Domain": AREAS["DE"]},
            start,
            end,
        )
        actual_rows = parse_timeseries(actual_b)

        # ENTSO-E 14.1.D process types:
        # A01 = fixed day-ahead snapshot (18:00 D-1)
        # A40 = fixed intraday snapshot (08:00 D)
        # A18 = current / latest updated forecast
        da_rows = maybe_forecast("A01")
        intraday_rows = maybe_forecast("A40")
        current_rows = maybe_forecast("A18")

        payload: dict[str, Any] = {
            "date": d.isoformat(),
            "series": {},
            "updated": datetime.now(BERLIN).isoformat(),
            "forecast_definitions": {
                "day_ahead": "A01 · fixed forecast at 18:00 D-1",
                "intraday": "A40 · fixed forecast at 08:00 delivery day",
                "current": "A18 · latest available forecast update",
            },
        }

        actual_parts: list[dict[datetime, float]] = []
        da_parts: list[dict[datetime, float]] = []
        intraday_parts: list[dict[datetime, float]] = []
        current_parts: list[dict[datetime, float]] = []

        for code, name in PSR.items():
            actual = series(actual_rows, code, consumption=False)
            day_ahead = series(da_rows, code)
            intraday = series(intraday_rows, code)
            current = series(current_rows, code)

            payload["series"][f"{name} Actual"] = as_points(actual)
            payload["series"][f"{name} Current"] = as_points(current)
            payload["series"][f"{name} Intraday"] = as_points(intraday)
            payload["series"][f"{name} Day-ahead"] = as_points(day_ahead)

            live_forecast = current or intraday or day_ahead
            payload["series"][f"{name} Forecast"] = as_points(live_forecast)

            actual_parts.append(actual)
            da_parts.append(day_ahead)
            intraday_parts.append(intraday)
            current_parts.append(current)

        res_actual = add_series_complete(*actual_parts)
        res_da = add_series_complete(*da_parts)
        res_intraday = add_series_complete(*intraday_parts)
        res_current = add_series_complete(*current_parts)
        res_live = res_current or res_intraday or res_da
        miss = subtract_series(res_actual, res_live)
        forecast_revision = subtract_series(res_current, res_da)

        payload["series"].update(
            {
                "RES Actual": as_points(res_actual),
                "RES Current": as_points(res_current),
                "RES Intraday": as_points(res_intraday),
                "RES Day-ahead": as_points(res_da),
                "RES Forecast": as_points(res_live),
                "RES Forecast Error": as_points(miss),
                "RES Forecast Revision": as_points(forecast_revision),
            }
        )
        basis = "current" if res_current else "intraday" if res_intraday else "day-ahead" if res_da else None
        miss_point = latest_point(miss)
        basis_rows = current_rows if basis == "current" else intraday_rows if basis == "intraday" else da_rows

        now = datetime.now(BERLIN)
        next4: dict[datetime, float] = {}
        if d == now.date() and res_current and res_da:
            next4 = {t: v for t, v in forecast_revision.items() if now <= t < min(end, now + timedelta(hours=4))}
        revision_avg = statistics.mean(next4.values()) if next4 else None

        payload["kpi"] = {
            "res_error_mw": miss_point[1] if miss_point else None,
            "as_of": miss_point[0].isoformat() if miss_point else None,
            "forecast_basis": basis,
            "forecast_issued_at": max_created(basis_rows),
            "changes": change_windows(miss),
            "next4h_revision_avg_mw": round(revision_avg, 3) if revision_avg is not None else None,
            "next4h_revision_min_mw": round(min(next4.values()), 3) if next4 else None,
            "next4h_revision_max_mw": round(max(next4.values()), 3) if next4 else None,
            "next4h_points": len(next4),
            "next4h_window_start": min(next4).isoformat() if next4 else None,
            "next4h_window_end": (max(next4) + timedelta(minutes=15)).isoformat() if next4 else None,
        }
        payload["freshness"] = {
            "actual_through": latest_timestamp(res_actual),
            "current_forecast_issued_at": max_created(current_rows),
        }
        return payload

    return cached(key, CACHE_SECONDS, force, work)


def fetch_load(day: str | None, force: bool = False) -> dict[str, Any]:
    start, end, d = day_bounds(day)
    key = f"load:v4:{d.isoformat()}"

    def work():
        actual_b = entsoe_request(
            {"documentType": "A65", "processType": "A16", "outBiddingZone_Domain": AREAS["DE"], "out_Domain": AREAS["DE"]},
            start,
            end,
        )
        forecast_b = entsoe_request(
            {"documentType": "A65", "processType": "A01", "outBiddingZone_Domain": AREAS["DE"]}, start, end
        )
        actual = series(parse_timeseries(actual_b))
        forecast = series(parse_timeseries(forecast_b))
        ren = fetch_renewables(d.isoformat(), force=force)
        rs = ren["series"]
        res_actual = {parse_dt(p["t"]): p["v"] for p in rs.get("RES Actual", [])}
        res_da = {parse_dt(p["t"]): p["v"] for p in rs.get("RES Day-ahead", [])}
        residual_actual = subtract_series(actual, res_actual)
        residual_da = subtract_series(forecast, res_da)
        surprise = subtract_series(residual_actual, residual_da)
        rp = latest_point(residual_actual)
        sp = latest_point(surprise)
        return {
            "date": d.isoformat(),
            "updated": datetime.now(BERLIN).isoformat(),
            "series": {
                "Load Actual": as_points(actual),
                "Load Forecast": as_points(forecast),
                "Residual Load Actual": as_points(residual_actual),
                "Residual Load Forecast": as_points(residual_da),
                "Residual Load Surprise": as_points(surprise),
            },
            "kpi": {
                "residual_load_mw": rp[1] if rp else None,
                "as_of": rp[0].isoformat() if rp else None,
                "residual_surprise_mw": sp[1] if sp else None,
                "surprise_as_of": sp[0].isoformat() if sp else None,
                "forecast_basis": "day-ahead load − day-ahead RES",
                "changes": change_windows(residual_actual),
            },
            "freshness": {"actual_through": latest_timestamp(actual)},
        }

    return cached(key, CACHE_SECONDS, force, work)


def _one_flow(doc_type: str, source: str, dest: str, start: datetime, end: datetime, contract: str | None = None) -> dict[datetime, float]:
    params = {"documentType": doc_type, "in_Domain": AREAS[dest], "out_Domain": AREAS[source]}
    if contract:
        params["contract_MarketAgreement.Type"] = contract
    try:
        return flow_series(parse_timeseries(entsoe_request(params, start, end)))
    except Exception:
        return {}


def fetch_borders(day: str | None, neighbors: list[str], force: bool = False) -> dict[str, Any]:
    start, end, d = day_bounds(day)
    neighbors = [n for n in neighbors if n in ALL_NEIGHBORS]
    if not neighbors:
        neighbors = DEFAULT_NEIGHBORS
    key = f"borders:v4:{d.isoformat()}:{','.join(neighbors)}"

    def work():
        result: dict[str, Any] = {"date": d.isoformat(), "updated": datetime.now(BERLIN).isoformat(), "borders": {}, "series": {}}
        tasks = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for n in neighbors:
                for metric, doc, contract in (("physical", "A11", None), ("scheduled", "A09", "A01")):
                    tasks[pool.submit(_one_flow, doc, n, "DE_LU", start, end, contract)] = (n, metric, "import")
                    tasks[pool.submit(_one_flow, doc, "DE_LU", n, start, end, contract)] = (n, metric, "export")
            temp: dict[tuple[str, str, str], dict[datetime, float]] = {}
            for fut in as_completed(tasks):
                temp[tasks[fut]] = fut.result()

        totals_phys: dict[datetime, float] = {}
        totals_sched: dict[datetime, float] = {}
        for n in neighbors:
            imp_p = temp.get((n, "physical", "import"), {})
            exp_p = temp.get((n, "physical", "export"), {})
            imp_s = temp.get((n, "scheduled", "import"), {})
            exp_s = temp.get((n, "scheduled", "export"), {})
            net_p = {k: imp_p.get(k, 0.0) - exp_p.get(k, 0.0) for k in set(imp_p) | set(exp_p)}
            net_s = {k: imp_s.get(k, 0.0) - exp_s.get(k, 0.0) for k in set(imp_s) | set(exp_s)}
            result["borders"][n] = {"physical": as_points(net_p), "scheduled": as_points(net_s)}
            totals_phys = add_series(totals_phys, net_p)
            totals_sched = add_series(totals_sched, net_s)
        result["series"]["Net Physical Import"] = as_points(totals_phys)
        result["series"]["Net DA Schedule"] = as_points(totals_sched)
        flow_delta = subtract_series(totals_phys, totals_sched)
        fp = latest_point(totals_phys)
        dp = latest_point(flow_delta)
        result["kpi"] = {
            "net_import_mw": fp[1] if fp else None,
            "as_of": fp[0].isoformat() if fp else None,
            "vs_da_schedule_mw": dp[1] if dp else None,
            "selected_borders": neighbors,
            "changes": change_windows(totals_phys),
        }
        result["freshness"] = {"physical_through": latest_timestamp(totals_phys)}
        return result

    return cached(key, max(CACHE_SECONDS, 600), force, work)


def _parse_outage_docs(content: bytes, zone: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in xml_documents(content):
        try:
            root = ET.fromstring(doc)
        except ET.ParseError:
            continue
        created = text_of(root, "createdDateTime", "createddatetime")
        docstatus = text_of(root, "value")
        for ts in elements(root, "timeseries"):
            business = text_of(ts, "businessType", "businesstype")
            plant = text_of(ts, "production_RegisteredResource.name", "production_registeredresource.name", "registeredResource.name", "registeredresource.name") or "Unknown unit"
            psr = text_of(ts, "psrType", "psrtype", "production_RegisteredResource.pSRType.psrType", "production_registeredresource.psrtype.psrtype")
            nominal_txt = text_of(ts, "nominalP", "nominalp")
            nominal = float(nominal_txt) if nominal_txt and nominal_txt.replace('.', '', 1).isdigit() else None
            for period in [n for n in ts.iter() if local_name(n.tag) == "available_period"]:
                start_txt = text_of(period, "start")
                end_txt = text_of(period, "end")
                res_txt = text_of(period, "resolution")
                if not start_txt or not end_txt:
                    continue
                pstart, pend = parse_dt(start_txt), parse_dt(end_txt)
                step = parse_iso_duration(res_txt)
                pts = [n for n in period.iter() if local_name(n.tag) == "point"]
                for i, point in enumerate(pts):
                    pos_txt = text_of(point, "position")
                    qty_txt = text_of(point, "quantity")
                    if not pos_txt or qty_txt is None:
                        continue
                    try:
                        pos, available = int(pos_txt), float(qty_txt)
                    except ValueError:
                        continue
                    seg_start = pstart + (pos - 1) * step
                    if i + 1 < len(pts):
                        next_pos = int(text_of(pts[i + 1], "position") or pos + 1)
                        seg_end = pstart + (next_pos - 1) * step
                    else:
                        seg_end = pend
                    unavailable = max(0.0, (nominal or available) - available) if nominal is not None else None
                    out.append({
                        "zone": zone,
                        "start": seg_start.astimezone(BERLIN),
                        "end": seg_end.astimezone(BERLIN),
                        "available": available,
                        "nominal": nominal,
                        "unavailable": unavailable,
                        "plant": plant,
                        "psr": psr,
                        "business": business,
                        "created": created,
                        "docstatus": docstatus,
                    })
    return out


def fetch_outages(day: str | None, force: bool = False) -> dict[str, Any]:
    start, end, d = day_bounds(day)
    zones = ["DE_LU", "FR", "NL", "BE"]
    key = f"outages:v4:{d.isoformat()}"

    def work():
        all_rows: list[dict[str, Any]] = []
        errors: list[str] = []
        no_data: list[str] = []
        source_status: dict[str, dict[str, str]] = {z: {"A77": "pending", "A80": "pending"} for z in zones}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {}
            for z in zones:
                for doc in ("A80", "A77"):
                    futs[pool.submit(entsoe_request, {"documentType": doc, "biddingZone_domain": AREAS[z], "offset": 0}, start, end)] = (z, doc)
            for fut in as_completed(futs):
                z, doc = futs[fut]
                try:
                    parsed = _parse_outage_docs(fut.result(), z)
                    all_rows.extend(parsed)
                    source_status[z][doc] = "ok" if parsed else "empty"
                except LookupError:
                    no_data.append(f"{z}:{doc}")
                    source_status[z][doc] = "no_data"
                except Exception as e:
                    errors.append(f"{z}:{doc}: {e}")
                    source_status[z][doc] = "error"

        grid = [start + timedelta(minutes=15 * i) for i in range(int((end - start).total_seconds() // 900))]
        by_zone = {z: {} for z in zones}
        for z in zones:
            zr = [r for r in all_rows if r["zone"] == z and r.get("unavailable") is not None]
            for t in grid:
                by_zone[z][t] = sum(float(r["unavailable"]) for r in zr if r["start"] <= t < r["end"])
        total_series = add_series_complete(*(by_zone[z] for z in zones)) if zones else {}

        now = datetime.now(BERLIN)
        if d < now.date():
            ref = end - timedelta(minutes=15)
        elif d > now.date():
            ref = start
        else:
            ref = now

        active_rows = [
            r for r in all_rows
            if r.get("unavailable") is not None and r["start"] <= ref < r["end"] and float(r["unavailable"] or 0) > 0
        ]
        upcoming_rows = [
            r for r in all_rows
            if r.get("unavailable") is not None and r["start"] > ref and float(r["unavailable"] or 0) > 0
        ]
        display_rows = sorted(
            active_rows + upcoming_rows,
            key=lambda r: (0 if r in active_rows else 1, r["start"], -float(r.get("unavailable") or 0)),
        )
        top = sorted(
            [r for r in all_rows if r.get("unavailable") is not None and float(r.get("unavailable") or 0) > 0],
            key=lambda r: float(r.get("unavailable") or 0),
            reverse=True,
        )[:12]

        current_total = sum(float(r["unavailable"]) for r in active_rows)
        hard_failure = bool(errors) and not all_rows and len(errors) + len(no_data) >= len(zones) * 2
        largest_active = max(active_rows, key=lambda r: float(r.get("unavailable") or 0), default=None)
        next_event = min(upcoming_rows, key=lambda r: r["start"], default=None)

        return {
            "date": d.isoformat(),
            "updated": datetime.now(BERLIN).isoformat(),
            "series": {z: as_points(by_zone[z]) for z in zones},
            "total_series": as_points(total_series),
            "top": [
                {
                    "zone": r["zone"], "plant": r["plant"], "psr": r["psr"],
                    "unavailable_mw": round(float(r["unavailable"] or 0), 1),
                    "start": r["start"].isoformat(), "end": r["end"].isoformat(), "business": r["business"],
                    "active": r in active_rows,
                }
                for r in display_rows[:12]
            ],
            "kpi": {
                "unavailable_mw": None if hard_failure else round(current_total, 1),
                "as_of": ref.isoformat(),
                "scope": "A77+A80 · DE-LU + FR + NL + BE",
                "reportable_events": len(top),
                "active_events": len(active_rows),
                "largest_active_mw": round(float(largest_active["unavailable"]), 1) if largest_active else None,
                "largest_active_unit": largest_active["plant"] if largest_active else None,
                "next_event_at": next_event["start"].isoformat() if next_event else None,
                "next_event_mw": round(float(next_event["unavailable"]), 1) if next_event else None,
                "next_event_unit": next_event["plant"] if next_event else None,
                "changes": change_windows(total_series, ref),
            },
            "source_status": source_status,
            "errors": errors,
            "no_data": no_data,
        }

    return cached(key, max(CACHE_SECONDS, 900), force, work)


def _query_control_area_document(
    document_type: str,
    area: str,
    start: datetime,
    end: datetime,
    extra: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    params: dict[str, Any] = {"documentType": document_type, "controlArea_Domain": AREAS[area]}
    if extra:
        params.update(extra)
    try:
        rows = parse_timeseries(entsoe_request(params, start, end))
        for r in rows:
            r["source_area"] = area
        return rows, "ok" if rows else "empty"
    except LookupError:
        return [], "no_data"
    except Exception:
        return [], "error"


def _query_balancing_doc_with_fallback(
    document_type: str, start: datetime, end: datetime
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Query German control areas first, then DE/DE-LU aggregate fallbacks."""
    statuses: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_query_control_area_document, document_type, area, start, end): area for area in BALANCING_AREAS}
        for fut in as_completed(futs):
            area = futs[fut]
            r, status = fut.result()
            statuses[area] = status
            rows.extend(r)
    if rows:
        return rows, statuses, "German control areas"

    for area in ("DE", "DE_LU"):
        r, status = _query_control_area_document(document_type, area, start, end)
        statuses[area] = status
        if r:
            return r, statuses, area
    return [], statuses, "none"


def fetch_balancing(day: str | None, force: bool = False) -> dict[str, Any]:
    start, end, d = day_bounds(day)
    key = f"system-stress:v4:{d.isoformat()}"

    def work():
        # A83 activated balancing energy; A96=aFRR, A97=mFRR.
        a83_rows: list[dict[str, Any]] = []
        a83_status: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {}
            for area in BALANCING_AREAS:
                for business in ("A96", "A97"):
                    futs[pool.submit(_query_control_area_document, "A83", area, start, end, {"businessType": business})] = (area, business)
            for fut in as_completed(futs):
                area, business = futs[fut]
                rows, status = fut.result()
                a83_status[f"{area}:{business}"] = status
                a83_rows.extend(rows)

        a83_rows = latest_revision_rows(a83_rows, ("source_area", "business", "direction", "ts"))
        afrr_rows = [r for r in a83_rows if r.get("business") == "A96"]
        mfrr_rows = [r for r in a83_rows if r.get("business") == "A97"]
        afrr = signed_quantity_series(afrr_rows)
        mfrr = signed_quantity_series(mfrr_rows)
        activation_net = add_series(afrr, mfrr)

        # A85/A86 are ZIP/XML endpoints. Germany may not publish every balancing
        # item on ENTSO-E; therefore source health is first-class UI information.
        price_rows, a85_status, a85_scope = _query_balancing_doc_with_fallback("A85", start, end)
        volume_rows, a86_status, a86_scope = _query_balancing_doc_with_fallback("A86", start, end)
        price_rows = latest_revision_rows(price_rows, ("source_area", "category", "ts"))
        volume_rows = latest_revision_rows(volume_rows, ("source_area", "business", "direction", "ts"))
        imbalance_volume = signed_quantity_series(volume_rows)

        categories = {r.get("category") for r in price_rows}
        price_long = mean_series(price_rows, "A04") if "A04" in categories else {}
        price_short = mean_series(price_rows, "A05") if "A05" in categories else {}
        uncategorized_rows = [r for r in price_rows if not r.get("category")]
        price_single = mean_series(uncategorized_rows) if uncategorized_rows else {}

        primary = imbalance_volume or activation_net
        # A86 is an energy volume (MWh per imbalance settlement period / MTU),
        # while legacy A83 activated balancing quantities are published in MW per
        # balancing time unit. Do not imply they share a physical unit.
        primary_basis = "A86 total imbalance volume" if imbalance_volume else "A83 net aFRR+mFRR activation" if activation_net else None
        primary_unit = "MWh" if imbalance_volume else "MW" if activation_net else None
        pp = latest_point(primary)

        def latest_val(s: dict[datetime, float]) -> float | None:
            p = latest_point(s)
            return p[1] if p else None

        def doc_state(rows: list[dict[str, Any]], statuses: dict[str, str]) -> str:
            if rows:
                return "ok"
            if any(v == "error" for v in statuses.values()):
                return "error"
            return "no_data"

        freshness_candidates = [
            latest_point(activation_net), latest_point(imbalance_volume), latest_point(price_single),
            latest_point(price_long), latest_point(price_short),
        ]
        freshness_points = [p for p in freshness_candidates if p]
        freshest = max(freshness_points, key=lambda p: p[0]) if freshness_points else None

        return {
            "date": d.isoformat(),
            "updated": datetime.now(BERLIN).isoformat(),
            "series": {
                "aFRR net": as_points(afrr),
                "mFRR net": as_points(mfrr),
                "Net activation": as_points(activation_net),
                "Net imbalance volume": as_points(imbalance_volume),
                "Imbalance price": as_points(price_single),
                "Imbalance price long": as_points(price_long),
                "Imbalance price short": as_points(price_short),
            },
            "kpi": {
                # system_stress_value is intentionally unit-aware. Keep the old
                # field as a compatibility alias for older front-ends.
                "system_stress_value": pp[1] if pp else None,
                "system_stress_unit": primary_unit,
                "system_stress_mw": pp[1] if pp else None,
                "as_of": pp[0].isoformat() if pp else None,
                "basis": primary_basis,
                "changes": change_windows(primary),
                "net_activation_mw": latest_val(activation_net),
                "imbalance_volume_mwh": latest_val(imbalance_volume),
                "imbalance_volume_mw": latest_val(imbalance_volume),
                "imbalance_price_eur_mwh": latest_val(price_single),
                "imbalance_price_long_eur_mwh": latest_val(price_long),
                "imbalance_price_short_eur_mwh": latest_val(price_short),
            },
            "freshness": {
                "latest_through": freshest[0].isoformat() if freshest else None,
                "activation_through": latest_timestamp(activation_net),
                "volume_through": latest_timestamp(imbalance_volume),
                "price_through": latest_timestamp(price_single or price_short or price_long),
            },
            "sources": {
                "A83": {"state": doc_state(a83_rows, a83_status), "label": "Activated balancing", "scope": "4 German control areas"},
                "A85": {"state": doc_state(price_rows, a85_status), "label": "Imbalance price", "scope": a85_scope},
                "A86": {"state": doc_state(volume_rows, a86_status), "label": "Imbalance volume", "scope": a86_scope},
            },
            "note": "System Stress combines ENTSO-E A83, A85 and A86 where published. A83 is shown in MW, A86 in MWh per ISP/MTU, and A85 in EUR/MWh. Missing source data is shown explicitly rather than rendered as zero.",
        }

    return cached(key, max(CACHE_SECONDS, 600), force, work)

app = FastAPI(
    title="ENTSO-E Desk",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def optional_basic_auth(request, call_next):
    """Protect the public dashboard when DASHBOARD_USERNAME/PASSWORD are set.

    /health stays unauthenticated so a hosting platform can perform health checks.
    """
    if not AUTH_ENABLED or request.url.path == "/health":
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    valid = False
    if auth.startswith("Basic "):
        try:
            raw = base64.b64decode(auth[6:], validate=True).decode("utf-8")
            username, password = raw.split(":", 1)
            valid = hmac.compare_digest(username, DASHBOARD_USERNAME) and hmac.compare_digest(
                password, DASHBOARD_PASSWORD
            )
        except (ValueError, UnicodeDecodeError):
            valid = False

    if not valid:
        return PlainTextResponse(
            "Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="ENTSO-E Desk"'},
        )
    return await call_next(request)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    html = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__REFRESH_SECONDS__", str(REFRESH_SECONDS)))


@app.get("/health")
def health():
    return {"ok": True, "token_configured": bool(API_KEY), "endpoint": ENDPOINT, "time": datetime.now(BERLIN).isoformat()}


def endpoint_guard(fn):
    try:
        return fn()
    except LookupError as e:
        return {"error": str(e), "series": {}, "updated": datetime.now(BERLIN).isoformat()}
    except Exception as e:
        msg = str(e).replace(API_KEY, "***") if API_KEY else str(e)
        raise HTTPException(status_code=502, detail=msg)


@app.get("/api/renewables")
def api_renewables(day: str | None = None, force: bool = False):
    return endpoint_guard(lambda: fetch_renewables(day, force))


@app.get("/api/load")
def api_load(day: str | None = None, force: bool = False):
    return endpoint_guard(lambda: fetch_load(day, force))


@app.get("/api/borders")
def api_borders(day: str | None = None, neighbors: str = Query(default=",".join(DEFAULT_NEIGHBORS)), force: bool = False):
    selected = [x.strip().upper() for x in neighbors.split(",") if x.strip()]
    return endpoint_guard(lambda: fetch_borders(day, selected, force))


@app.get("/api/outages")
def api_outages(day: str | None = None, force: bool = False):
    return endpoint_guard(lambda: fetch_outages(day, force))


@app.get("/api/balancing")
def api_balancing(day: str | None = None, force: bool = False):
    return endpoint_guard(lambda: fetch_balancing(day, force))


@app.post("/api/cache/clear")
def clear_cache():
    CACHE.clear()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
