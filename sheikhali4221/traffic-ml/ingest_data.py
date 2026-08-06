import os
import requests
import time
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# 1. Load Environment Variables
load_dotenv()
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
TRAFFIC_API_KEY = os.getenv("TRAFFIC_API_KEY")
NEON_URL = os.getenv("DATABASE_URL")

# 2. Database Connection Variables
DB_NAME = "traffic_ml_db"
DB_USER = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"

# 3. Define Top Major Corridors (NY, DC, FL, CA - Total 40 Locations)
MAJOR_CORRIDORS = {
    # --- NEW YORK CITY (10 Locations) ---
    "Times_Square_NY": {"lat": 40.7588, "lon": -73.9851},
    "Wall_Street_NY": {"lat": 40.7060, "lon": -74.0088},
    "Brooklyn_Bridge_NY": {"lat": 40.7061, "lon": -73.9969},
    "Broadway_Manhattan": {"lat": 40.7590, "lon": -73.9845},
    "Central_Park_West": {"lat": 40.7812, "lon": -73.9740},
    "JFK_Airport_NY": {"lat": 40.6413, "lon": -73.7781},
    "Lincoln_Tunnel_NY": {"lat": 40.7583, "lon": -74.0086},
    "Manhattan_Bridge_NY": {"lat": 40.7130, "lon": -73.9896},
    "Queensboro_Bridge_NY": {"lat": 40.7567, "lon": -73.9545},
    "FDR_Drive_NY": {"lat": 40.7351, "lon": -73.9730},

    # --- WASHINGTON D.C. (10 Locations) ---
    "White_House_DC": {"lat": 38.8977, "lon": -77.0365},
    "Capitol_Hill_DC": {"lat": 38.8899, "lon": -77.0090},
    "Lincoln_Memorial_DC": {"lat": 38.8893, "lon": -77.0502},
    "Washington_Monument_DC": {"lat": 38.8895, "lon": -77.0353},
    "Pentagon_VA": {"lat": 38.8719, "lon": -77.0563},
    "Georgetown_DC": {"lat": 38.9051, "lon": -77.0624},
    "Union_Station_DC": {"lat": 38.8973, "lon": -77.0063},
    "Dupont_Circle_DC": {"lat": 38.9096, "lon": -77.0434},
    "National_Mall_DC": {"lat": 38.8896, "lon": -77.0229},
    "K_Street_DC": {"lat": 38.9026, "lon": -77.0396},

    # --- FLORIDA (Miami & Orlando - 10 Locations) ---
    "South_Beach_Miami_FL": {"lat": 25.7826, "lon": -80.1340},
    "Ocean_Drive_Miami_FL": {"lat": 25.7765, "lon": -80.1320},
    "Downtown_Miami_FL": {"lat": 25.7743, "lon": -80.1937},
    "Brickell_City_Centre_FL": {"lat": 25.7667, "lon": -80.1928},
    "Miami_Intl_Airport_FL": {"lat": 25.7959, "lon": -80.2870},
    "Walt_Disney_World_Orlando_FL": {"lat": 28.3852, "lon": -81.5639},
    "Universal_Studios_Orlando_FL": {"lat": 28.4743, "lon": -81.4678},
    "International_Drive_Orlando_FL": {"lat": 28.4444, "lon": -81.4688},
    "Tampa_Riverwalk_FL": {"lat": 27.9465, "lon": -82.4616},
    "Key_West_Duval_St_FL": {"lat": 24.5534, "lon": -81.7995},

    # --- CALIFORNIA (LA & SF Heavy Traffic - 10 Locations) ---
    "I_405_Sepulveda_Pass_LA": {"lat": 34.1105, "lon": -118.4735},
    "US_101_Hollywood_Fwy_LA": {"lat": 34.0689, "lon": -118.2611},
    "I_10_Santa_Monica_Fwy_LA": {"lat": 34.0335, "lon": -118.2721},
    "I_5_Golden_State_Fwy_LA": {"lat": 34.0631, "lon": -118.2185},
    "CA_110_Harbor_Fwy_LA": {"lat": 34.0486, "lon": -118.2702},
    "Golden_Gate_Bridge_SF": {"lat": 37.8199, "lon": -122.4783},
    "Bay_Bridge_SF": {"lat": 37.8181, "lon": -122.3467},
    "Silicon_Valley_US_101": {"lat": 37.3852, "lon": -122.0256},
    "I_280_Interstate_SF": {"lat": 37.7303, "lon": -122.4332},
    "Pacific_Coast_Hwy_Malibu": {"lat": 34.0308, "lon": -118.5772}
}

def fetch_and_store_data():
    conn = psycopg2.connect(NEON_URL)
    cursor = conn.cursor()
    
    for loc_name, coords in MAJOR_CORRIDORS.items():
        # Smart Coordinate Extractor & Float Converter
        try:
            if isinstance(coords, dict):
                lat = float(coords.get('lat'))
                lon = float(coords.get('lon'))
            else:
                lat_str, lon_str = coords.split(',')
                lat = float(lat_str)
                lon = float(lon_str)
                
            # 1. Fetch Traffic Data
            traffic_url = f"https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point={lat},{lon}&key={TRAFFIC_API_KEY}"
            traffic_res = requests.get(traffic_url).json()
            
            # 2. Fetch Weather Data
            weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric"
            weather_res = requests.get(weather_url).json()
            
            # 3. Extract Features
            if 'flowSegmentData' in traffic_res and 'main' in weather_res:
                flow_data = traffic_res['flowSegmentData']
                weather_data = weather_res
                
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Traffic Features
                current_speed = flow_data.get('currentSpeed', 0)
                free_flow_speed = flow_data.get('freeFlowSpeed', 0)
                current_travel_time = flow_data.get('currentTravelTime', 0)
                free_flow_travel_time = flow_data.get('freeFlowTravelTime', 0)
                confidence = flow_data.get('confidence', 1.0)
                road_closure = flow_data.get('roadClosure', False)
                
                # Weather Features
                temp_c = weather_data['main'].get('temp', 0)
                humidity = weather_data['main'].get('humidity', 0)
                weather_condition = weather_data.get('weather', [{}])[0].get('description', 'Unknown')
                weather_main = weather_data.get('weather', [{}])[0].get('main', 'Unknown')
                visibility = weather_data.get('visibility', 0)
                wind_speed = weather_data.get('wind', {}).get('speed', 0.0)
                feels_like = weather_data['main'].get('feels_like', 0.0)

                # 4. Save to Database
                insert_query = """
                INSERT INTO traffic_weather_data (
                    location, timestamp, current_speed_kmh, free_flow_speed_kmh, 
                    temperature_c, humidity, weather_condition, latitude, longitude,
                    visibility, wind_speed, weather_main, feels_like,
                    current_travel_time, free_flow_travel_time, confidence, road_closure
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                cursor.execute(insert_query, (
                    loc_name, timestamp, current_speed, free_flow_speed, 
                    temp_c, humidity, weather_condition, lat, lon,
                    visibility, wind_speed, weather_main, feels_like,
                    current_travel_time, free_flow_travel_time, confidence, road_closure
                ))
                
                conn.commit()

                print(f"✅ Extracted ALL 17 features for {loc_name}")
                
        except Exception as e:
            print(f"❌ Error fetching {loc_name}: {e}")
            conn.rollback() 
            
    conn.commit()
    cursor.close()
    conn.close()
    print("🚀 Pipeline Run Complete!")

if __name__ == "__main__":
    fetch_and_store_data()