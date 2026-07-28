
"""
Park Pulse NYC — live-board endpoint (Vercel Python Function).
All logic consolidated into a single file because Vercel's Python
runtime only bundles the entrypoint file, not sibling modules.

Deployed URL once live: https://<your-vercel-project>.vercel.app/api/live_board
Query params (all optional):
  ?subway_line=L
  ?bus_route=B52
  ?ferry_route=AS
  ?borough=Brooklyn
"""
from __future__ import annotations

import os
import json
from datetime import date, datetime
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.request

import requests
import zipfile
import io
import csv
from icalendar import Calendar
from nyct_gtfs.compiled_gtfs import gtfs_realtime_pb2 
from nyct_gtfs import NYCTFeed


# ============================================================
# PARKING (Alternate Side Parking suspensions)
# ============================================================
ICS_URL_TEMPLATE = "https://www.nyc.gov/html/dot/downloads/misc/{year}-alternate-side.ics"


@dataclass
class Suspension:
    suspension_date: date
    holiday_name: str


def _fetch_ics(year: int, timeout: int = 10) -> bytes:
    url = ICS_URL_TEMPLATE.format(year=year)
    req = urllib.request.Request(url, headers={"User-Agent": "ParkPulseNYC/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_ics(ics_bytes: bytes) -> list[Suspension]:
    cal = Calendar.from_ical(ics_bytes)
    suspensions: list[Suspension] = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        dtstart = component.get("dtstart").dt
        if isinstance(dtstart, datetime):
            dtstart = dtstart.date()
        summary = str(component.get("summary", "ASP Suspended"))
        suspensions.append(Suspension(suspension_date=dtstart, holiday_name=summary))
    return suspensions


def _is_suspended_on(suspensions: list[Suspension], day: date) -> Suspension | None:
    for s in suspensions:
        if s.suspension_date == day:
            return s
    return None


def get_parking_status(borough: str | None = None) -> dict:
    try:
        today = date.today()
        ics_bytes = _fetch_ics(today.year)
        suspensions = _parse_ics(ics_bytes)
        today_suspension = _is_suspended_on(suspensions, today)

        return {
            "status": "ok",
            "date": today.isoformat(),
            "asp_suspended_today": today_suspension is not None,
            "reason": today_suspension.holiday_name if today_suspension else None,
            "message": (
                f"No alternate side parking today — {today_suspension.holiday_name}"
                if today_suspension
                else "Alternate side parking is in effect today"
            ),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error fetching parking data: {e}"}


# ============================================================
# SUBWAY
# ============================================================
@dataclass
class LineStatus:
    line: str
    has_delay: bool
    trains_underway: int


def _get_line_status(line: str) -> LineStatus:
    feed = NYCTFeed(line)
    trips = feed.filter_trips(line_id=line, underway=True)
    has_delay = any(trip.has_delay_alert for trip in trips)
    return LineStatus(line=line, has_delay=has_delay, trains_underway=len(trips))


def _get_line_status_message(status: LineStatus) -> str:
    if status.has_delay:
        return "Minor delays"
    if status.trains_underway == 0:
        return "No trains reported"
    return "Running on time"


def get_subway_status(line: str | None = None) -> dict:
    if not line:
        return {"status": "error", "message": "No subway line specified"}
    try:
        status = _get_line_status(line)
        return {
            "status": "ok",
            "line": status.line,
            "has_delay": status.has_delay,
            "trains_underway": status.trains_underway,
            "message": _get_line_status_message(status),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error fetching subway data: {e}"}


# ============================================================
# BUS
# ============================================================
TRIP_UPDATES_URL = "https://gtfsrt.prod.obanyc.com/tripUpdates"


@dataclass
class RouteStatus:
    route: str
    has_delay: bool
    trips_tracked: int
    avg_delay_minutes: float | None


def _fetch_trip_updates(api_key: str, timeout: int = 10) -> gtfs_realtime_pb2.FeedMessage:
    response = requests.get(TRIP_UPDATES_URL, params={"key": api_key}, timeout=timeout)
    response.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def _get_route_status(feed: gtfs_realtime_pb2.FeedMessage, route: str) -> RouteStatus:
    delays = []
    trips_for_route = 0
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_update = entity.trip_update
        if trip_update.trip.route_id != route:
            continue
        trips_for_route += 1
        if trip_update.HasField("delay") and trip_update.delay:
            delays.append(trip_update.delay / 60)

    has_delay = any(d > 3 for d in delays)
    avg_delay = round(sum(delays) / len(delays), 1) if delays else None
    return RouteStatus(
        route=route,
        has_delay=has_delay,
        trips_tracked=trips_for_route,
        avg_delay_minutes=avg_delay,
    )


def _get_route_status_message(status: RouteStatus) -> str:
    if status.trips_tracked == 0:
        return "No buses reported"
    if status.has_delay:
        return f"Minor delays (~{status.avg_delay_minutes} min)"
    return "Running on schedule"


def get_bus_status(route: str | None = None) -> dict:
    if not route:
        return {"status": "error", "message": "No bus route specified"}
    api_key = os.environ.get("OBA_API_KEY")
    if not api_key:
        return {"status": "error", "message": "Bus API key not configured yet"}
    try:
        feed = _fetch_trip_updates(api_key)
        status = _get_route_status(feed, route)
        return {
            "status": "ok",
            "route": status.route,
            "has_delay": status.has_delay,
            "trips_tracked": status.trips_tracked,
            "avg_delay_minutes": status.avg_delay_minutes,
            "message": _get_route_status_message(status),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error fetching bus data: {e}"}


# ============================================================
# FERRY
# ============================================================
TRIPUPDATE_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate"
ALERT_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/alert"


def _fetch_ferry_feed(url: str) -> gtfs_realtime_pb2.FeedMessage:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed
  
STATIC_GTFS_URL = "http://nycferry.connexionz.net/rtt/public/resource/gtfs.zip"
_ferry_trip_route_cache: dict = {}
_ferry_trip_route_cache_time: float = 0
FERRY_CACHE_TTL_SECONDS = 3600

def _get_ferry_trip_route_map() -> dict:
    global _ferry_trip_route_cache, _ferry_trip_route_cache_time
    now = datetime.now().timestamp()
    if _ferry_trip_route_cache and (now - _ferry_trip_route_cache_time) < FERRY_CACHE_TTL_SECONDS:
        return _ferry_trip_route_cache
    response = requests.get(STATIC_GTFS_URL, timeout=15)
    response.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    trip_map = {}
    with zf.open("trips.txt") as f:
        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
        for row in reader:
            trip_map[row["trip_id"]] = row["route_id"]
    _ferry_trip_route_cache = trip_map
    _ferry_trip_route_cache_time = now
    return trip_map

def _get_ferry_alerts(route_id=None):
    alerts = []
    feed = _fetch_ferry_feed(ALERT_URL)
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        affected_routes = [
            informed.route_id for informed in alert.informed_entity if informed.route_id
        ]
        if route_id and affected_routes and route_id not in affected_routes:
            continue
        header = alert.header_text.translation[0].text if alert.header_text.translation else ""
        description = (
            alert.description_text.translation[0].text
            if alert.description_text.translation
            else ""
        )
        alerts.append(
            {"id": entity.id, "routes": affected_routes, "header": header, "description": description}
        )
    return alerts


def _get_ferry_trip_updates(route_id=None):
    updates = []
    feed = _fetch_ferry_feed(TRIPUPDATE_URL)
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_update = entity.trip_update
        trip_route_id = trip_update.trip.route_id or _get_ferry_trip_route_map().get(trip_update.trip.trip_id, "")
        if route_id and trip_route_id != route_id:
            continue
        stops = []
        for stop_time_update in trip_update.stop_time_update:
            arrival_time = (
                stop_time_update.arrival.time
                if stop_time_update.HasField("arrival") and stop_time_update.arrival.time
                else None
            )
            departure_time = (
                stop_time_update.departure.time
                if stop_time_update.HasField("departure") and stop_time_update.departure.time
                else None
            )
            stops.append(
                {
                    "stop_id": stop_time_update.stop_id,
                    "arrival_time": arrival_time,
                    "departure_time": departure_time,
                }
            )
        updates.append({"trip_id": trip_update.trip.trip_id, "route_id": trip_route_id, "stops": stops})
    return updates


def get_ferry_status(route_id: str | None = None) -> dict:
    try:
        return {
            "status": "ok",
            "alerts": _get_ferry_alerts(route_id),
            "trip_updates": _get_ferry_trip_updates(route_id),
        }
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"No se pudo conectar a NYC Ferry: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Error procesando datos de ferry: {e}"}


# ============================================================
# LIVE BOARD (entrypoint)
# ============================================================
def _safe_call(label, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        return {"status": "error", "message": f"Error en {label}: {e}"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)

        def get_param(name):
            values = query.get(name)
            return values[0] if values else None

        result = {
            "parking": _safe_call("parking", get_parking_status, get_param("borough")),
            "subway": _safe_call("subway", get_subway_status, get_param("subway_line")),
            "bus": _safe_call("bus", get_bus_status, get_param("bus_route")),
            "ferry": _safe_call("ferry", get_ferry_status, get_param("ferry_route")),
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode("utf-8"))
