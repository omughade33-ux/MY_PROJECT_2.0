from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
import hashlib
import re
from datetime import datetime
from functools     import wraps
import os
import psycopg2
from psycopg2.extras import RealDictCursor


app = Flask(__name__)

# Secret key from environment (better security)
app.secret_key = os.environ.get("SECRET_KEY", "cargoconnect_secret_key_2026")
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

# CORS - allow all origins for production (you can restrict later)
CORS(app, supports_credentials=True, origins=['http://localhost:5000', 'http://127.0.0.1:5000', '*'])

# =====================================================
# PostgreSQL Database Configuration (Supabase)
# =====================================================
# You can also set DATABASE_URL to a full connection stri
DATABASE_URL = os.environ.get("DATABASE_URL")
print(DATABASE_URL)

def get_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        print("Database connected successfully!")
        return conn
    except Exception as err:
        print(f"Database error: {err}")
        return None



def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Login required'}), 401
        return f(*args, **kwargs)
    return decorated

# =====================================================
# Static Routes
# =====================================================
@app.route('/')
def index():
    # Serving index.html (not demo.html)
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

# =====================================================
# Auth Routes
# =====================================================
@app.route('/api/register', methods=['POST'])
def register():
    try:
        print("STEP 1")
        data = request.get_json(silent=True)
        if not data:
            data = request.form.to_dict() if request.form else {}
        print("Register request:", data)

        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        phone = data.get('phone', '').strip()
        role = data.get('role', '')
        gst = data.get('gst', '').strip() if data.get('gst') else None

        if not all([name, email, password, phone, role]):
            return jsonify({'error': 'All fields are required'}), 400

        if role not in ['company', 'transporter']:
            return jsonify({'error': 'Invalid role'}), 400

        conn = get_db()
        print("STEP 2")
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("STEP 3")
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Email already registered'}), 409

        hashed = hash_password(password)
        created_at = int(datetime.now().timestamp())

        gst_value = gst if (role == 'company' and gst) else None
        cursor.execute("""
            INSERT INTO users (name, email, password, role, phone, gst_number, is_verified, created_at) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (name, email, hashed, role, phone, gst_value, 1, created_at))
        
        result = cursor.fetchone()
        user_id = result['id']
        conn.commit()
        print("STEP 4")
        conn.close()

        session['user_id'] = user_id
        session['role'] = role
        session['name'] = name

        return jsonify({'success': True, 'user': {'id': user_id, 'name': name, 'role': role}}), 201
    except Exception as e:
         return jsonify({
        "error": repr(e)
        }), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400

        conn = get_db()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE email = %s AND password = %s",
                       (email, hash_password(password)))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401

        session['user_id'] = user['id']
        session['role'] = user['role']
        session['name'] = user['name']

        return jsonify({'success': True, 'user': {
            'id': user['id'], 'name': user['name'], 'role': user['role'],
            'email': user['email'], 'phone': user['phone'], 'gst': user['gst_number']
        }})
    
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("Login error:", str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me', methods=['GET'])
@login_required
def me():
    conn = get_db()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, name, email, role, phone, gst_number FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    conn.close()
    return jsonify({'success': True, 'user': user})

# =====================================================
# Loads Routes
# =====================================================
@app.route('/api/loads', methods=['GET'])
def get_loads():
    conn = get_db()
    if not conn:
        return jsonify([]), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT l.*, u.name as company_name, u.gst_number,
        (SELECT COUNT(*) FROM bids WHERE load_id = l.id) as bids_count
        FROM loads l 
        JOIN users u ON l.company_id = u.id
        ORDER BY l.created_at DESC
    """)
    loads = cursor.fetchall()
    conn.close()

    for load in loads:
        if load.get('price'):
            load['price'] = str(load['price'])

    return jsonify(loads)

@app.route('/api/loads', methods=['POST'])
@login_required
def post_load():
    if session['role'] != 'company':
        return jsonify({'error': 'Only companies can post loads'}), 403

    data = request.get_json()
    required = ['goods_name', 'weight', 'pickup_location', 'delivery_location', 'truck_type', 'pickup_date']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    conn = get_db()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        INSERT INTO loads 
        (company_id, goods_name, weight, pickup_location, delivery_location, 
         truck_type, pickup_date, price, status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (session['user_id'], data['goods_name'], data['weight'],
          data['pickup_location'], data['delivery_location'], data['truck_type'],
          data['pickup_date'], data.get('price'), 'open', created_at))
    load_id = cursor.fetchone()['id']
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'load_id': load_id}), 201

@app.route('/api/loads/<int:load_id>', methods=['GET'])
def get_load(load_id):
    conn = get_db()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT l.*, u.name as company_name, u.phone as company_phone, u.gst_number
        FROM loads l 
        JOIN users u ON l.company_id = u.id
        WHERE l.id = %s
    """, (load_id,))
    load = cursor.fetchone()
    conn.close()

    if not load:
        return jsonify({'error': 'Load not found'}), 404

    if load.get('price'):
        load['price'] = str(load['price'])

    return jsonify(load)

# =====================================================
# Bids Routes
# =====================================================
@app.route('/api/loads/<int:load_id>/bids', methods=['POST'])
@login_required
def place_bid(load_id):
    if session['role'] != 'transporter':
        return jsonify({'error': 'Only transporters can place bids'}), 403

    data = request.get_json()
    bid_amount = data.get('bid_amount')
    if not bid_amount or float(bid_amount) <= 0:
        return jsonify({'error': 'Valid bid amount is required'}), 400

    conn = get_db()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT id FROM bids WHERE load_id = %s AND transporter_id = %s",
                   (load_id, session['user_id']))
    if cursor.fetchone():
        conn.close()
        return jsonify({'error': 'You have already bid on this load'}), 409

    cursor.execute("SELECT status FROM loads WHERE id = %s", (load_id,))
    load = cursor.fetchone()
    if not load or load['status'] != 'open':
        conn.close()
        return jsonify({'error': 'Load is not available for bidding'}), 400

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("""
        INSERT INTO bids (load_id, transporter_id, bid_amount, status, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (load_id, session['user_id'], float(bid_amount), 'pending', created_at))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Bid placed successfully!'}), 201

@app.route('/api/loads/<int:load_id>/bids', methods=['GET'])
def get_bids_for_load(load_id):
    conn = get_db()
    if not conn:
        return jsonify([]), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT b.*, u.name as transporter_name, u.phone as transporter_phone
        FROM bids b 
        JOIN users u ON b.transporter_id = u.id
        WHERE b.load_id = %s
        ORDER BY b.bid_amount ASC
    """, (load_id,))
    bids = cursor.fetchall()
    conn.close()

    for bid in bids:
        if bid.get('bid_amount'):
            bid['bid_amount'] = str(bid['bid_amount'])

    return jsonify(bids)

@app.route('/api/bids/<int:bid_id>/accept', methods=['PUT'])
@login_required
def accept_bid(bid_id):
    conn = get_db()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT b.*, l.company_id, l.id as load_id
        FROM bids b 
        JOIN loads l ON b.load_id = l.id
        WHERE b.id = %s
    """, (bid_id,))
    bid = cursor.fetchone()

    if not bid or bid['company_id'] != session['user_id']:
        conn.close()
        return jsonify({'error': 'Unauthorized'}), 403

    cursor.execute("UPDATE bids SET status = 'accepted' WHERE id = %s", (bid_id,))
    cursor.execute("UPDATE loads SET status = 'booked' WHERE id = %s", (bid['load_id'],))
    cursor.execute("UPDATE bids SET status = 'rejected' WHERE load_id = %s AND id != %s",
                   (bid['load_id'], bid_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'message': 'Bid accepted!'})

# =====================================================
# Dashboard Route
# =====================================================
@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard():
    conn = get_db()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    user_id = session['user_id']
    role = session['role']

    if role == 'company':
        cursor.execute("""
            SELECT l.*, COUNT(b.id) as bids_count
            FROM loads l
            LEFT JOIN bids b ON l.id = b.load_id
            WHERE l.company_id = %s
            GROUP BY l.id
            ORDER BY l.created_at DESC
        """, (user_id,))
        loads = cursor.fetchall()
        conn.close()

        for load in loads:
            if load.get('price'):
                load['price'] = str(load['price'])

        return jsonify({'role': 'company', 'loads': loads})
    else:
        cursor.execute("""
            SELECT b.*, l.goods_name, l.pickup_location, l.delivery_location, l.weight
            FROM bids b
            JOIN loads l ON b.load_id = l.id
            WHERE b.transporter_id = %s
            ORDER BY b.created_at DESC
        """, (user_id,))
        bids = cursor.fetchall()
        conn.close()

        for bid in bids:
            if bid.get('bid_amount'):
                bid['bid_amount'] = str(bid['bid_amount'])

        return jsonify({'role': 'transporter', 'bids': bids})

# =====================================================
# GST Verification Route
# =====================================================
@app.route('/api/verify-gst', methods=['POST'])
def verify_gst():
    data = request.get_json()
    gst_number = data.get('gst_number', '').strip().upper()

    pattern = r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$'
    if not re.match(pattern, gst_number):
        return jsonify({'valid': False, 'message': 'Invalid GST number format'}), 400

    conn = get_db()
    if not conn:
        return jsonify({'valid': False, 'message': 'Database error'}), 500
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT name, role FROM users WHERE gst_number = %s", (gst_number,))
    user = cursor.fetchone()
    conn.close()

    if user:
        return jsonify({
            'valid': True,
            'registered': True,
            'details': {'name': user['name'], 'role': user['role']}
        })
    else:
        return jsonify({
            'valid': True,
            'registered': False,
            'message': 'GST format is valid but not registered'
        })

# =====================================================
# Main
# =====================================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("=" * 50)
    print("  CargoConnect Backend Server (PostgreSQL)")
    print(f"  Running at: http://0.0.0.0:{port}")
    print("  API Base: /api")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port)