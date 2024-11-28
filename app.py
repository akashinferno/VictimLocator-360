from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
import base64
from collections import Counter
import cv2
import time

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Enable CORS and SocketIO
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Database configuration
DB_NAME = 'car_control.db'

# Global variables
active_controller = None
viewers = set()
global_username = None
esp32_pi, esp32_ci, esp32_mi = 0, 0, 0  # ESP32 control variables

# ESP32 states
esp32_controller = ['neutral', 'accelerate', 'brake', 'left', 'right', 'diagonal']
esp32_power = ['off', 'on']
esp32_mode = ['drive', 'reverse']

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
        conn.commit()

# Initialize the database
init_db()

# MJPEG camera feed URL
camera_url = "http://172.16.66.107:8080"

def generate_video_stream():
    cap = cv2.VideoCapture(camera_url)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        _, jpeg = cv2.imencode('.jpg', frame)
        frame = jpeg.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

# Default route
@app.route('/')
def index():
    if 'username' not in session:
        # Redirect to login if the user is not logged in
        return redirect(url_for('login'))
    # Otherwise, render the index page
    return render_template('index.html', controller=active_controller, username=session['username'], car_state=esp32_power[esp32_pi])

@app.route('/esp32', methods=['GET'])
def esp32():
    return {
        "power": esp32_power[esp32_pi],
        "mode": esp32_mode[esp32_mi],
        "controller": esp32_controller[esp32_ci]
    }, 200

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
                conn.commit()
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash("Username already exists!", "error")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    global active_controller, viewers, global_username
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
    return render_template('login.html')

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
        car_data=zip( timestamps,states,usernames),
        freq_img_data=freq_img_data,
        time_img_data=time_img_data
    )

@app.route('/view_requests')
def view_requests():
    if 'username' not in session:
        return redirect(url_for('login'))
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, requester, status, timestamp FROM control_requests ORDER BY timestamp DESC')
        requests = cursor.fetchall()
    return render_template('requests.html', requests=requests)

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

@socketio.on('connect')
def handle_connect():
    emit('server_message', {'message': 'Connected to WebSocket server'})

@socketio.on('control_power')
def handle_control_power(data):
    global esp32_pi, global_username,esp32_power
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
    global esp32_ci, global_username,esp32_controller
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

@socketio.on('control_mode')
def handle_control_mode(data):
    global esp32_mi, global_username,esp32_mode
    mode = data.get('gear')
    esp32_mi = 0 if mode == 'D' else 1
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                'INSERT INTO car_state (state, timestamp, user_id) VALUES (?, ?, ?)',
                (esp32_mode[esp32_mi], timestamp, global_username)
            )
            conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    emit('mode_status', {'mode': mode})

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
