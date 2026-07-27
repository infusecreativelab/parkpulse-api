"""
Park Pulse NYC — live-board endpoint (Vercel Python Function).

Deployed URL once live: https://<your-vercel-project>.vercel.app/api/live-board
Query params (all optional):
  ?subway_line=L
  ?bus_route=B52
  ?ferry_route=AS
  ?borough=Brooklyn
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json

from _parking import get_parking_status
from _subway import get_subway_status
from _bus import get_bus_status
from _ferry import get_ferry_status


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
