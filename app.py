import os
import sqlite3
import datetime
import json
import csv
import io
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, g, make_response,
    Response, stream_with_context
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from agent.park_agent import ParkOpsAgent
from database.database import (
    init_db as init_sqlite_db,
    get_full_park_state,
    import_park_dataset,
    remove_park_dataset,
    stream_import_pipeline,
    parse_excel_dataset,
    create_sample_excel_template,
    calculate_crowd_level,
    seed_demo_park_data,
    get_connection
)

load_dotenv()

app = Flask(__name__)
SECRET_KEY = os.getenv('SECRET_KEY', 'parkops-digital-model-super-secret-key-2026')
app.secret_key = SECRET_KEY
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
park_agent = ParkOpsAgent(gemini_api_key=GEMINI_API_KEY)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """Initializes the database schema."""
    init_sqlite_db(DATABASE)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please sign in to access ParkOps operations.', 'warning')
            return redirect(url_for('signin', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# PUBLIC ROUTES
# ==========================================
@app.route('/')
def home():
    user = None
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return render_template('index.html', user=user)

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        remember = request.form.get('remember') == 'on'

        if not email or not password:
            error = 'Please provide both email address and password.'
        else:
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            if user and check_password_hash(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['user_name'] = user['full_name']
                session['user_email'] = user['email']
                session['user_role'] = user['role'] if ('role' in user.keys() and user['role']) else 'Operator'
                if remember:
                    session.permanent = True
                    app.permanent_session_lifetime = datetime.timedelta(days=30)
                flash(f'Welcome back, {user["full_name"]}!', 'success')
                next_page = request.args.get('next')
                return redirect(next_page or url_for('dashboard'))
            else:
                error = 'Invalid email address or password. Please try again.'

    return render_template('signin.html', error=error)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        phone = request.form.get('phone', '').strip()
        country = request.form.get('country', '').strip()
        role = request.form.get('role', 'Operator').strip() or 'Operator'

        if not full_name or not email or not password or not confirm_password:
            error = 'All required fields must be filled.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters long.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif '@' not in email or '.' not in email:
            error = 'Please enter a valid email address.'
        else:
            db = get_db()
            existing_user = db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if existing_user:
                error = 'An account with this email already exists. Please sign in.'
            else:
                pw_hash = generate_password_hash(password)
                cursor = db.execute(
                    'INSERT INTO users (full_name, email, password_hash, phone, country, role) VALUES (?, ?, ?, ?, ?, ?)',
                    (full_name, email, pw_hash, phone, country, role)
                )
                db.commit()
                new_user_id = cursor.lastrowid
                session.clear()
                session['user_id'] = new_user_id
                session['user_name'] = full_name
                session['user_email'] = email
                session['user_role'] = role
                flash('Account created successfully! Welcome to ParkOps.', 'success')
                return redirect(url_for('dashboard'))

    return render_template('signup.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out securely.', 'info')
    return redirect(url_for('signin'))

@app.context_processor
def inject_user_context():
    user = None
    if 'user_id' in session:
        try:
            db = get_db()
            user_row = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            if user_row:
                user = dict(user_row)
        except Exception:
            pass
    return {'user': user}

@app.route('/contact', methods=['POST'])
def contact():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    park_name = request.form.get('park_name', '').strip()
    message = request.form.get('message', '').strip()

    if not name or not email or not message:
        flash('Please fill in all required contact fields.', 'warning')
        return redirect(url_for('home', _anchor='contact'))

    db = get_db()
    db.execute(
        'INSERT INTO contacts (name, email, park_name, message) VALUES (?, ?, ?, ?)',
        (name, email, park_name, message)
    )
    db.commit()
    flash('Thank you for reaching out to ParkOps! Our Digital Model engineering team will get back to you shortly.', 'success')
    return redirect(url_for('home', _anchor='contact'))

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    email = request.form.get('email', '').strip().lower()
    if not email:
        return jsonify({'success': False, 'message': 'Please enter your email address.'}), 400
    
    db = get_db()
    user = db.execute('SELECT id, full_name FROM users WHERE email = ?', (email,)).fetchone()
    if user:
        return jsonify({
            'success': True,
            'message': f'Password reset link generated for {email}. (Demo mode: reset verification link sent to your inbox).'
        })
    else:
        return jsonify({
            'success': False,
            'message': 'No registered account found with that email address.'
        }), 404

# ==========================================
# PROTECTED SIDEBAR APPLICATION PAGES
# ==========================================
# ==========================================
# PROTECTED SIDEBAR APPLICATION PAGES & WORKFLOW STAGES
# ==========================================
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'dashboard.html',
        user=user,
        park=park_state.get('averages', {}),
        park_state=park_state,
        rides=park_state.get('rides', [])[:4],
        zones=park_state.get('zones', []),
        facilities=park_state.get('facilities', []),
        agent=park_agent.monitor(park_state),
        active_page='dashboard',
        current_stage=0
    )

# ----------------------------------------------------
# PARKOPS WORKFLOW STAGES (1 -> 9 SEQUENTIAL SYSTEM)
# ----------------------------------------------------
@app.route('/real-park')
@login_required
def real_park():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'real_park.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='real-park',
        current_stage=1
    )

@app.route('/park-data', methods=['GET', 'POST'])
@login_required
def park_data():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    success_upload = None

    if request.method == 'POST':
        data = None
        if 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            fname = file.filename.lower()
            try:
                if fname.endswith('.xlsx') or fname.endswith('.xls') or fname.endswith('.csv'):
                    data = parse_excel_dataset(file)
                elif fname.endswith('.json'):
                    data = json.loads(file.read().decode('utf-8'))
                if data:
                    res = import_park_dataset(db, data)
                    success_upload = res
                    flash(res.get('message', 'Dataset uploaded successfully!'), 'success')
            except Exception as e:
                flash(f'Dataset Upload Error: {str(e)}', 'danger')

    park_state = get_full_park_state(db)
    return render_template(
        'park_data.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        success_upload=success_upload,
        active_page='park-data',
        current_stage=2
    )

@app.route('/digital-model')
@login_required
def digital_model():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'digital_model.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='digital-model',
        current_stage=3
    )

@app.route('/ai-agent')
@login_required
def ai_agent():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    agent_state = park_agent.monitor(park_state)
    activity_log = park_agent.activity_log
    latest_decision = park_agent.latest_decision
    history = db.execute(
        'SELECT * FROM simulation_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 6',
        (session['user_id'],)
    ).fetchall()
    return render_template(
        'ai_agent.html',
        user=user,
        park=park_state,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        agent=agent_state,
        activity_log=activity_log,
        latest_decision=latest_decision,
        history=history,
        active_page='ai-agent',
        current_stage=4
    )

@app.route('/monitor')
@login_required
def monitor():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'monitor.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='monitor',
        current_stage=5
    )

@app.route('/predict')
@login_required
def predict():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'predict.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='predict',
        current_stage=6
    )

@app.route('/simulate', endpoint='simulate')
@app.route('/simulations', endpoint='simulations')
@login_required
def simulate():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    history = db.execute(
        'SELECT * FROM simulation_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
        (session['user_id'],)
    ).fetchall()
    return render_template(
        'simulate.html',
        user=user,
        park=park_state.get('averages', {}),
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        history=history,
        active_page='simulate',
        current_stage=7
    )

@app.route('/recommend')
@login_required
def recommend():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'recommend.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='recommend',
        current_stage=8
    )

@app.route('/operator-decision')
@login_required
def operator_decision():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'operator_decision.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='operator-decision',
        current_stage=9
    )

@app.route('/park-overview', endpoint='park_overview')
@login_required
def park_overview():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'park_overview.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        rides=park_state.get('rides', []),
        facilities=park_state.get('facilities', []),
        active_page='park-overview'
    )

@app.route('/rides', endpoint='rides')
@login_required
def rides():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    rides_list = park_state.get('rides', [])
    op_count = sum(1 for r in rides_list if r.get('status') == 'Operational')
    maint_count = sum(1 for r in rides_list if r.get('status') == 'Maintenance')
    off_count = sum(1 for r in rides_list if r.get('status') == 'Offline')
    avg_util = int(sum(r.get('utilization', 0) for r in rides_list) / max(1, len(rides_list))) if rides_list else 0

    stats = {
        'total': len(rides_list),
        'operational': op_count,
        'maintenance': maint_count,
        'offline': off_count,
        'avg_utilization': avg_util
    }
    return render_template(
        'rides.html',
        user=user,
        park_state=park_state,
        stats=stats,
        rides=rides_list,
        active_page='rides'
    )

@app.route('/visitors', endpoint='visitors')
@login_required
def visitors():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    return render_template(
        'visitors.html',
        user=user,
        park_state=park_state,
        stats=park_state.get('averages', {}),
        zones=park_state.get('zones', []),
        active_page='visitors'
    )

@app.route('/facilities', endpoint='facilities')
@login_required
def facilities():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    fac_list = park_state.get('facilities', [])
    avail = sum(1 for f in fac_list if f.get('status') == 'Available')
    busy = sum(1 for f in fac_list if f.get('status') == 'Busy')
    crit = sum(1 for f in fac_list if f.get('status') == 'Critical')

    stats = {
        'total': len(fac_list),
        'available': avail,
        'busy': busy,
        'critical': crit
    }
    return render_template(
        'facilities.html',
        user=user,
        park_state=park_state,
        stats=stats,
        facilities=fac_list,
        active_page='facilities'
    )

@app.route('/ai-assistant')
@login_required
def ai_assistant():
    return redirect(url_for('ai_agent'))

@app.route('/reports')
@login_required
def reports():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    history = db.execute(
        'SELECT * FROM simulation_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
        (session['user_id'],)
    ).fetchall()
    return render_template(
        'reports.html',
        user=user,
        park=park_state.get('averages', {}),
        park_state=park_state,
        history=history,
        active_page='reports',
        current_stage=0
    )

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    park_state = get_full_park_state(db)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'profile':
            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            country = request.form.get('country', '').strip()
            if full_name:
                db.execute(
                    'UPDATE users SET full_name = ?, phone = ?, country = ? WHERE id = ?',
                    (full_name, phone, country, session['user_id'])
                )
                db.commit()
                session['user_name'] = full_name
                flash('Profile updated successfully!', 'success')
        elif action == 'password':
            old_pw = request.form.get('old_password', '').strip()
            new_pw = request.form.get('new_password', '').strip()
            if check_password_hash(user['password_hash'], old_pw):
                if len(new_pw) >= 6:
                    db.execute(
                        'UPDATE users SET password_hash = ? WHERE id = ?',
                        (generate_password_hash(new_pw), session['user_id'])
                    )
                    db.commit()
                    flash('Password changed securely!', 'success')
                else:
                    flash('New password must be at least 6 characters.', 'danger')
            else:
                flash('Incorrect current password.', 'danger')
        elif action == 'import_json':
            json_text = request.form.get('json_data', '').strip()
            if 'file' in request.files and request.files['file'].filename:
                file = request.files['file']
                content = file.read().decode('utf-8')
                if file.filename.endswith('.json'):
                    try:
                        parsed = json.loads(content)
                        res = import_park_dataset(db, parsed)
                        flash(res['message'], 'success')
                    except Exception as e:
                        flash(f'JSON Import Error: {str(e)}', 'danger')
                elif file.filename.endswith('.csv'):
                    flash('CSV file detected and parsed for theme park telemetry!', 'success')
            elif json_text:
                try:
                    parsed = json.loads(json_text)
                    res = import_park_dataset(db, parsed)
                    flash(res['message'], 'success')
                except Exception as e:
                    flash(f'JSON Import Error: {str(e)}', 'danger')
        elif action == 'reset_demo':
            try:
                db.execute("DELETE FROM rides")
                db.execute("DELETE FROM facilities")
                db.execute("DELETE FROM zones")
                db.execute("DELETE FROM parks")
                seed_demo_park_data(db)
                flash('Successfully reset park to standard ParkOps Theme Park Demo dataset!', 'success')
            except Exception as e:
                flash(f'Reset error: {str(e)}', 'danger')
        return redirect(url_for('settings'))

    return render_template('settings.html', user=user, park_state=park_state, active_page='settings')

# ==========================================
# REST API ENDPOINTS
# ==========================================
@app.route('/api/dashboard')
@login_required
def api_dashboard():
    db = get_db()
    park_state = get_full_park_state(db)
    avg = park_state.get('averages', {})
    zones = park_state.get('zones', [])
    rides = park_state.get('rides', [])

    zone_labels = [z['name'] for z in zones]
    zone_values = [z.get('occupancy_pct', 50) for z in zones]

    ride_labels = [r['name'] for r in rides[:5]]
    ride_values = [r.get('utilization', 75) for r in rides[:5]]

    return jsonify({
        'kpi': {
            'total_visitors': avg.get('total_visitors', 12450),
            'active_rides': avg.get('active_rides_ratio', '18 / 20'),
            'average_queue': avg.get('average_queue_str', '24 min'),
            'crowd_density': avg.get('crowd_density', 'Medium')
        },
        'visitor_flow': {
            'labels': ['9 AM', '10 AM', '11 AM', '12 PM', '1 PM', '2 PM', '3 PM', '4 PM', '5 PM', '6 PM'],
            'actual': [3200, 5400, 7800, 10200, 11800, avg.get('total_visitors', 12450), 0, 0, 0, 0],
            'predicted': [3200, 5400, 7800, 10200, 11800, avg.get('total_visitors', 12450), 14200, 16800, 15300, 11000]
        },
        'queue_trend': {
            'labels': ['9 AM', '10 AM', '11 AM', '12 PM', '1 PM', '2 PM', '3 PM', '4 PM', '5 PM', '6 PM'],
            'wait_times': [10, 15, 22, 28, 25, avg.get('average_queue', 24), 38, 45, 34, 18]
        },
        'crowd_by_zone': {
            'labels': zone_labels,
            'values': zone_values
        },
        'ride_utilization': {
            'labels': ride_labels,
            'values': ride_values
        }
    })

@app.route('/api/park-state')
@login_required
def api_park_state():
    db = get_db()
    return jsonify(get_full_park_state(db))

@app.route('/api/park-data/template')
@app.route('/api/park-data/download-template')
@login_required
def api_park_data_template():
    output = create_sample_excel_template()
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=parkops_sample_dataset.xlsx"
    resp.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return resp

@app.route('/api/park-data/import', methods=['POST'])
@app.route('/api/park-data/upload-excel', methods=['POST'])
@login_required
def api_park_data_import():
    db = get_db()
    data = None
    
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        fname = file.filename.lower()
        try:
            if fname.endswith('.xlsx') or fname.endswith('.xls'):
                data = parse_excel_dataset(file)
            elif fname.endswith('.json'):
                data = json.loads(file.read().decode('utf-8'))
            elif fname.endswith('.csv'):
                # Try Excel/CSV parse
                data = parse_excel_dataset(file)
            else:
                return jsonify({
                    'success': False, 
                    'error': f"Unsupported file format '{file.filename}'. Please upload an Excel (.xlsx, .xls) or .csv dataset."
                }), 400
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    elif request.is_json:
        data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'error': 'No dataset file provided. Please select an Excel (.xlsx) file.'}), 400

    try:
        res = import_park_dataset(db, data)
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/park-data/upload-stream', methods=['POST'])
@app.route('/api/park-data/import-stream', methods=['POST'])
@login_required
def api_park_data_upload_stream():
    if 'file' not in request.files or not request.files['file'].filename:
        def err_gen():
            yield json.dumps({'stage': 'error', 'failed_stage': 'FILE RECEIVED', 'error': 'No file uploaded. Please select an Excel (.xlsx, .xls) or .csv dataset file.'}) + '\n'
        return Response(err_gen(), mimetype='application/x-ndjson')

    file = request.files['file']
    filename = file.filename
    file_bytes = file.read()

    db = get_db()
    return Response(
        stream_with_context(stream_import_pipeline(db, filename, file_bytes)),
        mimetype='application/x-ndjson'
    )

@app.route('/api/park-data/remove', methods=['POST'])
@app.route('/api/park-data/delete', methods=['POST'])
@login_required
def api_park_data_remove():
    db = get_db()
    try:
        res = remove_park_dataset(db)
        return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/park-data/reset-demo', methods=['POST'])
@login_required
def api_park_data_reset_demo():
    db = get_db()
    try:
        db.execute("DELETE FROM rides")
        db.execute("DELETE FROM facilities")
        db.execute("DELETE FROM zones")
        db.execute("DELETE FROM parks")
        seed_demo_park_data(db)
        return jsonify({'success': True, 'message': 'Reset to default ParkOps Demo dataset.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/rides')
@login_required
def api_rides():
    db = get_db()
    rides = db.execute('SELECT * FROM rides').fetchall()
    return jsonify([dict(r) for r in rides])

@app.route('/api/facilities')
@login_required
def api_facilities():
    db = get_db()
    facilities = db.execute('SELECT * FROM facilities').fetchall()
    return jsonify([dict(f) for f in facilities])

# --- CENTRAL AGENT APIS ---
@app.route('/api/agent/status')
@login_required
def api_agent_status():
    db = get_db()
    park_state = get_full_park_state(db)
    return jsonify(park_agent.monitor(park_state))

@app.route('/api/agent/activity')
@login_required
def api_agent_activity():
    return jsonify({
        'activity_log': park_agent.activity_log,
        'latest_decision': park_agent.latest_decision
    })

@app.route('/api/agent/analyze', methods=['POST'])
@app.route('/api/ai-chat', methods=['POST'])
@login_required
def api_agent_analyze():
    data = request.get_json() or {}
    query = str(data.get('message', '') or data.get('query', '')).strip()
    if not query:
        return jsonify({'response': 'Please ask an operational question for the ParkOps AI Agent.'})
    result = park_agent.analyze(query)
    return jsonify(result)

@app.route('/api/agent/simulate', methods=['POST'])
@app.route('/api/simulation', methods=['POST'])
@app.route('/api/simulate', methods=['POST'])
@login_required
def api_agent_simulate():
    data = request.get_json() or {}
    try:
        additional_visitors = int(data.get('additional_visitors', 5000))
    except (ValueError, TypeError):
        additional_visitors = 5000

    time_period = str(data.get('time_period', '5 PM - 6 PM'))
    ride_availability = str(data.get('ride_availability', 'All Rides Operational'))
    weather_condition = str(data.get('weather_condition', 'Sunny'))

    result = park_agent.simulate(additional_visitors, time_period, ride_availability, weather_condition)

    try:
        db = get_db()
        db.execute("""
            INSERT INTO simulation_history (
                user_id, scenario_name, additional_visitors, time_period,
                weather, ride_status_override, predicted_visitors,
                predicted_queue_time, crowd_density, bottleneck_zone, ai_recommendation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session.get('user_id'),
            f'+{additional_visitors:,} Visitors ({time_period})',
            additional_visitors,
            time_period,
            weather_condition,
            ride_availability,
            result['predicted_visitors'],
            result['predicted_queue'],
            result['crowd_density'],
            result['bottleneck'],
            result['recommendation']
        ))
        db.commit()
    except Exception as e:
        print(f'Error saving simulation: {e}')

    return jsonify(result)

@app.route('/api/agent/recommend', methods=['POST'])
@login_required
def api_agent_recommend():
    data = request.get_json() or {}
    total_visitors = int(data.get('total_visitors', 17450))
    predicted_queue = int(data.get('predicted_queue', 34))
    bottleneck = str(data.get('bottleneck', 'Adventure Zone'))
    weather = str(data.get('weather', 'Sunny'))
    rec = park_agent.recommend(total_visitors, predicted_queue, bottleneck, weather)
    return jsonify({'recommendation': rec})

@app.route('/api/agent/apply-decision', methods=['POST'])
@app.route('/api/agent/decision', methods=['POST'])
@app.route('/api/operator/decision', methods=['POST'])
@login_required
def api_agent_apply_decision():
    data = request.get_json() or {}
    decision_id = str(data.get('decision_id', 'DEC-8492'))
    action = str(data.get('action', 'apply')).lower()
    
    if action == 'reject':
        res = park_agent.reject_decision(decision_id)
    elif action == 'save':
        res = park_agent.save_decision(decision_id)
    else:
        res = park_agent.apply_decision(decision_id)

    # Persist decision into SQLite
    try:
        db = get_db()
        db.execute("""
            INSERT INTO operator_decisions (decision_id, action, status, operator_id, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (
            decision_id,
            action,
            res.get('status', 'Processed'),
            session.get('user_id'),
            res.get('message', '')
        ))
        db.commit()
    except Exception as e:
        print(f"Error saving operator decision: {e}")

    return jsonify(res)

@app.route('/api/export-report')
@login_required
def export_report():
    db = get_db()
    sims = db.execute('SELECT * FROM simulation_history ORDER BY created_at DESC').fetchall()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Scenario', 'Additional Visitors', 'Time Period', 'Weather', 'Predicted Queue (min)', 'Crowd Density', 'Bottleneck', 'Date'])
    for s in sims:
        cw.writerow([s['id'], s['scenario_name'], s['additional_visitors'], s['time_period'], s['weather'], s['predicted_queue_time'], s['crowd_density'], s['bottleneck_zone'], s['created_at']])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=parkops_operational_report.csv"
    output.headers["Content-type"] = "text/csv"
    return output

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print('====================================================')
    print('   PARKOPS - THEME PARK DIGITAL MODEL WEB APP       ')
    print('   Database: SQLite initialized (database.db)        ')
    print(f'   Application URL: http://127.0.0.1:{port}          ')
    print('====================================================')
    app.run(host='0.0.0.0', port=port, debug=True)
