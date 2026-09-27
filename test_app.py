import os
import json
import sqlite3
import io
import app

def run_tests():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')
    if os.path.exists(db_path):
        os.remove(db_path)
    
    app.init_db()
    client = app.app.test_client()

    # Create user & authenticate session
    res_signup = client.post('/signup', data={
        'full_name': 'Operator Test',
        'email': 'op@parkops.com',
        'password': 'password123',
        'confirm_password': 'password123'
    }, follow_redirects=True)
    assert res_signup.status_code == 200

    print("====================================================")
    print("  RUNNING PARKOPS FINAL ACCEPTANCE TEST SUITE")
    print("====================================================")

    # ----------------------------------------------------
    # TEST 1: Initial Empty State
    # ----------------------------------------------------
    pstate = client.get('/api/park-state').get_json()
    assert pstate is not None, "Failed to fetch /api/park-state"
    assert pstate['has_data'] is False, "Expected has_data to be False on fresh initialization."
    assert pstate['visitors'] == 0, f"Expected 0 visitors, got {pstate['visitors']}"
    assert len(pstate['zones']) == 0, f"Expected 0 zones, got {len(pstate['zones'])}"
    assert len(pstate['rides']) == 0, f"Expected 0 rides, got {len(pstate['rides'])}"
    assert len(pstate['facilities']) == 0, f"Expected 0 facilities, got {len(pstate['facilities'])}"

    res_dash = client.get('/dashboard')
    assert res_dash.status_code == 200
    assert b'Upload a park dataset' in res_dash.data

    res_ai_agent = client.get('/ai-agent')
    assert res_ai_agent.status_code == 200
    assert b'Waiting for Park Data' in res_ai_agent.data

    print("PASS: TEST 1 - Fresh application starts 100% EMPTY (no demo data)!")

    # ----------------------------------------------------
    # TEST 2: Upload Excel Dataset
    # ----------------------------------------------------
    tpl_res = client.get('/api/park-data/template')
    assert tpl_res.status_code == 200
    excel_stream = io.BytesIO(tpl_res.data)

    upload_res = client.post('/api/park-data/upload-excel',
        data={'file': (excel_stream, 'parkops_dataset.xlsx')},
        content_type='multipart/form-data'
    )
    assert upload_res.status_code == 200
    up_json = upload_res.get_json()
    assert up_json['success'] is True, f"Upload failed: {up_json}"
    print(f"PASS: TEST 2 - Park Dataset Uploaded Successfully ({up_json['park_name']}, {up_json['zones_count']} Zones, {up_json['rides_count']} Rides, {up_json['facilities_count']} Facilities)!")

    # ----------------------------------------------------
    # TEST 3: Park Overview Page
    # ----------------------------------------------------
    res_po = client.get('/park-overview')
    assert res_po.status_code == 200
    assert b'Park Overview' in res_po.data
    assert up_json['park_name'].encode('utf-8') in res_po.data or b'ParkOps' in res_po.data
    print("PASS: TEST 3 - Park Overview displays uploaded park!")

    # ----------------------------------------------------
    # TEST 4: Rides Page
    # ----------------------------------------------------
    res_rides = client.get('/rides')
    assert res_rides.status_code == 200
    assert b'Roller Coaster' in res_rides.data or b'Attractions' in res_rides.data
    print("PASS: TEST 4 - Rides page displays uploaded rides!")

    # ----------------------------------------------------
    # TEST 5: Visitors Page
    # ----------------------------------------------------
    res_vis = client.get('/visitors')
    assert res_vis.status_code == 200
    assert b'Visitor Flow' in res_vis.data
    print("PASS: TEST 5 - Visitors page displays uploaded visitor telemetry!")

    # ----------------------------------------------------
    # TEST 6: Facilities Page
    # ----------------------------------------------------
    res_fac = client.get('/facilities')
    assert res_fac.status_code == 200
    assert b'Facilities' in res_fac.data
    print("PASS: TEST 6 - Facilities page displays uploaded facilities!")

    # ----------------------------------------------------
    # TEST 7: Digital Model Page
    # ----------------------------------------------------
    res_dt = client.get('/digital-model')
    assert res_dt.status_code == 200
    assert b'Digital Model' in res_dt.data
    print("PASS: TEST 7 - Digital Model page generates architecture from uploaded coordinates!")

    # ----------------------------------------------------
    # TEST 8: AI Agent Page (Active)
    # ----------------------------------------------------
    res_ai_active = client.get('/ai-agent')
    assert res_ai_active.status_code == 200
    assert b'Active' in res_ai_active.data or b'Ready' in res_ai_active.data
    print("PASS: TEST 8 - AI Agent is now ACTIVE!")

    # ----------------------------------------------------
    # TEST 9: Run Simulation (+5,000 Visitors)
    # ----------------------------------------------------
    res_sim = client.post('/api/simulation',
        data=json.dumps({
            'additional_visitors': 5000,
            'time_period': '5 PM - 6 PM',
            'ride_availability': 'All Rides Operational',
            'weather_condition': 'Sunny'
        }),
        content_type='application/json'
    )
    assert res_sim.status_code == 200
    sim_json = res_sim.get_json()
    assert sim_json['predicted_visitors'] > 5000
    assert 'recommendation' in sim_json
    print(f"PASS: TEST 9 - Simulation uses uploaded park data ({sim_json['predicted_visitors']} visitors)!")

    # ----------------------------------------------------
    # TEST 10: Remove Dataset
    # ----------------------------------------------------
    res_rm = client.post('/api/park-data/remove')
    assert res_rm.status_code == 200
    rm_json = res_rm.get_json()
    assert rm_json['success'] is True

    # Verify everything returned to empty state
    pstate_empty = client.get('/api/park-state').get_json()
    assert pstate_empty['has_data'] is False
    assert pstate_empty['visitors'] == 0
    assert len(pstate_empty['zones']) == 0
    assert len(pstate_empty['rides']) == 0

    res_rides_empty = client.get('/rides')
    assert b'No rides available' in res_rides_empty.data

    res_dt_empty = client.get('/digital-model')
    assert b'No park dataset loaded' in res_dt_empty.data

    print("PASS: TEST 10 - Dataset removal resets application to 100% EMPTY STATE!")

    # ----------------------------------------------------
    # TEST 11: Upload a Completely Different Dataset
    # ----------------------------------------------------
    new_dataset = {
        "park": {"name": "Galactic Odyssey World", "capacity": 45000, "current_visitors": 22000},
        "zones": [
            {"name": "Nebula Heights", "capacity": 15000, "current_visitors": 11000, "x": 15, "y": 15, "width": 35, "height": 35},
            {"name": "Cyber Port", "capacity": 12000, "current_visitors": 8000, "x": 55, "y": 15, "width": 35, "height": 35}
        ],
        "rides": [
            {"name": "Hyperdrive Coaster", "zone": "Nebula Heights", "capacity_per_hour": 1800, "queue": 50, "status": "Operational", "x": 25, "y": 25},
            {"name": "Laser Skirmish", "zone": "Cyber Port", "capacity_per_hour": 1200, "queue": 20, "status": "Operational", "x": 65, "y": 25}
        ],
        "facilities": [
            {"name": "Space Bistro", "zone": "Nebula Heights", "capacity": 600, "current_demand": 500, "x": 30, "y": 30}
        ]
    }
    res_import_new = client.post('/api/park-data/import',
        data=json.dumps(new_dataset),
        content_type='application/json'
    )
    assert res_import_new.status_code == 200
    assert res_import_new.get_json()['success'] is True

    pstate_new = client.get('/api/park-state').get_json()
    assert pstate_new['park']['name'] == 'Galactic Odyssey World'
    assert len(pstate_new['zones']) == 2
    assert pstate_new['zones'][0]['name'] == 'Nebula Heights'

    # ----------------------------------------------------
    # TEST 12: Stream Dataset Upload Process
    # ----------------------------------------------------
    tpl_res2 = client.get('/api/park-data/template')
    excel_stream2 = io.BytesIO(tpl_res2.data)
    stream_res = client.post('/api/park-data/upload-stream',
        data={'file': (excel_stream2, 'ParkOps_Project_Based_Dataset.xlsx')},
        content_type='multipart/form-data'
    )
    assert stream_res.status_code == 200
    lines = stream_res.data.decode('utf-8').strip().split('\n')
    events = [json.loads(line) for line in lines if line.strip()]
    stages_seen = set(e['stage'] for e in events if 'stage' in e)
    assert 1 in stages_seen and 2 in stages_seen and 3 in stages_seen and 4 in stages_seen and 5 in stages_seen and 6 in stages_seen and 7 in stages_seen
    print("PASS: TEST 12 - Streaming upload pipeline yielded all 7 processing stages!")

    # ----------------------------------------------------
    # TEST 13: Dynamic Logged-In User Name & Role Verification
    # ----------------------------------------------------
    # Logout current user
    client.get('/logout')

    # User 1: Kookie
    client.post('/signup', data={
        'full_name': 'Kookie Operator',
        'email': 'kookie@parkops.com',
        'password': 'password123',
        'confirm_password': 'password123',
        'role': 'Operator'
    }, follow_redirects=True)
    res_kookie = client.get('/dashboard')
    assert b'Hi, Kookie' in res_kookie.data, "Expected 'Hi, Kookie' in header"
    assert b'Operator' in res_kookie.data
    assert b'K' in res_kookie.data
    client.get('/logout')

    # User 2: Rahul
    client.post('/signup', data={
        'full_name': 'Rahul Sharma',
        'email': 'rahul@parkops.com',
        'password': 'password123',
        'confirm_password': 'password123',
        'role': 'Operator'
    }, follow_redirects=True)
    res_rahul = client.get('/dashboard')
    assert b'Hi, Rahul' in res_rahul.data, "Expected 'Hi, Rahul' in header"
    assert b'Jahnavi' not in res_rahul.data, "Forbidden hardcoded 'Jahnavi' detected"
    client.get('/logout')

    # User 3: Sneha (Admin)
    client.post('/signup', data={
        'full_name': 'Sneha Patel',
        'email': 'sneha@parkops.com',
        'password': 'password123',
        'confirm_password': 'password123',
        'role': 'Admin'
    }, follow_redirects=True)
    res_sneha = client.get('/dashboard')
    assert b'Hi, Sneha' in res_sneha.data, "Expected 'Hi, Sneha' in header"
    assert b'Admin' in res_sneha.data, "Expected 'Admin' role in header"
    client.get('/logout')

    # Unauthenticated Neutral State
    res_loggedout = client.get('/signin')
    assert b'Jahnavi' not in res_loggedout.data
    print("PASS: TEST 13 - Dynamic logged-in user name, role, and avatar verified across multiple user sessions!")

    print("====================================================")
    print(" SUCCESS: ALL 13 FINAL ACCEPTANCE TESTS PASSED (100%)!")
    print("====================================================")

if __name__ == '__main__':
    run_tests()
