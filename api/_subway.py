"""
Park Pulse NYC — Subway real-time status checker.

Data source: MTA GTFS-Realtime subway feeds, accessed via the community-
maintained `nyct-gtfs` library. No API key required.
"""
from __future__ import annotations
from dataclasses import dataclass
from nyct_gtfs import NYCTFeed


@dataclass
class LineStatus:
    line: str
    has_delay: bool
    trains_underway: int


def get_line_status(line: str) -> LineStatus:
    feed = NYCTFeed(line)
    trips = feed.filter_trips(line_id=line, underway=True)

    has_delay = any(trip.has_delay_alert for trip in trips)

    return LineStatus(
        line=line,
        has_delay=has_delay,
        trains_underway=len(trips),
    )


def get_line_status_message(status: LineStatus) -> str:
    if status.has_delay:
        return "Minor delays"
    if status.trains_underway == 0:
        return "No trains reported"
    return "Running on time"


def get_subway_status(line: str | None = None) -> dict:
    if not line:
        return {"status": "error", "message": "No subway line specified"}
    try:
        status = get_line_status(line)
        return {
            "status": "ok",
            "line": status.line,
            "has_delay": status.has_delay,
            "trains_underway": status.trains_underway,
            "message": get_line_status_message(status),
        }
    except Exception as e:
        return {"status": "error", "message": f"Error fetching subway data: {e}"}
