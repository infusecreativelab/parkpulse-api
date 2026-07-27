"""
Park Pulse NYC — Bus real-time status checker.

Data source: MTA Bus Time GTFS-Realtime feeds (standard format).
Requires an API key from https://register.developer.obanyc.com/
Set it as the OBA_API_KEY environment variable in Vercel.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime, timezone
import requests
from google.transit import gtfs_realtime_pb2

TRIP_UPDATES_URL = "https://gtfsrt.prod.obanyc.com/tripUpdates"


@dataclass
class RouteStatus:
    route: str
    has_delay: bool
    trips_tracked: int
    avg_delay_minutes: float | None


def fetch_trip_updates(api_key: str, timeout: int = 10) -> gtfs_realtime_pb2.FeedMessage:
    response = requests.get(TRIP_UPDATES_URL, params={"key": api_key}, timeout=timeout)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def get_route_status(feed: gtfs_realtime_pb2.FeedMessage, route: str) -> RouteStatus:
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


def get_route_status_message(status: RouteStatus) -> str:
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
        feed = fetch_trip_updates(api_key)
        status = get_route_status(feed, route)
        return {
            "status": "ok",
            "route": status.route,
            "has_delay": status.has_delay,
            "trips_tracked": status.trips_tracked,
            "avg_delay_minutes": status.avg_delay_minutes,
            "message": get_route_status_message(status),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error fetching bus data: {e}"}
