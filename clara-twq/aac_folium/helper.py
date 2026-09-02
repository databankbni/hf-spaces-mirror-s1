import requests
import numpy
import pandas as pd
from math import radians, sin, cos, sqrt, atan2
import json
from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus   # CHANGE FOR CLICK TRACKING
from google.oauth2 import service_account
from googleapiclient.discovery import build

# First try environment variables (for local development)         
load_dotenv()
email = os.getenv("ONEMAP_EMAIL")
password = os.getenv("ONEMAP_EMAIL_PASSWORD")
googlekey = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

# If not found, read from HuggingFace secret files
if not email and os.path.exists("/run/secrets/ONEMAP_EMAIL"):
    with open("/run/secrets/ONEMAP_EMAIL", "r") as f:
        email = f.read().strip()

if not password and os.path.exists("/run/secrets/ONEMAP_EMAIL_PASSWORD"):
    with open("/run/secrets/ONEMAP_EMAIL_PASSWORD", "r") as f:
        password = f.read().strip()
if not googlekey and os.path.exists("/run/secrets/GOOGLE_SERVICE_ACCOUNT_JSON"):
    with open ("/run/secrets/GOOGLE_SERVICE_ACCOUNT_JSON","r") as f:
        googlekey = f.read().strip()
        
 
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
info = json.loads(googlekey)
creds = service_account.Credentials.from_service_account_info(
    info,
    scopes = SCOPES
    )

url = "https://www.onemap.gov.sg/api/auth/post/getToken"
            
payload = {
    "email": email,
    "password": password
}

def get_token(payload=payload):
    response = requests.request("POST", url, json=payload)
    data = response.json()
    token = data.get("access_token")
    headers = {"Authorization": token}
    return headers

def update_and_get_dataset(creds= creds):
    service = build("sheets", "v4", credentials=creds)
    
    # 1. Fetch current data using your existing reader logic
    
    service = build("sheets", "v4", credentials=creds)

    SPREADSHEET_ID = "1G-IP1cfut9OHjNK2EgeoC_rSn-izUT-xC7BBK_CUBZU"
    # SPREADSHEET_ID = "1kO-eLcBN3tYDwBTRKbAOr54ExJNVdBGO2TgRiHcLIMQ" --testing spreadsheet
    RANGE_NAME = "CHP_dataset!A:I"
    SHEET_NAME = "CHP_dataset"

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=RANGE_NAME
    ).execute()

    values = result.get("values", [])
    
    if not values:
        return pd.DataFrame()
    aac_df = pd.DataFrame(values[1:], columns=values[0])
    aac_df['latitude'] = pd.to_numeric(aac_df['latitude'], errors='coerce')
    aac_df['longitude'] = pd.to_numeric(aac_df['longitude'], errors='coerce')
    
    # 2. Identify rows with missing Lat/Lon
    missing_mask = aac_df['latitude'].isna() | aac_df['longitude'].isna()
    missing_df = aac_df[missing_mask]

    if missing_df.empty:
        return aac_df  # Return immediately if no work is needed

    # 3. Map column letters (A=0, B=1, etc.)
    cols = list(aac_df.columns)
    lat_idx = cols.index('latitude')
    lon_idx = cols.index('longitude')
    lat_col_letter = chr(65 + lat_idx)
    lon_col_letter = chr(65 + lon_idx)

    updates = []

    # 4. Iterate only through missing rows
    for index, row in missing_df.iterrows():
        try:
            # Get data from OneMap
            lat, lon, addr = get_coordinates_from_postal(row['Postal Code'])
            rounded_lat = round(lat, 6)
            rounded_lon = round(lon, 6)
            # Update the local DataFrame (so it's ready to be returned)
            aac_df.at[index, 'latitude'] = rounded_lat
            aac_df.at[index, 'longitude'] = rounded_lon
            
            # Prepare the Google Sheets updates
            row_num = index + 2
            updates.append({'range': f"{SHEET_NAME}!{lat_col_letter}{row_num}", 'values': [[rounded_lat]]})
            updates.append({'range': f"{SHEET_NAME}!{lon_col_letter}{row_num}", 'values': [[rounded_lon]]})
            
            print(f"Updated {row['Postal Code']} at Row {row_num}")
            
        except Exception as e:
            print(f"Skipping postal {row.get('Postal Code')}: {e}")

    # 5. Push changes to Google Sheets in one batch
    if updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'valueInputOption': 'USER_ENTERED', 'data': updates}
        ).execute()

    return aac_df # This now contains the new lat/lon values


# =========================
# OneMap Functions
# =========================

def haversine(lat1, lon1, lat2, lon2):
    R = 6371 # represents the average radius of the earth
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))



def get_coordinates_from_postal(postal_code):
    headers = get_token()
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

            from_stop = leg.get("from", {}).get("name", "the bus stop")
            to_stop = leg.get("to", {}).get("name", "the next stop")

            steps.append(
                f"Take Bus {route} from {from_stop} to {to_stop}."
            )

        # MRT / SUBWAY
        elif mode in ["SUBWAY", "TRAIN"]:
            route = leg.get("route", "")
            from_stop = leg.get("from", {}).get("name", "the station")
            to_stop = leg.get("to", {}).get("name", "your stop")

            steps.append(
                f"Take the {route} line from {from_stop} to {to_stop}."
            )

        # UNKNOWN MODE
        else:
            steps.append("Continue as directed.")
    
    return steps


def get_route(start, end, routetype="pt", mode='TRANSIT'):
    """Get route using OneMap Routing API (walk or transit)."""
    print('get_route', start, end, routetype)
    
    # 1. Handle identical points immediately
    if round(start[0], 6) == round(end[0], 6) and round(start[1], 6) == round(end[1], 6):
        print("Start and End are identical. Returning zero route metrics.")
        return {
            "coords": None,
            "time": 0,
            "Walk distance": 0,
            "Instructions": ["Same Location"]
        }
    
    headers = get_token()
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(sgt)
    date_format = now.strftime('%m-%d-%Y')
    
    # 2. Build URL with both start and end rounded to 6dp
    url = (
        f"https://www.onemap.gov.sg/api/public/routingsvc/route?"
        f"start={round(start[0],6)},{round(start[1],6)}&end={round(end[0],6)},{round(end[1],6)}"
        f"&date={date_format}&time=09:00:00"
        f"&routeType={routetype}&mode={mode}"
    )
    
    print('url', url)
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
    except Exception as e:
        print(f"Primary connection failure: {e}")
        return None
        
    # 3. FIXED: Properly check 'r' and safely fall back to walking
    if r is not None and r.status_code == 404 and routetype == "pt":
        print("No public transit found (points might be too close). Trying walking route...")
        url_walk = (
            f"https://www.onemap.gov.sg/api/public/routingsvc/route?"
            f"start={round(start[0],6)},{round(start[1],6)}&end={round(end[0],6)},{round(end[1],6)}"
            f"&routeType=walk"
        )
        try:
            r = requests.get(url_walk, headers=headers, timeout=10)
        except Exception as e:
            print(f"Fallback walking connection failure: {e}")
            return None
        
    # 4. Final safety check on status codes
    if r is None or r.status_code != 200:
        status_log = r.status_code if r else "No Connection"
        print('status code in getroute', status_log)
        return None
    
    # Process successful data
    data = r.json()
    plan = data.get("plan")
    
    if not plan or not plan.get("itineraries"):
        return None
        
    itinerary = plan["itineraries"][0]  # Take the first suggested route
    legs = itinerary.get("legs", [])
    coords = []
    
    for leg in legs:
        poly = leg.get("legGeometry", {}).get("points")
        if poly:
            coords.extend(decode_polyline(poly))
            
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
