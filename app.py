from flask import Flask, render_template, request, redirect, url_for, session, flash, Response,jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import sqlite3
import time
#import cv2
from collections import Counter
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
import pytz

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Enable CORS and SocketIO
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Database configuration
DB_NAME = 'database.db'

# Global variables
active_controller = None
viewers = set()
global_username = None

# ESP32 states and control variables
esp32_controller = ['neutral','accelerate', 'brake', 'left', 'right', 'diagonal']   # Removed 'neutral'
esp32_power = ['off', 'on']
esp32_mode = ['drive', 'reverse']
esp32_pi, esp32_ci, esp32_mi = 0, 0, 0  # Default ESP32 states

# Initialize the database
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE NOT NULL,
                            password TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS car_state (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            state TEXT NOT NULL,
                            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                            user_id TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS control_requests (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            requester TEXT NOT NULL,
                            status TEXT DEFAULT 'Pending',
                            timestamp TEXT DEFAULT CURRENT_TIMESTAMP)''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp TEXT NOT NULL)''')
        conn.commit()

# Initialize the database at the start of the program
init_db()

def format_timestamp(utc_timestamp):
    utc = pytz.utc
    local_tz = pytz.timezone("Asia/Kolkata")
    utc_dt = utc.localize(datetime.strptime(utc_timestamp, '%Y-%m-%d %H:%M:%S'))
    local_dt = utc_dt.astimezone(local_tz)
    return local_dt.strftime('%Y-%m-%d %H:%M:%S')


def generate_bar_chart(data, title, xlabel, ylabel):
    plt.figure(figsize=(8, 4))
    plt.bar(Counter(data).keys(), Counter(data).values(), color='skyblue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode('utf8')

def generate_line_chart(x_data, y_data, title, xlabel, ylabel):
    plt.figure(figsize=(10, 5))
    plt.plot(x_data, y_data, marker='o', linestyle='-', color='blue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.xticks(rotation=45)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode('utf8')

def get_current_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

@socketio.on('log_action')
def handle_log_action(data):
    action = data.get('action')
    timestamp = get_current_ist_time()  # Use IST for timestamps
    global global_username

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO car_state (state, timestamp, user_id) VALUES (?, ?, ?)',
            (action, timestamp, global_username)
        )
        conn.commit()

    # Emit updated data to all clients
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT state, timestamp, user_id FROM car_state ORDER BY timestamp DESC')
        car_data = cursor.fetchall()

    freq_img_data = generate_bar_chart(
        [row[0] for row in car_data], "Car States Frequency", "States", "Frequency"
    )
    time_img_data = generate_line_chart(
        [row[1] for row in car_data], [row[0] for row in car_data], "State Changes Over Time", "Timestamps", "States"
    )

    emit('update_graphs', {
        'freq_img_data': freq_img_data,
        'time_img_data': time_img_data,
        'car_data': car_data
    }, broadcast=True)

@socketio.on('connect')
def handle_connect():
    emit('server_message', {'message': 'Connected to WebSocket server'})

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')

# Route to handle ESP32 states
@app.route('/esp32', methods=['GET'])
def esp32():
    return {
        "power": esp32_power[esp32_pi],
        "mode": esp32_mode[esp32_mi],
        "controller": esp32_controller[esp32_ci]
    }, 200

# Main route for the app
@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', controller=active_controller, username=session['username'], car_state=esp32_power[esp32_pi])

# Route to handle admin login
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'VL360' and password == 'admin@123':
            session['is_admin'] = True
            return redirect(url_for('manage_database'))
        else:
            flash('Invalid admin credentials!', 'error')
    return render_template('admin_login.html')

# Route to manage database
@app.route('/manage_database', methods=['GET'])
def manage_database():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        cursor.execute("SELECT * FROM car_state")
        car_states = cursor.fetchall()
        cursor.execute("SELECT * FROM control_requests")
        requests = cursor.fetchall()

    return render_template('manage_database.html', users=users, car_states=car_states, requests=requests)

# Backend for managing users
@app.route('/update_user', methods=['POST'])
def update_user():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    user_id = request.form['user_id']
    username = request.form['username']
    password = request.form['password']

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET username = ?, password = ? WHERE id = ?", (username, password, user_id))
        conn.commit()

    flash("User updated successfully!", "success")
    return redirect(url_for('manage_database'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash("User deleted successfully!", "success")
    return redirect(url_for('manage_database'))

@app.route('/insert_user', methods=['POST'])
def insert_user():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    username = request.form['username']
    password = request.form['password']

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            flash("User added successfully!", "success")
        except sqlite3.IntegrityError:
            flash("Username already exists!", "error")

    return redirect(url_for('manage_database'))

# Backend for managing car states
@app.route('/delete_car_state/<int:state_id>', methods=['POST'])
def delete_car_state(state_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM car_state WHERE id = ?", (state_id,))
        conn.commit()
        flash("Car state deleted successfully!", "success")
    return redirect(url_for('manage_database'))

@app.route('/delete_control_request/<int:request_id>', methods=['POST'])
def delete_control_request(request_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM control_requests WHERE id = ?", (request_id,))
        conn.commit()
        flash("Control request deleted successfully!", "success")
    return redirect(url_for('manage_database'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            # Check if the username already exists
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            if user:
                flash('Username already exists!', 'error')  # Flash an error message
                return redirect(url_for('register'))  # Redirect back to the register page
            else:
                # Insert the new user into the database
                cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
                conn.commit()
                flash('Registration successful!', 'success')  # Flash a success message
                return redirect(url_for('register'))  # Redirect back to the register page
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    global active_controller, viewers, global_username
    error = None  # Initialize error here

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
            user = cursor.fetchone()
            if user:
                session['username'] = username
                session['user_id'] = user[0]
                global_username = username
                if not active_controller:
                    active_controller = username
                else:
                    viewers.add(username)
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password', 'error')
                error = 'Invalid username or password'  # Assign error message here

    return render_template('login.html', error=error)  # Pass error variable to the template

@app.route('/logout')
def logout():
    global active_controller, viewers
    username = session.get('username')
    if username:
        if username == active_controller:
            active_controller = None
        viewers.discard(username)
    session.clear()
    return redirect(url_for('login'))


@app.route('/start_session')
def start_session():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('start_session.html')
    
@app.route('/index')
def dashboard():
    return render_template('index.html')
    

@app.route('/visualize')
def visualize():
    if 'username' not in session:
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT state, timestamp, user_id FROM car_state ORDER BY timestamp DESC')
        car_data = cursor.fetchall()

    states = [row[0] for row in car_data]
    timestamps = [row[1] for row in car_data]
    usernames = [row[2] for row in car_data]

    freq_img_data = generate_bar_chart(states, "Car States Frequency", "States", "Frequency")
    time_img_data = generate_line_chart(timestamps, states, "State Changes Over Time", "Timestamps", "States")

    return render_template(
        'visualize.html',
        car_data=zip(timestamps, states, usernames),
        freq_img_data=freq_img_data,
        time_img_data=time_img_data
    )

def generate_bar_chart(data, title, xlabel, ylabel):
    plt.figure(figsize=(8, 4))
    plt.bar(Counter(data).keys(), Counter(data).values(), color='skyblue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode('utf8')

def generate_line_chart(x_data, y_data, title, xlabel, ylabel):
    plt.figure(figsize=(10, 5))
    plt.plot(x_data, y_data, marker='o', linestyle='-', color='blue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.xticks(rotation=45)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode('utf8')


@app.route('/view_requests')
def view_requests():
    if 'username' not in session:
        return redirect(url_for('login'))
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, requester, status, timestamp FROM control_requests ORDER BY timestamp DESC')
        requests = cursor.fetchall()
        # Format the timestamps to IST
        formatted_requests = [
            (req[0], req[1], req[2], format_timestamp(req[3])) for req in requests
        ]
    return render_template('requests.html', requests=formatted_requests)

# Add route for About page
@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/request_control', methods=['POST'])
def request_control():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    if username == active_controller:
        return "You are already the controller.", 403
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO control_requests (requester) VALUES (?)', (username,))
        conn.commit()
    socketio.emit('control_request', {'requester': username})
    return redirect(url_for('index'))

@app.route('/update_request/<int:request_id>/<string:action>', methods=['POST'])
def update_request(request_id, action):
    global active_controller
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    if username != active_controller:
        return "Only the current controller can manage requests.", 403

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT requester FROM control_requests WHERE id = ? AND status = "Pending"', (request_id,))
        request = cursor.fetchone()
        if not request:
            return "Request not found or already processed.", 404
        requester = request[0]
        if action == 'accept':
            cursor.execute('UPDATE control_requests SET status = "Accepted" WHERE id = ?', (request_id,))
            viewers.add(active_controller)
            active_controller = requester
            viewers.discard(requester)
        elif action == 'reject':
            cursor.execute('UPDATE control_requests SET status = "Rejected" WHERE id = ?', (request_id,))
        conn.commit()
    socketio.emit('request_updated', {'action': action, 'requester': requester})
    return redirect(url_for('view_requests'))

@app.route('/video_feed')
def video_feed():
    return Response(generate_video_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

def generate_bar_chart(data, title, xlabel, ylabel):
    plt.figure(figsize=(8, 4))
    plt.bar(Counter(data).keys(), Counter(data).values(), color='skyblue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode('utf8')

def generate_line_chart(x_data, y_data, title, xlabel, ylabel):
    plt.figure(figsize=(10, 5))
    plt.plot(x_data, y_data, marker='o', linestyle='-', color='blue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.xticks(rotation=45)
    plt.tight_layout()
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    return base64.b64encode(img.getvalue()).decode('utf8')

@app.route("/data", methods=["POST"])
def data():
    # Extract JSON data from the POST request
    try:
        data = request.get_json()  # Try to parse JSON
        # Extract values from the data
        sensor_name = data.get("sensor_name")
        value = data.get("value")
        timestamp = data.get("timestamp")

        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided or invalid JSON format"}), 400
        print(f"Received data: {data}")  # Log the incoming data
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor() 
            #formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")  # Get the current timestamp in IST
            cursor.execute(''' INSERT INTO sensor_data (sensor_name, value, timestamp)
                VALUES (?, ?, ?)''', (sensor_name, value,timestamp)) 
             # Insert sensor data with timestamp

        # Commit the changes and close the connection
        conn.commit()
        conn.close()

        # Emit the sensor data via WebSocket
        socketio.emit("sensor_reading", data)

        return jsonify({"status": "success", "message": "Sensor data inserted successfully"}), 200
    
    except Exception as e:
        # Return an error message if any exception occurs
        return jsonify({"status": "error", "message": str(e)}), 500

#------------------------------socket-================================
@socketio.on('connect')
def handle_connect():
    emit('server_message', {'message': 'Connected to WebSocket server'})

@socketio.on('control_power')
def handle_control_power(data):
    global esp32_pi, global_username
    power_state = data.get('state')
    esp32_pi = 0 if power_state == 'off' else 1
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                'INSERT INTO car_state (state, timestamp, user_id) VALUES (?, ?, ?)',
                (esp32_power[esp32_pi], timestamp, global_username)
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    emit('power_status', {'state': power_state})

@socketio.on('control_direction')
def handle_control_direction(data):
    global esp32_ci, global_username
    direction = data.get('direction')
    esp32_ci = {'accelerate': 1, 'brake': 2, 'left': 3, 'right': 4, 'diagonal': 5}.get(direction, 0)
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                'INSERT INTO car_state (state, timestamp, user_id) VALUES (?, ?, ?)',
                (esp32_controller[esp32_ci], timestamp, global_username)
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    emit('direction_status', {'direction': direction})


if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
