from flask import Flask, render_template_string, request, flash
#from flask_talisman import Talisman
import requests 
import folium
import pandas as pd
from helper import update_and_get_dataset, haversine, get_coordinates_from_postal, fetch_route_task, build_tracked_gmaps_link
from folium.plugins import BeautifyIcon
from concurrent.futures import ThreadPoolExecutor
import time
import os

# CSV_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vT2Ux0ODD4oTvD8dOWdoHWT7ltu_3-FQXNrzgAwlwYX_oHO2TZ3gISHktBkEWA2BgQhYriNmyTS-wRr/pub?gid=1189089449&single=true&output=csv'

# def fetch_csv(url):
#     cache_buster = int(time.time())
#     resp = requests.get(f"{url}&v={cache_buster}", timeout=10)
#     resp.raise_for_status()
#     return resp.text

# csv_text = fetch_csv(CSV_URL)
#aac_df = pd.read_csv("CHP_dataset.csv")

# headers = get_token()

aac_df = update_and_get_dataset()

chp_df = aac_df[~(aac_df['Category']=='AAC')].copy()

app = Flask(__name__)

# Allow specific origin to iframe you


# csp = {
#     "default-src": "'self'",
#     "frame-ancestors": [
#         "https://www.nuhs.edu.sg",
#         "https://*.hf.space",
#         "https://huggingface.co"
#     ],
#     "script-src": "'self' 'unsafe-inline' https://cdn.jsdelivr.net", # Added for Leaflet/Folium scripts
#     "style-src": "'self' 'unsafe-inline' https://cdn.jsdelivr.net",
#     "img-src": "'self' data: https://*.tile.openstreetmap.org https://cdn.jsdelivr.net"
# }

# Talisman(
#     app,
#     content_security_policy=csp,
#     frame_options=None,
#     force_https=False # HF handles SSL; forcing it in the app can sometimes cause loops
# )

# CHANGE 1: You MUST have a secret key to use flashing
app.secret_key = "secret_key_123"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>CHP and AAC Finder</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <style>
        html, body {
            height: 100%;
            width: 100%;
            margin: 0;
            padding: 0;
            overflow: hidden;
        }

        #map-container {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            height: 100vh;
            width: 100vw;
        }

        /* Force Folium / Leaflet iframe to fill container */
        iframe {
            position: absolute;
            top: 0;
            left: 0;
            height: 100vh !important;
            width: 100vw !important;
            border: none;
        }

        .form-box {
            position: fixed;
            top: 12px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999;
            background: white;
            padding: 8px 12px;
            border-radius: 6px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }
        .error-msg { color: #721c24; background-color: #f8d7da; border: 1px solid #f5c6cb; 
                     padding: 5px; border-radius: 4px; margin-top: 5px; font-size: 13px; }
    </style>

</head>

<body>
    <div class="form-box">
        <form method="POST">
            <input
                type="text"
                name="postal"
                placeholder="Enter postal code"
                value="{{ postal or '' }}"
                style="padding:6px;"
            >
            <button type="submit">Find nearby CHPs</button>
            {% with messages = get_flashed_messages() %}
                {% if messages %}
                    {% for message in messages %}
                        <div class="error-msg">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
        </form>
    </div>

    <div id="map-container">
        {{ map_html|safe }}
    </div>
</body>
</html>
"""

@app.route("/health", methods=["GET"])
def health_check():
    return {"status": "healthy"}, 200

@app.route("/", methods=["GET", "POST"])
def index():
    postal = request.form.get("postal")

    WR_center = [1.345428, 103.7508]
    folium_map = folium.Map(
        location=WR_center,
        zoom_start=13,
        scrollWheelZoom=True,
        dragging=True,
        zoomControl=True
    )

    # Mobile-friendly scrolling behaviour
    folium_map.get_root().html.add_child(folium.Element("""
    <script>
    document.addEventListener("DOMContentLoaded", function() {
        const map = document.querySelector(".leaflet-container");
        map.addEventListener('touchmove', function(e) {

        }, { passive: true });
    });
    </script>
    """))

    # all_coords = []
    
    # Show all AACs
    for _, row in aac_df.iterrows():
        


        if pd.isna(row['Forsg']):
            tracked_gmaps_link = build_tracked_gmaps_link(
                row["latitude"], row["longitude"]
                )  # CHANGE FOR CLICK TRACKING
                    
            popup_html = f"""
            <b>{row['Centre Name']}</b><br>
            <b>Address:</b> {row['Address']}<br>
            <a href="{tracked_gmaps_link}" target="_blank">
            📍 Open in Google Maps
            </a><br>
            """
        else:        
            popup_html = f"""
            <b>{row['Centre Name']}</b><br>
            <b>Address:</b> {row['Address']}<br>
            <a href="{row['Forsg']}" target="_blank">
            📍 Open in Google Maps
            </a><br>
            """
        
        # 2. Add logic based on the Category
        category = row["Category"]
        
        if category == "CHP":
            marker_color = "#003D7C"
            popup_html += f"<b>CHP Opening Hours:</b> {row['CHP Operating Hours']}"
            
        elif category == "AAC":
            marker_color = "gray"
            popup_html += f"<b>AAC Opening Hours:</b> {row['AAC Operating Hours']}"
            
        elif category == "AAC & CHP":
            marker_color = "#003D7C"
            popup_html += f"<b>CHP Opening Hours:</b> {row['CHP Operating Hours']}<br>"
            popup_html += f"<b>AAC Opening Hours:</b> {row['AAC Operating Hours']}"

        # 3. Create the marker with the HTML string
        folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=folium.Popup(popup_html, max_width=300),
                icon=BeautifyIcon(
                        icon_shape='marker',      # Creates the teardrop shape
                        background_color=marker_color,
                        border_color='white',     # White border makes it look sharp
                        border_width=1,
                        inner_icon_style="display:none;", # THIS FIXES THE WHITE DOT
                        icon_size=[25, 25]        # THIS MAKES IT SMALLER (Standard is ~45)
                    )
            ).add_to(folium_map)
        
        # all_coords.append([row["latitude"], row["longitude"]])

    if postal:
        
        try:
        
            all_coords = [] # reset boundary for zoom
            # User location
            
            coord_result = get_coordinates_from_postal(postal)
            
            # CHANGE 2: Explicitly check if the result is valid/found
            if coord_result is None or not isinstance(coord_result, (tuple, list)):
                flash(f"Postal code '{postal}' not found. Please try again.")
            else:
                # Use indexing to be safe
                user_lat = coord_result[0]
                user_lon = coord_result[1]
                addr = coord_result[2] if len(coord_result) > 2 else "Unknown Address"
                print(user_lat,user_lon ,addr)
            
            if user_lat is None or user_lon is None:
                    flash(f"Location coordinates not available for '{postal}'.")
            else:
                folium.Marker(
                    location=[user_lat, user_lon],
                    popup="You are here",
                    icon=folium.Icon(
                        color="red",
                        icon="home",
                        prefix="fa"
                    )
                ).add_to(folium_map)

                all_coords.append([user_lat, user_lon])

                # Compute distances
                chp_df["dist_km"] = chp_df.apply(
                    lambda x: haversine(
                        user_lat, user_lon,
                        x["latitude"], x["longitude"]
                    ),
                    axis=1
                )

                nearest = chp_df.nsmallest(3, "dist_km")
                nearest_list = list(nearest.iterrows())
                colors = ["#F37021", "#003D7C", "#41B6E6"]
                route_results = []
                
                with ThreadPoolExecutor(max_workers=3) as executor:
                    # Map the tasks
                    futures = [
                        executor.submit(fetch_route_task, i, row, user_lat, user_lon, postal) 
                        for i, (idx, row) in enumerate(nearest.iterrows())
                    ]
                    for future in futures:
                        route_results.append(future.result())

                # Draw route 
                for i, row, route in route_results:
                    # FIX: Explicitly ensure route["coords"] exists and is not None
                    if isinstance(route, dict) and route.get("coords") is not None:
                        folium.PolyLine(
                            route["coords"],
                            color=colors[i],
                            weight=6,
                            opacity=1
                        ).add_to(folium_map)
                        all_coords.extend(route["coords"])
                    else:
                        # This will now catch both literal None returns AND dictionary None returns
                        centre_name = row.get('Centre Name', 'Unknown Centre')
                        print(f"Skipping route drawing for {centre_name} - no valid coordinate path found.")

                    # Popup content (shown only on click)
                    
                    # 1. Determine the Hours section based on Category
                    category = row["Category"]
                    hours_html = ""

                    if category == "CHP":
                        hours_html = f"<b>CHP Opening Hours:</b> {row['CHP Operating Hours']}<br>"
                    elif category == "AAC":
                        hours_html = f"<b>AAC Opening Hours:</b> {row['AAC Operating Hours']}<br>"
                    elif category == "AAC & CHP":
                        # Shows both if the category matches both
                        hours_html = (f"<b>CHP Opening Hours:</b> {row['CHP Operating Hours']}<br>"
                                    f"<b>AAC Opening Hours:</b> {row['AAC Operating Hours']}<br>")
                    tracked_gmaps_link = build_tracked_gmaps_link(
                        row["latitude"], row["longitude"]
                    )  
                    
                    # CHANGE FOR CLICK TRACKING
                    if pd.isna(row['Forsg']):
                        popup_html = f"""
                        <b>{row['Centre Name']}</b><br>
                        <b>Address:</b> {row['Address']}<br>
                        <a href="{tracked_gmaps_link}" target="_blank">
                        📍 Open in Google Maps
                        </a><br>
                        {hours_html}
                        <b>Walk Distance:</b> {route['Walk distance']/1000:.2f} km<br>
                        <b>Time:</b> {route['time']/60:.1f} min<br><br>

                        <b>Directions:</b><br>
                        """ 
                        
                    else:
                        popup_html = f"""
                        <b>{row['Centre Name']}</b><br>
                        <b>Address:</b> {row['Address']}<br>
                        <a href="{row['Forsg']}" target="_blank">
                        📍 Open in Google Maps
                        </a><br>
                        {hours_html}
                        <b>Walk Distance:</b> {route['Walk distance']/1000:.2f} km<br>
                        <b>Time:</b> {route['time']/60:.1f} min<br><br>

                        <b>Directions:</b><br>
                        """  # CHANGE FOR CLICK TRACKING


                    for step in route["Instructions"]:
                        popup_html += f"- {step}<br>"

                        folium.Marker(
                                location=[row["latitude"], row["longitude"]],
                                popup=folium.Popup(popup_html, max_width=320),
                                icon=BeautifyIcon(
                                    icon='plus',
                                    icon_shape='marker',      # Teardrop shape
                                    background_color=colors[i], # Uses your HEX colors
                                    border_color='white',
                                    border_width=1,
                                    text_color='white',        # This creates the "white dot" effect
                                    icon_size=[25, 25],
                                    inner_icon_style='font-size:12px; margin-left: 0.5px;'# This makes the whole teardrop smaller
                                )
                            ).add_to(folium_map)

                    all_coords.append([row["latitude"], row["longitude"]])

                # Fit map bounds
                if all_coords:
                    folium_map.fit_bounds(all_coords)
                
        except Exception as e:
                # CHANGE: "Flash" the error to the web interface and log it
                flash(f"Error: Could not find location for '{postal}'. Please try another postal code.")
                print(f"Geocoding Error: {e}")

    map_html = folium_map._repr_html_()
    return render_template_string(
                HTML_TEMPLATE,
                map_html=map_html,
                postal=postal
            )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)
