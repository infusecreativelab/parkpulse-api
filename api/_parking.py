"""
Park Pulse NYC — Alternate Side Parking (ASP) suspension checker.
Data source: NYC DOT's official annual ASP suspension calendar (.ics file),
published at:
    https://www.nyc.gov/html/dot/downloads/misc/{YEAR}-alternate-side.ics
"""
from __future__ import annotations
from datetime import date, datetime
from dataclasses import dataclass
from icalendar import Calendar
import urllib.request

ICS_URL_TEMPLATE = "https://www.nyc.gov/html/dot/downloads/misc/{year}-alternate-side.ics"


@dataclass
class Suspension:
    suspension_date: date
    holiday_name: str


def fetch_ics(year: int, timeout: int = 10) -> bytes:
    url = ICS_URL_TEMPLATE.format(year=year)
    req = urllib.request.Request(url, headers={"User-Agent": "ParkPulseNYC/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_ics(ics_bytes: bytes) -> list[Suspension]:
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


def is_suspended_on(suspensions: list[Suspension], day: date) -> Suspension | None:
    for s in suspensions:
        if s.suspension_date == day:
            return s
    return None


def get_parking_status(borough: str | None = None) -> dict:
    """
    Main entry point. `borough` is currently accepted for future filtering
    (the NYC-wide ASP calendar applies citywide, so it's not used to filter
    yet, but kept in the signature so live-board.py can pass it safely).
    """
    try:
        today = date.today()
        ics_bytes = fetch_ics(today.year)
        suspensions = parse_ics(ics_bytes)
        today_suspension = is_suspended_on(suspensions, today)

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
