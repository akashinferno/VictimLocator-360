from flask import Flask, render_template, request, redirect, url_for, session, flash, Response,jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import sqlite3
import time
from collections import Counter
import matplotlib.pyplot as plt
import io
import base64
from datetime import datetime
import pytz
import cv2
#from yolov5 import YOLOv5
#from yolov5.models.common import DetectMultiBackend
import torch
import numpy as np
import os
import random

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your_secret_key'
#cap = cv2.VideoCapture('http://192.168.29.99:8080/video')

RTSP_URL = "rtsp://192.168.0.224:8080/h264_ulaw.sdp" 
#RTSP_URL = "rtsp://192.168.0.10:554/avstream/channel=1/stream=1.sdp" 

# Load YOLOv5 model
model = torch.hub.load('ultralytics/yolov5', 'yolov5n', pretrained=True)

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
esp32_controller = ['neutral','accelerate', 'brake', 'left', 'right', 'diagonal']  
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

# Load YOLO model
weights_path ="yolov3.weights"  # Update with actual path
config_path = "yolov3.cfg"  # Update with actual path
classes_path ="coco.names"

# yolo_net = cv2.dnn.readNet(weights_path, config_path)
# yolo_classes = open(classes_path).read().strip().split("\n")
# yolo_output_layers = yolo_net.getUnconnectedOutLayersNames()


def simulate_temperature(intensity):
    """Simulate temperature based on intensity."""
    temperature = (intensity / 255.0) * 40  # Simulate temperature in range 0-40°C
    return round(temperature, 2)


def generate_frames_with_thermal():
    global RTSP_URL, thermal_filter_enabled,model
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise Exception(f"Unable to open RTSP stream: {RTSP_URL}")
    frame_counter = 0

    while True:
        success, frame = cap.read()
        if not success:
            break
        # Increment frame counter
        frame_counter += 1
        # Skip frame if not divisible by 3
        if frame_counter % 3 != 0:
            continue

        # Resize frame to reduce resolution for better streaming performance
        frame = cv2.resize(frame, (640, 480))


        # Perform object detection using YOLOv5
        results = model(frame)
        detections = results.xyxy[0]  # Get detections in [x1, y1, x2, y2, confidence, class] format

        for det in detections:
            x1, y1, x2, y2, conf, cls = map(int, det[:6])
            label = results.names[cls]  # Get class name
            confidence = f"{conf:.2f}"
            
            # Draw bounding box and label on the frame
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Green box
            cv2.putText(frame, f"{label} {confidence}", (x1, y1 - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # Apply thermal filter if enabled
        if thermal_filter_enabled:
            # Convert frame to grayscale
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Apply thermal filter (COLORMAP_JET)
            thermal_frame = cv2.applyColorMap(gray_frame, cv2.COLORMAP_JET)
            frame = thermal_frame


        # Encode frame as JPEG
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()



'''
def detect_humans_yolo(frame, net, output_layers, confidence_threshold=0.5):
    """Detect humans using YOLO."""
    height, width = frame.shape[:2]
    blob = cv2.dnn.blobFromImage(frame, 0.00392, (416, 416), (0, 0, 0), True, crop=False)
    net.setInput(blob)
    outputs = net.forward(output_layers)

    detections = []

    for output in outputs:
        for detection in output:
            scores = detection[5:]  # Class probabilities
            class_id = np.argmax(scores)
            confidence = scores[class_id]
            # Ensure detection is a "person" and meets confidence threshold
            if confidence > confidence_threshold and class_id == 0:  # Class ID 0 corresponds to "person"
                if len(detection) >= 4 and not np.any(np.isnan(detection[:4])):
                    # Convert normalized coordinates to pixel values
                    center_x, center_y, w, h = (detection[:4] * np.array([width, height, width, height])).astype('int')
                    x = int(center_x - w / 2)
                    y = int(center_y - h / 2)
                    detections.append(((x, y, w, h), confidence))
                else:
                    print(f"Invalid detection data: {detection}")

    return detections
    '''



'''

def generate_frames_with_human_detection(ip_camera_url, yolo_net, output_layers):
    """Stream frames with human detection and optional thermal filter."""
    global thermal_filter_enabled
    cap = cv2.VideoCapture(ip_camera_url)
    if not cap.isOpened():
        raise ValueError("Unable to open camera feed.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame.")
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            if thermal_filter_enabled:
                # Apply thermal filter
                thermal_frame = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
                processing_frame = thermal_frame
            else:
                processing_frame = frame

            # Detect humans using YOLO
            detections = detect_humans_yolo(frame, yolo_net, output_layers)

            hottest_temperature = 0
            hottest_bbox = None

            for box, confidence in detections:
                x, y, w, h = box
                x = max(0, int(x))
                y = max(0, int(y))
                w = int(w)
                h = int(h)

                # Ensure coordinates are within frame boundaries
                if x + w > frame.shape[1] or y + h > frame.shape[0]:
                    print(f"Skipping box out of bounds: {box}")
                    continue

                # Calculate temperature for thermal filter
                if thermal_filter_enabled:
                    region = gray[y:y + h, x:x + w]
                    avg_intensity = np.mean(region)
                    temperature = simulate_temperature(avg_intensity)

                    # Track the hottest region
                    if temperature > hottest_temperature:
                        hottest_temperature = temperature
                        hottest_bbox = (x, y, w, h)

                    # Display temperature on thermal frame
                    text_y = max(0, y - 10)  # Ensure y - 10 is not negative
                    cv2.putText(
                        processing_frame, f"{temperature:.1f} °C",
                        (x, text_y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 0), 1
                    )

                # Draw bounding box for all detections
                cv2.rectangle(processing_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # Highlight the hottest region if using the thermal filter
            if thermal_filter_enabled and hottest_bbox:
                x, y, w, h = hottest_bbox
                label = "Human" if hottest_temperature > 37 else "Non-Human"
                color = (0, 0, 255) if label == "Human" else (255, 255, 0)
                text_y = max(0, y - 20)  # Ensure y - 20 is not negative
                cv2.putText(
                    processing_frame, f"{hottest_temperature:.1f} °C - {label}",
                    (x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
                )
                cv2.rectangle(processing_frame, (x, y), (x + w, y + h), color, 3)

            # Encode the frame as JPEG
            ret, jpeg = cv2.imencode('.jpg', processing_frame)
            if not ret:
                break

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
    finally:
        cap.release()

'''






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

@app.route('/mapping')
def mapping():
    return render_template('mapping.html')

'''
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames_with_human_detection(), mimetype='multipart/x-mixed-replace; boundary=frame')
'''

# Main route for the app
@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', controller=active_controller, username=session['username'], car_state=esp32_power[esp32_pi])
    return render_template('index.html')  # You need to create an 'index.html' for this route
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
    

'''
@app.route('/toggle_thermal', methods=['POST'])
def toggle_thermal():
    global thermal_filter_enabled
    thermal_filter_enabled = not thermal_filter_enabled
    return jsonify({"thermal_filter_enabled": thermal_filter_enabled})
'''


@app.route('/video_feed')
def video_feed():
    # Serve MJPEG stream
    return Response(generate_frames_with_thermal(), mimetype='multipart/x-mixed-replace; boundary=frame')

'''
@app.route('/live_feed')
def live_feed():
    ip_camera_url = "http://192.168.29.99:8080/video"  # Set your camera URL here
    
    global thermal_filter_enabled  
    thermal_filter_enabled = request.args.get('thermal', 'false') == 'true'

    return Response(
        generate_frames_with_human_detection(ip_camera_url, yolo_net, yolo_output_layers),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

    '''

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


@app.route('/view_requests', methods=['GET', 'POST'])
def view_requests():
    global global_username
    if request.method == 'POST':
        # Assuming `current_user` is used to access the logged-in user's role (e.g., Flask-Login or similar)
        if global_username != active_controller:  # Check if the current user is not a controller
            flash('Only the current controller can manage requests.', 'error')
            return render_template('view_requests.html')  # Stay on the same page and show flash message

    # Retrieve requests from the database and format them for display
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, requester, status, timestamp FROM control_requests ORDER BY timestamp DESC')
        requests = cursor.fetchall()
        
        # Format the timestamps to IST (if necessary)
        formatted_requests = [
            (req[0], req[1], req[2], format_timestamp(req[3])) for req in requests
        ]

    # Pass the requests to the template
    return render_template('view_requests.html', requests=formatted_requests)

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

    # Check if the user is the current controller
    if username != active_controller:
        flash('Only the current controller can manage requests.', 'error')
        return redirect(url_for('view_requests'))  # Stay on the same page

    # Existing logic to accept or reject the request
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT requester FROM control_requests WHERE id = ? AND status = "Pending"', (request_id,))
        request = cursor.fetchone()
        if not request:
            flash("Request not found or already processed.", 'error')
            return redirect(url_for('view_requests'))
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
    
# Variable to store the current camera mode
camera_mode = "rover"

@app.route('/cam_mode', methods=['GET'])
def get_camera_mode():
    global camera_mode
    """API endpoint to return the current camera mode."""
    return jsonify({'camera_mode': camera_mode})
    

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
          +9  )
            conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    emit('Mode_status', {'Mode': mode})

@socketio.on('camera_mode')
def handle_camera_mode(data):
    """Handler for WebSocket 'camera_mode' events."""
    global camera_mode
    camera_mode = data.get('cameraMode')  # Update camera mode
    print(f"Received camera mode: {camera_mode}")

thermal_filter_enabled = False  
@socketio.on('thermal')
def handle_thermal_event(value):
    global thermal_filter_enabled

    # Directly assign the received value
    thermal_filter_enabled = value
    print(f"Thermal Filter State Updated: {'On' if thermal_filter_enabled else 'Off'}")

#------------------------------------CHECK---------------------------------------------

# Define the directories for the radargram images
folder_1 ="static/ml_folder/yes"
folder_0 = "static/ml_folder/no"


@app.route("/check")
def check():
    return render_template("check.html")

@socketio.on('check')
def handle_check(data):
    print(f"Received check event with data: {data}")
    if data == 1:
        image_folder = "static/ml_folder/yes"
    else:
        image_folder = "static/ml_folder/no"

    if os.path.exists(image_folder):
        image_files = [f for f in os.listdir(image_folder) if os.path.isfile(os.path.join(image_folder, f))]
        if image_files:
            selected_image = random.choice(image_files)
            image_url = f"/static/ml_folder/{os.path.basename(image_folder)}/{selected_image}".replace("\\", "/")
            print(f"Emitting image URL: {image_url}")
            socketio.emit('display_image', {'image_url': image_url})
        else:
            print("No images found in folder")
            socketio.emit('display_image', {'error': 'No images found in folder'})
    else:
        print("Folder not found")
        socketio.emit('display_image', {'error': 'Folder not found'})







# -----------------------------------------------------------------------------------------



if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)

    

