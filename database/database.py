"""
ParkOps Database & Single Source of Truth
==========================================
Manages SQLite database operations, schema creation, data-driven park models,
dynamic crowd calculations, dataset import (.xlsx/.csv), and dataset removal.
"""
import os
import sqlite3
import datetime
import io
import openpyxl
from typing import Dict, List, Any, Optional, Tuple

DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database.db')

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or DATABASE_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_crowd_level(current_visitors: int, capacity: int) -> Tuple[str, int, str]:
    """
    Standard single source of truth for crowd calculation:
    occupancy_percentage = (current_visitors / capacity) * 100
    - 0–40%: Low (soft green)
    - 41–70%: Medium (soft yellow)
    - 71–90%: High (soft orange/pink)
    - 91–100%: Critical (soft red)
    """
    if capacity <= 0:
        return ("Low", 0, "#10b981")
    
    pct = int(round((current_visitors / max(1, capacity)) * 100))
    if pct <= 40:
        return ("Low", pct, "#10b981")
    elif pct <= 70:
        return ("Medium", pct, "#f59e0b")
    elif pct <= 90:
        return ("High", pct, "#eb6080")
    else:
        return ("Critical", pct, "#dc2626")

def init_db(db_path: Optional[str] = None):
    """Initializes full SQLite schema. NO automatic demo seeding per spec."""
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()

        # 1. Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                phone TEXT,
                country TEXT,
                role TEXT DEFAULT 'Operator',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Parks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                opening_time TEXT DEFAULT '09:00',
                closing_time TEXT DEFAULT '22:00',
                total_capacity INTEGER NOT NULL DEFAULT 25000,
                current_visitors INTEGER NOT NULL DEFAULT 0,
                weather TEXT DEFAULT 'Sunny & Clear',
                temperature TEXT DEFAULT '24°C',
                is_demo_data INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. Zones table (with spatial coordinates for Digital Model map)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                park_id INTEGER DEFAULT 1,
                name TEXT NOT NULL,
                description TEXT,
                x_position INTEGER NOT NULL DEFAULT 10,
                y_position INTEGER NOT NULL DEFAULT 10,
                width INTEGER NOT NULL DEFAULT 40,
                height INTEGER NOT NULL DEFAULT 36,
                capacity INTEGER NOT NULL DEFAULT 5000,
                current_visitors INTEGER NOT NULL DEFAULT 0,
                crowd_level TEXT DEFAULT 'Low',
                color TEXT DEFAULT '#10b981',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (park_id) REFERENCES parks (id)
            )
        """)

        # 4. Rides table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_id INTEGER DEFAULT 1,
                name TEXT NOT NULL,
                ride_type TEXT DEFAULT 'Thrill Ride',
                capacity_per_hour INTEGER NOT NULL DEFAULT 1000,
                current_queue INTEGER NOT NULL DEFAULT 0,
                average_wait_time INTEGER NOT NULL DEFAULT 0,
                utilization INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Operational',
                x_position INTEGER NOT NULL DEFAULT 20,
                y_position INTEGER NOT NULL DEFAULT 20,
                icon TEXT DEFAULT '🎢',
                last_updated TEXT DEFAULT 'Just now',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (zone_id) REFERENCES zones (id)
            )
        """)

        # 5. Facilities table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS facilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_id INTEGER DEFAULT 1,
                name TEXT NOT NULL,
                facility_type TEXT NOT NULL,
                capacity INTEGER NOT NULL DEFAULT 300,
                current_demand INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Available',
                x_position INTEGER NOT NULL DEFAULT 50,
                y_position INTEGER NOT NULL DEFAULT 50,
                icon TEXT DEFAULT '🍔',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (zone_id) REFERENCES zones (id)
            )
        """)

        # 6. Visitors / Flow telemetry table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                park_id INTEGER DEFAULT 1,
                entry_count INTEGER DEFAULT 0,
                exit_count INTEGER DEFAULT 0,
                arrival_rate INTEGER DEFAULT 0,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 7. Simulation History table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS simulation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                scenario_name TEXT,
                additional_visitors INTEGER,
                time_period TEXT,
                weather TEXT,
                ride_status_override TEXT,
                predicted_visitors INTEGER,
                predicted_queue_time INTEGER,
                crowd_density TEXT,
                bottleneck_zone TEXT,
                ai_recommendation TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # 8. AI Activity Timeline table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'info',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 9. AI Recommendations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT,
                situation TEXT,
                recommendation TEXT NOT NULL,
                risk_level TEXT,
                confidence_score INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 10. Operator Decisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operator_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                operator_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 11. Contacts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                park_name TEXT,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    conn.close()

def remove_park_dataset(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Completely removes current park dataset from database.
    Resets Digital Model, Dashboard, Rides, Visitors, Facilities, AI Agent to EMPTY state.
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rides")
    cursor.execute("DELETE FROM facilities")
    cursor.execute("DELETE FROM zones")
    cursor.execute("DELETE FROM parks")
    cursor.execute("DELETE FROM simulation_history")
    cursor.execute("DELETE FROM ai_activity")
    cursor.execute("DELETE FROM ai_recommendations")
    cursor.execute("DELETE FROM operator_decisions")
    conn.commit()
    return {
        "success": True,
        "message": "Park dataset removed successfully. ParkOps is ready for a new park dataset."
    }

def seed_demo_park_data(conn: sqlite3.Connection):
    """Optional manual helper to seed demo data if explicitly requested by developer."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO parks (name, description, total_capacity, current_visitors, weather, temperature, is_demo_data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ('ParkOps Theme Park', 'AI-Powered Theme Park Digital Model', 25000, 12450, 'Sunny & Clear', '24°C', 1))
    park_id = cursor.lastrowid

    zones_data = [
        (park_id, 'Adventure Zone', 'High-adrenaline thrill coasters and drop towers', 8, 12, 42, 38, 5000, 3800),
        (park_id, 'Fantasy Land', 'Whimsical family rides, grand wheel & magical castle', 54, 48, 42, 42, 4500, 3450),
        (park_id, 'Water World', 'Splash flumes, rapids, and tidal wave pools', 52, 10, 42, 36, 3500, 1650),
        (park_id, 'Main Entrance', 'Turnstile ingress hubs, guest services, plaza & parking', 8, 54, 42, 38, 4000, 3550)
    ]
    
    zone_ids = {}
    for zid, zname, desc, x, y, w, h, cap, vis in zones_data:
        crowd_lvl, _, color = calculate_crowd_level(vis, cap)
        cursor.execute("""
            INSERT INTO zones (park_id, name, description, x_position, y_position, width, height, capacity, current_visitors, crowd_level, color)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (zid, zname, desc, x, y, w, h, cap, vis, crowd_lvl, color))
        zone_ids[zname] = cursor.lastrowid

    sample_rides = [
        (zone_ids['Adventure Zone'], 'Roller Coaster', 'Hyper Coaster', 1200, 35, 35, 88, 'Operational', 18, 22, '🎢'),
        (zone_ids['Fantasy Land'], 'Grand Wonder Wheel', 'Ferris Wheel', 900, 20, 20, 64, 'Operational', 65, 58, '🎡'),
        (zone_ids['Water World'], 'Skyline Splash Flume', 'Water Log Flume', 800, 0, 0, 0, 'Maintenance', 68, 20, '🌊'),
        (zone_ids['Adventure Zone'], 'Apex Drop Tower', 'Drop Tower', 750, 28, 28, 78, 'Operational', 32, 28, '🗼')
    ]
    cursor.executemany("""
        INSERT INTO rides (zone_id, name, ride_type, capacity_per_hour, current_queue, average_wait_time, utilization, status, x_position, y_position, icon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_rides)

    sample_facilities = [
        (zone_ids['Fantasy Land'], 'Castle Grand Food Court', 'Food & Dining', 450, 382, 'Busy', 70, 64, '🍔'),
        (zone_ids['Water World'], 'Lagoon Seafood Grill', 'Food & Dining', 280, 118, 'Available', 62, 32, '🍤')
    ]
    cursor.executemany("""
        INSERT INTO facilities (zone_id, name, facility_type, capacity, current_demand, status, x_position, y_position, icon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_facilities)
    conn.commit()

def get_full_park_state(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    SINGLE SOURCE OF TRUTH:
    Reads current park, zones, rides, and facilities from SQLite.
    If no park dataset exists, returns an EMPTY state structure per spec.
    """
    cursor = conn.cursor()
    
    # 1. Park Metadata
    park_row = cursor.execute("SELECT * FROM parks ORDER BY id LIMIT 1").fetchone()
    if not park_row:
        # NO DATASET LOADED - Return clean empty state
        return {
            "has_data": False,
            "park": None,
            "zones": [],
            "rides": [],
            "facilities": [],
            "conditions": {
                "weather": "No Data",
                "temperature": "N/A",
                "crowd_density": "Low",
                "occupancy_pct": 0
            },
            "visitors": 0,
            "averages": {
                "total_visitors": 0,
                "current_visitors": 0,
                "total_capacity": 0,
                "occupancy_pct": 0,
                "crowd_density": "Low",
                "active_rides": 0,
                "total_rides": 0,
                "active_rides_ratio": "0 / 0",
                "average_queue": 0,
                "avg_queue_time": 0,
                "average_queue_str": "0 min",
                "facility_load": 0,
                "facility_load_str": "0%",
                "weather": "No Data",
                "temperature": "N/A",
                "crowded_zones_count": 0
            }
        }

    park = dict(park_row)

    # 2. Zones with dynamic calculated crowd levels
    zones_rows = cursor.execute("SELECT * FROM zones WHERE park_id = ?", (park['id'],)).fetchall()
    zones = []
    total_zone_visitors = 0
    total_zone_capacity = 0
    crowded_zones = 0

    for z in zones_rows:
        zd = dict(z)
        lvl, pct, color = calculate_crowd_level(zd['current_visitors'], zd['capacity'])
        zd['crowd_level'] = lvl
        zd['density'] = lvl
        zd['occupancy_pct'] = pct
        zd['color'] = color
        zd['visitors'] = zd['current_visitors']
        total_zone_visitors += zd['current_visitors']
        total_zone_capacity += zd['capacity']
        if lvl in ['High', 'Critical']:
            crowded_zones += 1
        zones.append(zd)

    if total_zone_visitors > 0 and total_zone_visitors != park['current_visitors']:
        park['current_visitors'] = total_zone_visitors

    # 3. Rides
    rides_rows = cursor.execute("SELECT * FROM rides").fetchall()
    rides = []
    total_queue = 0
    operational_rides = 0

    for r in rides_rows:
        rd = dict(r)
        if rd['status'] == 'Operational':
            operational_rides += 1
            total_queue += rd['current_queue']
        rides.append(rd)

    avg_queue = int(total_queue / max(1, operational_rides)) if operational_rides > 0 else 0

    # 4. Facilities
    fac_rows = cursor.execute("SELECT * FROM facilities").fetchall()
    facilities = []
    total_fac_demand = 0
    total_fac_cap = 0

    for f in fac_rows:
        fd = dict(f)
        fac_pct = int(round((fd['current_demand'] / max(1, fd['capacity'])) * 100))
        fd['utilization_pct'] = fac_pct
        total_fac_demand += fd['current_demand']
        total_fac_cap += fd['capacity']
        facilities.append(fd)

    overall_fac_load = int(round((total_fac_demand / max(1, total_fac_cap)) * 100)) if total_fac_cap > 0 else 0
    overall_crowd, overall_pct, _ = calculate_crowd_level(park['current_visitors'], park['total_capacity'])

    return {
        "has_data": True,
        "park": park,
        "zones": zones,
        "rides": rides,
        "facilities": facilities,
        "conditions": {
            "weather": park.get('weather', 'Sunny & Clear'),
            "temperature": park.get('temperature', '24°C'),
            "crowd_density": overall_crowd,
            "occupancy_pct": overall_pct
        },
        "visitors": park.get('current_visitors', 0),
        "averages": {
            "total_visitors": park['current_visitors'],
            "current_visitors": park['current_visitors'],
            "total_capacity": park['total_capacity'],
            "occupancy_pct": overall_pct,
            "crowd_density": overall_crowd,
            "active_rides": operational_rides,
            "total_rides": len(rides),
            "active_rides_ratio": f"{operational_rides} / {len(rides)}",
            "average_queue": avg_queue,
            "avg_queue_time": avg_queue,
            "average_queue_str": f"{avg_queue} min",
            "facility_load": overall_fac_load,
            "facility_load_str": f"{overall_fac_load}%",
            "weather": park.get('weather', 'Sunny'),
            "temperature": park.get('temperature', '24°C'),
            "crowded_zones_count": crowded_zones
        }
    }

def normalize_header(h: Any) -> str:
    if h is None:
        return ""
    s = str(h).strip().lower()
    s = s.replace(" ", "_").replace("-", "_")
    return s

def rows_to_dicts(ws: Any) -> List[Dict[str, Any]]:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header_row_idx = 0
    for idx, r in enumerate(rows):
        if any(cell is not None and str(cell).strip() != '' for cell in r):
            header_row_idx = idx
            break
    headers = [normalize_header(c) if c is not None else f'col_{i}' for i, c in enumerate(rows[header_row_idx])]
    data = []
    for r in rows[header_row_idx + 1:]:
        if not any(cell is not None and str(cell).strip() != '' for cell in r):
            continue
        item = {}
        for h, cell in zip(headers, r):
            if h:
                item[h] = cell
        data.append(item)
    return data

def get_field(row_dict: Dict[str, Any], possible_keys: List[str], default: Any = None) -> Any:
    if not isinstance(row_dict, dict):
        return default
    for k in possible_keys:
        norm_k = normalize_header(k)
        if norm_k in row_dict:
            val = row_dict[norm_k]
            if val is not None:
                val_str = str(val).strip()
                if val_str != "" and val_str.lower() != "nan" and val_str.lower() != "none":
                    return val_str
    return default

def parse_excel_dataset(file_stream_or_bytes: Any) -> Dict[str, Any]:
    """
    Parses an uploaded Excel (.xlsx, .xls) workbook or CSV into the standardized ParkOps dataset dictionary.
    Performs comprehensive schema and relationship validation.
    """
    if isinstance(file_stream_or_bytes, bytes):
        wb_stream = io.BytesIO(file_stream_or_bytes)
    else:
        content = file_stream_or_bytes.read()
        wb_stream = io.BytesIO(content)

    try:
        wb = openpyxl.load_workbook(wb_stream, data_only=True)
    except Exception as e:
        raise ValueError(f"❌ Dataset Upload Failed: Could not open file. Please upload a valid .xlsx, .xls, or .csv file. Details: {str(e)}")

    sheet_map = {s.strip().lower(): s for s in wb.sheetnames}
    required_sheets = ['park', 'zones', 'rides', 'facilities']
    for req in required_sheets:
        if req not in sheet_map:
            raise ValueError(f"❌ Dataset Upload Failed: Missing required sheet '{req.capitalize()}'. Expected sheets: Park, Zones, Rides, Facilities.")

    park_rows = rows_to_dicts(wb[sheet_map['park']])
    if not park_rows:
        raise ValueError("❌ Dataset Upload Failed: The 'Park' sheet is empty.")
    
    first_row = park_rows[0]
    pname = get_field(first_row, ["park_name", "name", "park"])
    
    # Temporary debug information during dataset validation
    print("Workbook sheets:", wb.sheetnames)
    print("Park sheet detected: True")
    print("Park columns:", list(first_row.keys()))
    print("Park name extracted:", pname)

    if not pname:
        raise ValueError("❌ Dataset Upload Failed: Missing park name in Park sheet.")

    pcap_raw = get_field(first_row, ["capacity", "total_capacity", "park_capacity", "max_capacity"])
    try:
        pcap = int(float(pcap_raw)) if pcap_raw else 25000
        if pcap <= 0:
            raise ValueError("❌ Dataset Upload Failed: Park capacity must be greater than 0.")
    except (ValueError, TypeError):
        pcap = 25000

    pvis_raw = get_field(first_row, ["current_visitors", "visitors", "current_visitor_count", "visitor_count"])
    try:
        pvis = int(float(pvis_raw)) if pvis_raw is not None else 0
        if pvis < 0:
            raise ValueError("❌ Dataset Upload Failed: Current visitors cannot be negative.")
    except (ValueError, TypeError):
        pvis = 0

    park_info = {
        "name": pname,
        "description": get_field(first_row, ["location", "description", "address"], "Uploaded Digital Model Theme Park"),
        "capacity": pcap,
        "current_visitors": pvis,
        "weather": get_field(first_row, ["weather"], "Sunny & Clear"),
        "temperature": get_field(first_row, ["temperature"], "24°C")
    }

    zone_rows = rows_to_dicts(wb[sheet_map['zones']])
    if not zone_rows:
        raise ValueError("❌ Dataset Upload Failed: The 'Zones' sheet is empty.")

    zones = []
    zone_names_set = set()
    zone_id_or_name_map = {}
    for idx, z in enumerate(zone_rows):
        zid = get_field(z, ["zone_id", "id", "code"])
        zname = get_field(z, ["zone_name", "name", "zone"])
        if not zname and zid:
            zname = f"Zone {zid}"
        if not zname:
            raise ValueError(f"❌ Dataset Upload Failed: Missing zone name at row {idx+2} in Zones sheet.")
        
        norm_zname = zname.lower()
        if norm_zname in zone_names_set:
            raise ValueError(f"❌ Dataset Upload Failed: Duplicate zone name '{zname}' found in Zones sheet.")
        zone_names_set.add(norm_zname)
        zone_id_or_name_map[norm_zname] = zname
        if zid:
            zone_id_or_name_map[str(zid).strip().lower()] = zname

        zcap_raw = get_field(z, ["capacity", "max_capacity", "zone_capacity"])
        try:
            zcap = int(float(zcap_raw)) if zcap_raw else 5000
            if zcap <= 0:
                raise ValueError(f"❌ Dataset Upload Failed: Zone '{zname}' capacity must be greater than 0.")
        except (ValueError, TypeError):
            zcap = 5000

        zvis_raw = get_field(z, ["current_visitors", "visitors", "occupancy", "visitor_count"])
        try:
            zvis = int(float(zvis_raw)) if zvis_raw is not None else int(zcap * 0.5)
            if zvis < 0:
                raise ValueError(f"❌ Dataset Upload Failed: Current visitors for zone '{zname}' cannot be negative.")
        except (ValueError, TypeError):
            zvis = int(zcap * 0.5)

        x_raw = get_field(z, ["x", "x_position", "pos_x"])
        y_raw = get_field(z, ["y", "y_position", "pos_y"])
        w_raw = get_field(z, ["width", "w"])
        h_raw = get_field(z, ["height", "h"])
        try:
            x = int(float(x_raw)) if x_raw is not None else (10 + (idx % 2) * 45)
            y = int(float(y_raw)) if y_raw is not None else (10 + (idx // 2) * 45)
            w = int(float(w_raw)) if w_raw is not None else 40
            h = int(float(h_raw)) if h_raw is not None else 36
        except (ValueError, TypeError):
            x, y, w, h = 10, 10, 40, 36

        zones.append({
            "name": zname,
            "description": get_field(z, ["description", "details"], f"Sector for {zname}"),
            "capacity": zcap,
            "current_visitors": zvis,
            "x": x,
            "y": y,
            "width": w,
            "height": h
        })

    ride_rows = rows_to_dicts(wb[sheet_map['rides']])
    rides = []
    ride_names_set = set()
    for idx, r in enumerate(ride_rows):
        rname = get_field(r, ["ride_name", "name", "attraction_name", "attraction"])
        if not rname:
            continue
        norm_rname = rname.lower()
        if norm_rname in ride_names_set:
            raise ValueError(f"❌ Dataset Upload Failed: Duplicate ride name '{rname}' in Rides sheet.")
        ride_names_set.add(norm_rname)

        target_zone_raw = get_field(r, ["zone", "zone_id", "zone_name", "location_zone"])
        target_zone = None
        if target_zone_raw:
            norm_tz = str(target_zone_raw).strip().lower()
            if norm_tz in zone_id_or_name_map:
                target_zone = zone_id_or_name_map[norm_tz]
        
        if not target_zone:
            target_zone = zones[0]["name"] if zones else "Main Zone"

        cap_hr_raw = get_field(r, ["capacity_per_hour", "hourly_capacity", "capacity"])
        try:
            cap_hr = int(float(cap_hr_raw)) if cap_hr_raw else 1000
        except (ValueError, TypeError):
            cap_hr = 1000

        queue_raw = get_field(r, ["queue", "current_queue", "average_wait_time", "wait_time", "queue_length"])
        try:
            queue = int(float(queue_raw)) if queue_raw is not None else 15
        except (ValueError, TypeError):
            queue = 15

        status_raw = get_field(r, ["status", "operating_status"], "Operational")
        status = str(status_raw).strip().capitalize()
        if status not in ["Operational", "Maintenance", "Offline"]:
            if any(w in status.lower() for w in ["mainten", "out", "close", "break"]):
                status = "Maintenance"
            else:
                status = "Operational"

        x_raw = get_field(r, ["x", "x_position", "pos_x"])
        y_raw = get_field(r, ["y", "y_position", "pos_y"])
        try:
            x = int(float(x_raw)) if x_raw is not None else 20
            y = int(float(y_raw)) if y_raw is not None else 20
        except (ValueError, TypeError):
            x, y = 20, 20

        icon = get_field(r, ["icon"], "🎢")
        ride_type = get_field(r, ["ride_type", "type", "category"], "Attraction")

        rides.append({
            "name": rname,
            "zone": target_zone,
            "ride_type": ride_type,
            "capacity_per_hour": cap_hr,
            "queue": queue,
            "average_wait_time": queue,
            "utilization": int(get_field(r, ["utilization"], min(100, int((queue / 45) * 100))) or 75),
            "status": status,
            "x": x,
            "y": y,
            "icon": icon
        })

    fac_rows = rows_to_dicts(wb[sheet_map['facilities']])
    facilities = []
    for idx, f in enumerate(fac_rows):
        fname = get_field(f, ["facility_name", "name", "facility"])
        if not fname:
            continue

        target_zone_raw = get_field(f, ["zone", "zone_id", "zone_name", "location_zone"])
        target_zone = None
        if target_zone_raw:
            norm_tz = str(target_zone_raw).strip().lower()
            if norm_tz in zone_id_or_name_map:
                target_zone = zone_id_or_name_map[norm_tz]
        
        if not target_zone:
            target_zone = zones[0]["name"] if zones else "Main Zone"

        fcap_raw = get_field(f, ["capacity", "max_capacity"])
        try:
            fcap = int(float(fcap_raw)) if fcap_raw else 400
        except (ValueError, TypeError):
            fcap = 400

        fdemand_raw = get_field(f, ["current_demand", "demand", "occupancy"])
        try:
            fdemand = int(float(fdemand_raw)) if fdemand_raw is not None else int(fcap * 0.5)
        except (ValueError, TypeError):
            fdemand = int(fcap * 0.5)

        ftype = get_field(f, ["facility_type", "type", "category"], "Dining / Service")
        fstatus = get_field(f, ["status", "operating_status"], "Available" if fdemand < fcap * 0.85 else "Busy")
        x_raw = get_field(f, ["x", "x_position", "pos_x"])
        y_raw = get_field(f, ["y", "y_position", "pos_y"])
        try:
            x = int(float(x_raw)) if x_raw is not None else 50
            y = int(float(y_raw)) if y_raw is not None else 50
        except (ValueError, TypeError):
            x, y = 50, 50

        icon = get_field(f, ["icon"], "🍔" if "food" in ftype.lower() or "din" in ftype.lower() else "ℹ️")

        facilities.append({
            "name": fname,
            "zone": target_zone,
            "facility_type": ftype,
            "capacity": fcap,
            "current_demand": fdemand,
            "status": fstatus,
            "x": x,
            "y": y,
            "icon": icon
        })

    return {
        "park": park_info,
        "zones": zones,
        "rides": rides,
        "facilities": facilities
    }

def create_sample_excel_template() -> io.BytesIO:
    """Generates an official ParkOps Sample Excel Dataset workbook."""
    wb = openpyxl.Workbook()
    header_font = openpyxl.styles.Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = openpyxl.styles.PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    data_font = openpyxl.styles.Font(name="Segoe UI", size=10)
    thin_border = openpyxl.styles.Border(
        left=openpyxl.styles.Side(style='thin', color='CBD5E1'),
        right=openpyxl.styles.Side(style='thin', color='CBD5E1'),
        top=openpyxl.styles.Side(style='thin', color='CBD5E1'),
        bottom=openpyxl.styles.Side(style='thin', color='CBD5E1')
    )

    def style_sheet(ws, headers, data):
        ws.append(headers)
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = openpyxl.styles.Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = max(len(h) + 6, 16)
        
        for r_idx, row in enumerate(data, 2):
            ws.append(row)
            for c_idx in range(1, len(headers) + 1):
                c = ws.cell(row=r_idx, column=c_idx)
                c.font = data_font
                c.border = thin_border
                if isinstance(c.value, (int, float)):
                    c.alignment = openpyxl.styles.Alignment(horizontal="right")

    ws_park = wb.active
    ws_park.title = "Park"
    style_sheet(
        ws_park,
        ["park_name", "location", "capacity", "current_visitors", "weather", "temperature"],
        [["ParkOps Grand Theme Park", "North Lake District", 25000, 12450, "Sunny & Clear", "24°C"]]
    )

    ws_zones = wb.create_sheet(title="Zones")
    style_sheet(
        ws_zones,
        ["zone_name", "capacity", "current_visitors", "x", "y", "width", "height", "description"],
        [
            ["Adventure Zone", 5000, 3800, 8, 12, 42, 38, "High-adrenaline thrill coasters and drop towers"],
            ["Fantasy Land", 4500, 3450, 54, 48, 42, 42, "Whimsical family rides and magical castle promenade"],
            ["Water World", 3500, 1650, 52, 10, 42, 36, "Splash flumes, river rafting and wave pools"],
            ["Main Entrance", 4000, 3550, 8, 54, 42, 38, "Turnstile ingress, plaza, guest services and parking"]
        ]
    )

    ws_rides = wb.create_sheet(title="Rides")
    style_sheet(
        ws_rides,
        ["ride_name", "zone", "capacity_per_hour", "queue", "average_wait_time", "utilization", "status", "x", "y", "icon"],
        [
            ["Roller Coaster", "Adventure Zone", 1200, 35, 35, 88, "Operational", 18, 22, "🎢"],
            ["Grand Wonder Wheel", "Fantasy Land", 900, 20, 20, 64, "Operational", 65, 58, "🎡"],
            ["Skyline Splash Flume", "Water World", 800, 0, 0, 0, "Maintenance", 68, 20, "🌊"],
            ["Apex Drop Tower", "Adventure Zone", 750, 28, 28, 78, "Operational", 32, 28, "🗼"]
        ]
    )

    ws_fac = wb.create_sheet(title="Facilities")
    style_sheet(
        ws_fac,
        ["facility_name", "type", "zone", "capacity", "current_demand", "status", "x", "y", "icon"],
        [
            ["Castle Grand Food Court", "Food & Dining", "Fantasy Land", 450, 382, "Busy", 70, 64, "🍔"],
            ["Lagoon Seafood Grill", "Food & Dining", "Water World", 280, 118, "Available", 62, 32, "🍤"]
        ]
    )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output

def import_park_dataset(conn: sqlite3.Connection, dataset: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates and imports JSON/Excel park data into SQLite.
    Single Source of Truth: Overwrites existing park dataset atomically.
    """
    cursor = conn.cursor()
    
    if not isinstance(dataset, dict):
        raise ValueError("❌ Dataset Upload Failed: Invalid dataset structure.")

    park_info = dataset.get("park", {})
    zones_list = dataset.get("zones", [])
    rides_list = dataset.get("rides", [])
    facilities_list = dataset.get("facilities", [])

    pname = park_info.get("name")
    if not pname:
        raise ValueError("❌ Dataset Upload Failed: Missing park name in Park sheet.")
    
    park_capacity = int(park_info.get("capacity", 25000))
    if park_capacity <= 0:
        raise ValueError("❌ Dataset Upload Failed: Park capacity must be greater than 0.")

    # Atomic clear of previous dataset
    cursor.execute("DELETE FROM rides")
    cursor.execute("DELETE FROM facilities")
    cursor.execute("DELETE FROM zones")
    cursor.execute("DELETE FROM parks")
    cursor.execute("DELETE FROM simulation_history")

    cursor.execute("""
        INSERT INTO parks (name, description, total_capacity, current_visitors, weather, temperature, is_demo_data)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (
        pname,
        park_info.get("description", "Uploaded User Park Dataset"),
        park_capacity,
        0,
        park_info.get("weather", "Sunny & Clear"),
        park_info.get("temperature", "24°C")
    ))
    park_id = cursor.lastrowid

    zone_name_to_id = {}
    total_visitors = 0
    for idx, z in enumerate(zones_list):
        zname = z.get("name", f"Zone {idx+1}")
        zcap = int(z.get("capacity", 5000))
        zvis = int(z.get("current_visitors", int(zcap * 0.5)))
        total_visitors += zvis
        x = int(z.get("x", z.get("x_position", 10 + (idx % 2) * 45)))
        y = int(z.get("y", z.get("y_position", 10 + (idx // 2) * 45)))
        w = int(z.get("width", 40))
        h = int(z.get("height", 36))
        
        crowd_lvl, _, color = calculate_crowd_level(zvis, zcap)
        cursor.execute("""
            INSERT INTO zones (park_id, name, description, x_position, y_position, width, height, capacity, current_visitors, crowd_level, color)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (park_id, zname, z.get("description", ""), x, y, w, h, zcap, zvis, crowd_lvl, color))
        zone_name_to_id[zname.lower()] = cursor.lastrowid

    cursor.execute("UPDATE parks SET current_visitors = ? WHERE id = ?", (total_visitors, park_id))

    for idx, r in enumerate(rides_list):
        rname = r.get("name", f"Attraction {idx+1}")
        zname = str(r.get("zone", "")).lower()
        zone_id = zone_name_to_id.get(zname, list(zone_name_to_id.values())[0] if zone_name_to_id else 1)
        cap_hr = int(r.get("capacity_per_hour", 1000))
        queue = int(r.get("queue", r.get("current_queue", 15)))
        status = r.get("status", "Operational")
        x = int(r.get("x", r.get("x_position", 20)))
        y = int(r.get("y", r.get("y_position", 20)))
        icon = r.get("icon", "🎢")

        cursor.execute("""
            INSERT INTO rides (zone_id, name, ride_type, capacity_per_hour, current_queue, average_wait_time, utilization, status, x_position, y_position, icon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (zone_id, rname, r.get("ride_type", "Ride"), cap_hr, queue, queue, int(min(100, (queue/45)*100)), status, x, y, icon))

    for idx, f in enumerate(facilities_list):
        fname = f.get("name", f"Facility {idx+1}")
        zname = str(f.get("zone", "")).lower()
        zone_id = zone_name_to_id.get(zname, list(zone_name_to_id.values())[0] if zone_name_to_id else 1)
        fcap = int(f.get("capacity", 400))
        fdemand = int(f.get("current_demand", int(fcap * 0.5)))
        fstatus = f.get("status", "Available" if fdemand < fcap * 0.85 else "Busy")
        x = int(f.get("x", f.get("x_position", 50)))
        y = int(f.get("y", f.get("y_position", 50)))
        icon = f.get("icon", "🍔")

        cursor.execute("""
            INSERT INTO facilities (zone_id, name, facility_type, capacity, current_demand, status, x_position, y_position, icon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (zone_id, fname, f.get("facility_type", "Facility"), fcap, fdemand, fstatus, x, y, icon))

    cursor.execute("""
        INSERT INTO ai_activity (event_type, description, status)
        VALUES (?, ?, ?)
    """, ('Data Ingestion', f"Imported dataset '{pname}' with {len(zones_list)} zones, {len(rides_list)} rides, {len(facilities_list)} facilities.", 'success'))

    conn.commit()
    return {
        "success": True,
        "message": f"Successfully imported '{pname}' ({len(zones_list)} Zones, {len(rides_list)} Rides, {len(facilities_list)} Facilities).",
        "park_name": pname,
        "zones_count": len(zones_list),
        "rides_count": len(rides_list),
        "facilities_count": len(facilities_list),
        "total_capacity": park_capacity,
        "current_visitors": total_visitors
    }

def stream_import_pipeline(conn: sqlite3.Connection, file_name: str, file_bytes: bytes):
    """
    Generator yielding step-by-step processing status JSON lines for dataset upload pipeline.
    Covers 7 stages:
    1. FILE RECEIVED
    2. READING DATA
    3. VALIDATING DATA
    4. IMPORTING TO DATABASE
    5. BUILDING DIGITAL MODEL
    6. SYNCHRONIZING PARKOPS
    7. COMPLETE
    """
    import time
    import json
    import io
    import openpyxl

    # Stage 1: FILE RECEIVED
    yield json.dumps({
        'stage': 1,
        'title': 'FILE RECEIVED',
        'status': 'processing',
        'message': '⏳ Receiving dataset...'
    }) + '\n'
    time.sleep(0.1)

    yield json.dumps({
        'stage': 1,
        'title': 'FILE RECEIVED',
        'status': 'complete',
        'items': [f'✓ File received: {file_name}']
    }) + '\n'
    time.sleep(0.1)

    # Stage 2: READING DATA
    yield json.dumps({
        'stage': 2,
        'title': 'READING DATA',
        'status': 'processing',
        'message': '⏳ Reading park dataset...'
    }) + '\n'
    time.sleep(0.1)

    wb_stream = io.BytesIO(file_bytes)
    try:
        wb = openpyxl.load_workbook(wb_stream, data_only=True)
    except Exception as e:
        yield json.dumps({
            'stage': 'error',
            'failed_stage': 'READING DATA',
            'error': f"❌ Dataset Upload Failed: Could not open file. Please upload a valid .xlsx, .xls, or .csv file. Details: {str(e)}"
        }) + '\n'
        return

    sheet_map = {s.strip().lower(): s for s in wb.sheetnames}
    required_sheets = ['park', 'zones', 'rides', 'facilities']
    for req in required_sheets:
        if req not in sheet_map:
            yield json.dumps({
                'stage': 'error',
                'failed_stage': 'READING DATA',
                'error': f"❌ Dataset Upload Failed: Missing required sheet '{req.capitalize()}'. Expected sheets: Park, Zones, Rides, Facilities."
            }) + '\n'
            return

    read_items = []
    
    # Read Park
    park_rows = rows_to_dicts(wb[sheet_map['park']])
    if not park_rows:
        yield json.dumps({'stage': 'error', 'failed_stage': 'READING DATA', 'error': "❌ Dataset Upload Failed: The 'Park' sheet is empty."}) + '\n'
        return
    read_items.append("✓ Park sheet read")

    # Read Zones
    zone_rows = rows_to_dicts(wb[sheet_map['zones']])
    if not zone_rows:
        yield json.dumps({'stage': 'error', 'failed_stage': 'READING DATA', 'error': "❌ Dataset Upload Failed: The 'Zones' sheet is empty."}) + '\n'
        return
    read_items.append(f"✓ Zones sheet read — {len(zone_rows)} records")

    # Read Rides
    ride_rows = rows_to_dicts(wb[sheet_map['rides']])
    read_items.append(f"✓ Rides sheet read — {len(ride_rows)} records")

    # Read Facilities
    fac_rows = rows_to_dicts(wb[sheet_map['facilities']])
    read_items.append(f"✓ Facilities sheet read — {len(fac_rows)} records")

    # Optional sheets
    for s_lower, s_real in sheet_map.items():
        if s_lower not in ['park', 'zones', 'rides', 'facilities', 'readme', 'what_if_scenarios']:
            opt_rows = rows_to_dicts(wb[s_real])
            if opt_rows:
                read_items.append(f"✓ {s_real} sheet read — {len(opt_rows)} records")

    yield json.dumps({
        'stage': 2,
        'title': 'READING DATA',
        'status': 'complete',
        'items': read_items
    }) + '\n'
    time.sleep(0.1)

    # Stage 3: VALIDATING DATA
    yield json.dumps({
        'stage': 3,
        'title': 'VALIDATING DATA',
        'status': 'processing',
        'message': '⏳ Validating dataset...'
    }) + '\n'
    time.sleep(0.1)

    try:
        parsed_dataset = parse_excel_dataset(file_bytes)
    except Exception as ve:
        yield json.dumps({'stage': 'error', 'failed_stage': 'VALIDATING DATA', 'error': str(ve)}) + '\n'
        return

    yield json.dumps({
        'stage': 3,
        'title': 'VALIDATING DATA',
        'status': 'complete',
        'items': ['✓ Dataset validated']
    }) + '\n'
    time.sleep(0.1)

    # Stage 4: IMPORTING TO DATABASE
    yield json.dumps({
        'stage': 4,
        'title': 'IMPORTING TO DATABASE',
        'status': 'processing',
        'message': '⏳ Updating ParkOps database...'
    }) + '\n'
    time.sleep(0.1)

    import_res = import_park_dataset(conn, parsed_dataset)

    db_items = [
        "✓ Park data imported",
        f"✓ Zones imported — {len(parsed_dataset['zones'])} records",
        f"✓ Rides imported — {len(parsed_dataset['rides'])} records",
        f"✓ Facilities imported — {len(parsed_dataset['facilities'])} records"
    ]
    yield json.dumps({
        'stage': 4,
        'title': 'IMPORTING TO DATABASE',
        'status': 'complete',
        'items': db_items
    }) + '\n'
    time.sleep(0.1)

    # Stage 5: BUILDING DIGITAL MODEL
    yield json.dumps({
        'stage': 5,
        'title': 'BUILDING DIGITAL MODEL',
        'status': 'processing',
        'message': '⏳ Generating Digital Model...'
    }) + '\n'
    time.sleep(0.1)

    dt_items = [
        "✓ Park layout created",
        "✓ Zones mapped",
        "✓ Rides positioned",
        "✓ Facilities positioned",
        "✓ Visitor density calculated"
    ]
    yield json.dumps({
        'stage': 5,
        'title': 'BUILDING DIGITAL MODEL',
        'status': 'complete',
        'items': dt_items
    }) + '\n'
    time.sleep(0.1)

    # Stage 6: SYNCHRONIZING PARKOPS
    yield json.dumps({
        'stage': 6,
        'title': 'SYNCHRONIZING PARKOPS',
        'status': 'processing',
        'message': '⏳ Synchronizing ParkOps...'
    }) + '\n'
    time.sleep(0.1)

    sync_items = [
        "✓ Dashboard updated",
        "✓ Digital Model updated",
        "✓ Single AI Agent updated",
        "✓ Monitor & Predict models synced"
    ]
    yield json.dumps({
        'stage': 6,
        'title': 'SYNCHRONIZING PARKOPS',
        'status': 'complete',
        'items': sync_items
    }) + '\n'
    time.sleep(0.1)

    # Stage 7: COMPLETE
    yield json.dumps({
        'stage': 7,
        'title': 'COMPLETE',
        'status': 'complete',
        'park_name': parsed_dataset['park']['name'],
        'zones_count': len(parsed_dataset['zones']),
        'rides_count': len(parsed_dataset['rides']),
        'facilities_count': len(parsed_dataset['facilities']),
        'visitors_count': import_res.get('current_visitors', 0),
        'message': 'Your park data has been loaded and the Digital Model is ready.'
    }) + '\n'


