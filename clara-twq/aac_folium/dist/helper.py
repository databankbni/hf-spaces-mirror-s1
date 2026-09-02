import requests
import numpy
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
import json
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus   # CHANGE FOR CLICK TRACKING
   
# First try environment variables (for local development)         
load_dotenv()
email = os.getenv("ONEMAP_EMAIL")
password = os.getenv("ONEMAP_EMAIL_PASSWORD")

# If not found, read from HuggingFace secret files
if not email and os.path.exists("/run/secrets/ONEMAP_EMAIL"):
    with open("/run/secrets/ONEMAP_EMAIL", "r") as f:
        email = f.read().strip()

if not password and os.path.exists("/run/secrets/ONEMAP_EMAIL_PASSWORD"):
    with open("/run/secrets/ONEMAP_EMAIL_PASSWORD", "r") as f:
        password = f.read().strip()


url = "https://www.onemap.gov.sg/api/auth/post/getToken"
            
payload = {
    "email": email,
    "password": password
}
            
response = requests.request("POST", url, json=payload)
data = response.json()
token = data.get("access_token")
headers = {"Authorization": token}


def get_token():
    return headers

# =========================
# OneMap Functions
# =========================

def haversine(lat1, lon1, lat2, lon2):
    R = 6371 # represents the average radius of the earth
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))



def get_coordinates_from_postal(postal_code):
    """Get lat/lon from a Singapore postal code using OneMap."""
    url = f"https://www.onemap.gov.sg/api/common/elastic/search?searchVal={postal_code}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
    r = requests.get(url, headers = headers).json()
    if r["found"] > 0:
        lat = float(r["results"][0]["LATITUDE"])
        lon = float(r["results"][0]["LONGITUDE"])
        addr = r["results"][0]["ADDRESS"]
        return lat, lon, addr
    else:
        raise ValueError("Postal code not found in OneMap.")

def route_instructions(legs):
    steps = []
    
    for leg in legs:
        mode = leg.get("mode", "").upper()

        # WALK LEG
        if mode == "WALK":
            dist = leg.get("distance", 0)
            from_name = leg.get("from", {}).get("name", "starting point")
            to_name = leg.get("to", {}).get("name", "next point")

            steps.append(f"Walk {dist} metres from {from_name} to {to_name}.")

        # BUS LEG
        elif mode == "BUS":
            route = leg.get("route", "")

            # OneMap often returns numStops = 0 → so we calculate it manually
            intermediate = leg.get("intermediateStops", [])
            num_stops = len(intermediate)

            from_stop = leg.get("from", {}).get("name", "the bus stop")
            to_stop = leg.get("to", {}).get("name", "the next stop")

            steps.append(
                f"Take Bus {route} from {from_stop} and ride for {num_stops} stops to {to_stop}."
            )

        # MRT / SUBWAY
        elif mode in ["SUBWAY", "TRAIN"]:
            route = leg.get("route", "")
            num_stops = leg.get("numStops", 0)
            from_stop = leg.get("from", {}).get("name", "the station")
            to_stop = leg.get("to", {}).get("name", "your stop")

            steps.append(
                f"Take the {route} line from {from_stop} for {num_stops} stops to {to_stop}."
            )

        # UNKNOWN MODE
        else:
            steps.append("Continue as directed.")
    
    return steps


def get_route(start, end, routetype="pt", mode = 'TRANSIT'):
    """Get route using OneMap Routing API (walk or transit)."""
    print('get_route', start, end, routetype)
    print('token', token)
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(sgt)

    date_format = now.strftime('%m-%d-%Y')
    time_raw = now.strftime('%H:%M:%S')
    
    url = (
        f"https://www.onemap.gov.sg/api/public/routingsvc/route?"
        f"start={start[0]},{start[1]}&end={end[0]},{end[1]}"
        f"&date={date_format}&time={time_raw}"
        f"&routeType={routetype}&mode={mode}"
    )
    
    print('url', url)
    r = requests.get(url, headers = headers)
    if r.status_code != 200:
        print ('status code in getroute', r.status_code)
        return None
    
    data = r.json()
    
    plan = data.get("plan")
    #print(json.dumps(plan))
    if not plan or not plan.get("itineraries"):
        return None
    itinerary = plan["itineraries"][0]  # Take the first suggested route
    legs = itinerary.get("legs", [])
    coords = []
    for leg in legs:
        poly = leg.get("legGeometry", {}).get("points")
        if poly:
            coords.extend(decode_polyline(poly))
    #print (json.dumps(itinerary, indent = 2))
    instructions = route_instructions(legs)
    return {
        "coords": coords,
        "time": itinerary.get("duration", 0),
        "Walk distance": itinerary.get("walkDistance", 0),
        "Instructions": instructions
    }

def fetch_route_task(index, row, user_lat, user_lon, postal):
    # Try offline first
    route = get_route(
    (user_lat, user_lon),
    (row["latitude"], row["longitude"])
        )
    return index, row, route

def decode_polyline(polyline_str):
    """Decode OneMap encoded polyline to list of [lat, lon]."""
    index, lat, lng, coordinates = 0, 0, 0, []
    changes = {"lat": 0, "lng": 0}
    while index < len(polyline_str):
        for unit in ["lat", "lng"]:
            shift, result = 0, 0
            while True:
                b = ord(polyline_str[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            if (result & 1):
                changes[unit] = ~(result >> 1)
            else:
                changes[unit] = (result >> 1)
        lat += changes["lat"]
        lng += changes["lng"]
        coordinates.append([lat / 1e5, lng / 1e5])
    return coordinates

def build_tracked_gmaps_link(lat, lng):
    """
    Builds a for.sg-tracked Google Maps link
    """
    gmaps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    return gmaps_url
    # CHANGE FOR CLICK TRACKING
