"""
ferry.py — Park Pulse NYC
Módulo de datos en tiempo real para NYC Ferry.

Fuente: GTFS-Realtime público de NYC Ferry (Connexionz), sin API key.
Endpoints confirmados en https://www.ferry.nyc/developer-tools/

- GTFS estático:     https://nycferry.connexionz.net/rtt/public/utility/gtfs.aspx
- Alertas (RT):      https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/alert
- Trip updates (RT): https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate
"""

import requests
from google.transit import gtfs_realtime_pb2

STATIC_GTFS_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfs.aspx"
TRIPUPDATE_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/tripupdate"
ALERT_URL = "https://nycferry.connexionz.net/rtt/public/utility/gtfsrealtime.aspx/alert"

REQUEST_TIMEOUT = 10


def _fetch_feed(url):
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    return feed


def get_ferry_alerts(route_id=None):
    alerts = []
    feed = _fetch_feed(ALERT_URL)

    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue

        alert = entity.alert

        affected_routes = [
            informed.route_id
            for informed in alert.informed_entity
            if informed.route_id
        ]

        if route_id and affected_routes and route_id not in affected_routes:
            continue

        header = ""
        if alert.header_text.translation:
            header = alert.header_text.translation[0].text

        description = ""
        if alert.description_text.translation:
            description = alert.description_text.translation[0].text

        alerts.append({
            "id": entity.id,
            "routes": affected_routes,
            "header": header,
            "description": description,
        })

    return alerts


def get_ferry_trip_updates(route_id=None):
    updates = []
    feed = _fetch_feed(TRIPUPDATE_URL)

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue

        trip_update = entity.trip_update
        trip_route_id = trip_update.trip.route_id

        if route_id and trip_route_id != route_id:
            continue

        stops = []
        for stop_time_update in trip_update.stop_time_update:
            arrival_time = None
            if stop_time_update.HasField("arrival") and stop_time_update.arrival.time:
                arrival_time = stop_time_update.arrival.time

            departure_time = None
            if stop_time_update.HasField("departure") and stop_time_update.departure.time:
                departure_time = stop_time_update.departure.time

            stops.append({
                "stop_id": stop_time_update.stop_id,
                "arrival_time": arrival_time,
                "departure_time": departure_time,
            })

        updates.append({
            "trip_id": trip_update.trip.trip_id,
            "route_id": trip_route_id,
            "stops": stops,
        })

    return updates


def get_ferry_status(route_id=None):
    try:
        return {
            "status": "ok",
            "alerts": get_ferry_alerts(route_id),
            "trip_updates": get_ferry_trip_updates(route_id),
        }
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"No se pudo conectar a NYC Ferry: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Error procesando datos de ferry: {e}"}
