import os
from collections import defaultdict
from importlib import import_module
from dotenv import load_dotenv

from pathlib import Path
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "qaclide")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_TABLE = os.getenv("DROPDOWN_TABLE", "").strip()

# Explicit field SQL queries mapping
DROPDOWN_QUERIES = {
    "Company": "SELECT DISTINCT company_name FROM clide_company_master WHERE company_name IS NOT NULL AND soft_delete=0 AND company_name != '' ORDER BY company_name",
    "Service": "SELECT DISTINCT stream_name FROM clide_stream WHERE stream_name IS NOT NULL AND stream_name != '' ORDER BY stream_name",
    "PlantProjectClient": "SELECT DISTINCT sub_stream_name FROM clide_sub_stream WHERE sub_stream_name IS NOT NULL AND sub_stream_name != '' ORDER BY sub_stream_name",
    "Department": "SELECT DISTINCT department FROM clide_company_department WHERE department IS NOT NULL AND department != '' ORDER BY department",
    "Contractor": "SELECT DISTINCT contractor FROM clide_company_contractor WHERE contractor IS NOT NULL AND contractor != '' ORDER BY contractor",
    "Zone": "SELECT DISTINCT sub_stream_zone_name FROM clide_sub_stream_zone WHERE sub_stream_zone_name IS NOT NULL AND sub_stream_zone_name != '' ORDER BY sub_stream_zone_name",
    "Location": "SELECT DISTINCT sub_stream_zone_location_name FROM clide_sub_stream_zone_location WHERE sub_stream_zone_location_name IS NOT NULL AND sub_stream_zone_location_name != '' ORDER BY sub_stream_zone_location_name",
    "Activity": "SELECT DISTINCT activity FROM clide_sub_stream_hira_activity WHERE activity IS NOT NULL AND activity != '' ORDER BY activity",
    "SubActivity": "SELECT DISTINCT name FROM sub_activity WHERE name IS NOT NULL AND name != '' ORDER BY name",
    "Hazard": "SELECT DISTINCT name FROM hazard WHERE name IS NOT NULL AND name != '' ORDER BY name",
    "SubHazard": "SELECT DISTINCT name FROM sub_hazard WHERE name IS NOT NULL AND name != '' ORDER BY name",
    "SourceRules": "SELECT DISTINCT source FROM clide_company_sourcemaster WHERE source IS NOT NULL AND source != '' ORDER BY source",
    "ControlMeasureViolations": "SELECT DISTINCT name FROM existing_control_measure WHERE name IS NOT NULL AND name != '' ORDER BY name",
    "ResolveRights": "SELECT DISTINCT em.display_name FROM clide_module_oiac_closing_rights_category_user cru JOIN clide_module_oiac_users ou ON cru.oiac_closing_rights_user_id = ou.oiac_closing_rights_user_id JOIN clide_user cu ON ou.user_id = cu.user_id JOIN employee_master em ON cu.employee_master_id = em.id WHERE em.display_name IS NOT NULL AND em.display_name != '' ORDER BY em.display_name",
}

# Static dropdowns explicitly specified by user
STATIC_DROPDOWNS = {
    "UAUCType": ["UA", "UC"],
    "RiskLevel": ["Extreme", "High", "Medium", "Low"],
}


def _load_pymysql():
    try:
        pymysql = import_module("pymysql")
        dict_cursor = import_module("pymysql.cursors").DictCursor
        return pymysql, dict_cursor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyMySQL is required to read dropdown values from the QA MySQL database. "
            "Install the backend requirements before starting the app."
        ) from exc


def get_connection():
    pymysql, dict_cursor = _load_pymysql()
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=dict_cursor,
        charset="utf8mb4",
        autocommit=False,
    )


def init_db():
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            print(f"[database] Successfully connected to database '{DB_NAME}' at {DB_HOST}:{DB_PORT}.")
        finally:
            conn.close()
    except Exception as err:
        print(f"[database ERROR] Could not connect to QA database '{DB_NAME}' ({err}).")


def get_all_dropdowns() -> dict:
    result: dict[str, list[str]] = {}

    # 1. Apply static dropdowns
    for field, options in STATIC_DROPDOWNS.items():
        result[field] = options

    # 2. Query dynamic fields from MySQL
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for field, query in DROPDOWN_QUERIES.items():
                    try:
                        cur.execute(query)
                        rows = cur.fetchall()
                        values = [list(r.values())[0] for r in rows if r and list(r.values())[0]]
                        result[field] = values
                    except Exception as q_err:
                        print(f"[database ERROR] Query for field '{field}' failed: {q_err}")
                        result[field] = []
        finally:
            conn.close()
    except Exception as err:
        print(f"[database ERROR] Failed connecting to DB: {err}")

    return result


def resolve_related_fields(data: dict) -> dict:
    location = data.get("Location")
    zone = data.get("Zone")
    plant = data.get("PlantProjectClient")
    sub_hazard = data.get("SubHazard")
    sub_activity = data.get("SubActivity")

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # 1. Resolve Location -> Zone, Plant, Service
                if location and (not zone or not plant or not data.get("Service")):
                    query = """
                        SELECT stream_id, sub_stream_id, sub_stream_zone_id 
                        FROM clide_sub_stream_zone_location 
                        WHERE sub_stream_zone_location_name = %s LIMIT 1
                    """
                    cur.execute(query, (location,))
                    row = cur.fetchone()
                    if row:
                        stream_id = row.get("stream_id")
                        sub_stream_id = row.get("sub_stream_id")
                        zone_id = row.get("sub_stream_zone_id")
                        
                        if zone_id and not zone:
                            cur.execute("SELECT sub_stream_zone_name FROM clide_sub_stream_zone WHERE sub_stream_zone_id = %s LIMIT 1", (zone_id,))
                            z_row = cur.fetchone()
                            if z_row:
                                data["Zone"] = list(z_row.values())[0]
                                zone = data["Zone"]
                        if sub_stream_id and not plant:
                            cur.execute("SELECT sub_stream_name FROM clide_sub_stream WHERE sub_stream_id = %s LIMIT 1", (sub_stream_id,))
                            p_row = cur.fetchone()
                            if p_row:
                                data["PlantProjectClient"] = list(p_row.values())[0]
                                plant = data["PlantProjectClient"]
                        if stream_id and not data.get("Service"):
                            cur.execute("SELECT stream_name FROM clide_stream WHERE stream_id = %s LIMIT 1", (stream_id,))
                            s_row = cur.fetchone()
                            if s_row:
                                data["Service"] = list(s_row.values())[0]

                # 2. Resolve Zone -> Plant, Service
                if zone and (not plant or not data.get("Service")):
                    query = """
                        SELECT stream_id, sub_stream_id 
                        FROM clide_sub_stream_zone 
                        WHERE sub_stream_zone_name = %s LIMIT 1
                    """
                    cur.execute(query, (zone,))
                    row = cur.fetchone()
                    if row:
                        stream_id = row.get("stream_id")
                        sub_stream_id = row.get("sub_stream_id")
                        
                        if sub_stream_id and not plant:
                            cur.execute("SELECT sub_stream_name FROM clide_sub_stream WHERE sub_stream_id = %s LIMIT 1", (sub_stream_id,))
                            p_row = cur.fetchone()
                            if p_row:
                                data["PlantProjectClient"] = list(p_row.values())[0]
                                plant = data["PlantProjectClient"]
                        if stream_id and not data.get("Service"):
                            cur.execute("SELECT stream_name FROM clide_stream WHERE stream_id = %s LIMIT 1", (stream_id,))
                            s_row = cur.fetchone()
                            if s_row:
                                data["Service"] = list(s_row.values())[0]

                # 3. Resolve Plant -> Service, Region, State, City, ProjectCategory, Company
                if plant:
                    query = """
                        SELECT stream_id, company_id, region, sub_stream_state, sub_stream_city, project_category_id 
                        FROM clide_sub_stream 
                        WHERE sub_stream_name = %s LIMIT 1
                    """
                    cur.execute(query, (plant,))
                    row = cur.fetchone()
                    if row:
                        stream_id = row.get("stream_id")
                        company_id = row.get("company_id")
                        region = row.get("region")
                        state = row.get("sub_stream_state")
                        city = row.get("sub_stream_city")
                        pc_id = row.get("project_category_id")

                        if stream_id and not data.get("Service"):
                            cur.execute("SELECT stream_name FROM clide_stream WHERE stream_id = %s LIMIT 1", (stream_id,))
                            s_row = cur.fetchone()
                            if s_row:
                                data["Service"] = list(s_row.values())[0]

                        if company_id and not data.get("Company"):
                            cur.execute("SELECT company_name FROM clide_company_master WHERE company_id = %s LIMIT 1", (company_id,))
                            c_row = cur.fetchone()
                            if c_row:
                                data["Company"] = list(c_row.values())[0]
                        
                        data["Region"] = region or ""
                        data["State"] = state or ""
                        data["City"] = city or ""
                        
                        if pc_id:
                            cur.execute("SELECT project_category_name FROM clide_project_category WHERE project_category_id = %s LIMIT 1", (pc_id,))
                            pc_row = cur.fetchone()
                            if pc_row:
                                data["ProjectCategory"] = list(pc_row.values())[0]
                            else:
                                data["ProjectCategory"] = ""
                        else:
                            data["ProjectCategory"] = ""

                # 4. Resolve SubHazard -> Hazard
                if sub_hazard and not data.get("Hazard"):
                    query = """
                        SELECT hazard_id FROM sub_hazard WHERE name = %s LIMIT 1
                    """
                    cur.execute(query, (sub_hazard,))
                    row = cur.fetchone()
                    if row:
                        h_id = row.get("hazard_id")
                        if h_id:
                            cur.execute("SELECT name FROM hazard WHERE id = %s LIMIT 1", (h_id,))
                            h_row = cur.fetchone()
                            if h_row:
                                data["Hazard"] = list(h_row.values())[0]

                # 5. Resolve SubActivity -> Activity
                if sub_activity and not data.get("Activity"):
                    query = """
                        SELECT activity_id FROM sub_activity WHERE name = %s LIMIT 1
                    """
                    cur.execute(query, (sub_activity,))
                    row = cur.fetchone()
                    if row:
                        act_id = row.get("activity_id")
                        if act_id:
                            cur.execute("SELECT activity FROM clide_sub_stream_hira_activity WHERE activity_master_id = %s LIMIT 1", (act_id,))
                            act_row = cur.fetchone()
                            if act_row:
                                data["Activity"] = list(act_row.values())[0]

                # 6. Resolve Service -> Company if Company is empty
                if data.get("Service") and not data.get("Company"):
                    cur.execute("SELECT stream_id FROM clide_stream WHERE stream_name = %s LIMIT 1", (data.get("Service"),))
                    s_row = cur.fetchone()
                    if s_row:
                        stream_id = s_row.get("stream_id")
                        if stream_id:
                            cur.execute("""
                                SELECT c.company_name 
                                FROM clide_company_stream cs
                                JOIN clide_company_master c ON cs.company_id = c.company_id
                                WHERE cs.stream_id = %s AND cs.soft_delete = 0 LIMIT 1
                            """, (stream_id,))
                            c_row = cur.fetchone()
                            if c_row:
                                data["Company"] = c_row.get("company_name")
        finally:
            conn.close()
    except Exception as err:
        print(f"[database ERROR] resolve_related_fields failed: {err}")

    return data




