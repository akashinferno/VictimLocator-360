from flask import Flask, render_template, request, redirect, url_for, session,flash
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
import base64
from collections import Counter
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
active_controller = None  # Store the username of the active controller
viewers = set()  # Store usernames of viewers
global_username=None



#controls going to esp32:
esp32_controller=['neutral','forward','reverse','left','right','diagonal']
esp32_ci=0

esp32_power=['off','on']
esp32_pi=0

esp32_mode=['4-wheel','2-wheel']
esp32_mi=0


# Initialize the database
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE NOT NULL,
                            password TEXT NOT NULL
                          )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS car_state (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            state TEXT NOT NULL,
                            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                            user_id INTEGER NOT NULL,
                            FOREIGN KEY (user_id) REFERENCES users (id)
                          )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS control_requests (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            requester TEXT NOT NULL,
                            status TEXT DEFAULT 'Pending',
                            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                          )''')
        conn.commit()


init_db()


@app.route('/')
def index():
    global esp32_power,esp32_pi
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', controller=active_controller, username=session['username'],car_state=esp32_power[esp32_pi])


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
                return "Username already exists!"
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    global active_controller, viewers,global_username
    error=None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
            user = cursor.fetchone()
            if user:
                session['username'] = username
                session['user_id'] = user[0]  # Store user_id in session
                global_username = username
                if not active_controller:
                    active_controller = username
                else:
                    viewers.add(username)
                
                return redirect(url_for('index'))
            
            else:
                flash('Invalid username or password', 'error')
                error='Invalid username or password'
            
                
    return render_template('login.html',error=error)


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


@app.route('/visualize')
def visualize():
    if 'username' not in session:
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT car_state.state, car_state.timestamp, car_state.user_id
            FROM car_state
            ORDER BY car_state.timestamp DESC
            
        ''')
        car_data = cursor.fetchall()

    # Extract states, timestamps, and map user_ids to usernames
    states = [row[0] for row in car_data]      # car_state.state
    timestamps = [row[1] for row in car_data]  # car_state.timestamp
    usernames = [row[2] for row in car_data]   # users.username




    #Generate Frequency Graph
    freq_img_data = generate_bar_chart(states, "Car States Frequency", "States", "Frequency")

    # Generate State Changes Graph
    time_img_data = generate_line_chart(timestamps, states, "State Changes Over Time", "Timestamps", "States")
    
    return render_template(
        'visualize.html',
        car_data=zip(timestamps,states, usernames),
        freq_img_data=freq_img_data,
        time_img_data=time_img_data )
    


def generate_bar_chart(data, title, xlabel, ylabel):
    state_counts = Counter(data)
    plt.figure(figsize=(8, 4))
    plt.bar(state_counts.keys(), state_counts.values(), color='skyblue')
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(axis='y')

    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    img_data = base64.b64encode(img.getvalue()).decode('utf8')
    plt.close()
    return img_data


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
    img_data = base64.b64encode(img.getvalue()).decode('utf8')
    plt.close()
    return img_data

#----------------------------------
@app.route('/esp32', methods=['GET'])
def esp32():
    global esp32_ci,esp32_mi,esp32_pi,esp32_controller,esp32_mode
    return {"power": esp32_power[esp32_pi],"mode":esp32_mode[esp32_mi],"controller": esp32_controller[esp32_ci] }, 200

    

'''
@socketio.on('control_action')
def handle_control_action(data):
    action = data.get('action')
    ist_timestamp = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    user_id = session.get('user_id', 0)

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO car_state (state, timestamp, user_id) VALUES (?, ?, ?)', (action, ist_timestamp, user_id))
        conn.commit()

    socketio.emit('new_control_action', {'action': action, 'timestamp': ist_timestamp}, broadcast=True)

    '''

#----------------------------------------------------------------
esp32_url="http://127.0.0.1:5000/esp32"
# WebSocket Handlers
@socketio.on('connect')
def handle_connect():
    print("Client connected")
    emit('server_message', {'message': 'Welcome to the WebSocket server!'})

#--------------------------------------------------------------
@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")
#----------------------------------------------------------------
# Handle power control (on/off)
@socketio.on('control_power')
def handle_control_power(data):
    global  esp32_pi,global_username,esp32_power
    power_state = data.get('state')
    print(f"Power turned {power_state}")
    emit('power_status', {'state': power_state})
    if power_state=='on':
        esp32_pi=1
    if power_state=='off':
        esp32_pi=0
    # Update global variable based on power state


    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            power_state= esp32_power[esp32_pi]

            user_id = global_username
            
            # Get the current timestamp
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')  # Format timestamp as 'YYYY-MM-DD HH:MM:SS'

            # Insert the power state, timestamp, and user_id into the car_state table
            cursor.execute('''
                INSERT INTO car_state (state, timestamp, user_id)
                VALUES (?, ?, ?)
            ''', (power_state, timestamp, user_id))

            # Commit the transaction
            conn.commit()

            print(f"Inserted car state '{power_state}' with timestamp '{timestamp}' for user {user_id} into database.")
    except sqlite3.Error as e:
        print(f"Error inserting into database: {e}")

        

# ----------------------------------------------

@socketio.on('control_direction')
def handle_control_direction(data):
    global  esp32_ci,esp32_controller,global_username
    direction = data.get('direction')
    print(f"Moving: {direction}")
    emit('direction_status', {'direction': direction})
    if direction=='left':
        esp32_ci=3
    elif direction=='right':
        esp32_ci=4
    elif direction=='forward':
        esp32_ci=1
    elif direction=='backward':
        esp32_ci=2
    elif direction=='diagonal':
        esp32_ci=5
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            control_state= esp32_controller[esp32_ci]

            user_id = global_username
            
            # Get the current timestamp
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')  # Format timestamp as 'YYYY-MM-DD HH:MM:SS'

            # Insert the power state, timestamp, and user_id into the car_state table
            cursor.execute('''
                INSERT INTO car_state (state, timestamp, user_id)
                VALUES (?, ?, ?)
            ''', (control_state, timestamp, user_id))

            # Commit the transaction
            conn.commit()

            print(f"Inserted car state -'{control_state}' with timestamp '{timestamp}' for user {user_id} into database.")
    except sqlite3.Error as e:
        print(f"Error inserting into database: {e}")
    





#--------------------------------------------------
# Handle mode control (two-wheel, four-wheel)
@socketio.on('control_mode')
def handle_control_mode(data):
    global esp32_mi,esp32_mode,global_username
    mode = data.get('mode')
    print(f"Mode selected: {mode}")
    emit('mode_status', {'mode': mode})
    if mode=='4wheel':
        esp32_mi=0
    if mode=='2wheel':
        esp32_mi=1
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            mode_state= esp32_mode[esp32_mi]

            user_id = global_username
            
            # Get the current timestamp
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')  # Format timestamp as 'YYYY-MM-DD HH:MM:SS'

            # Insert the power state, timestamp, and user_id into the car_state table
            cursor.execute('''
                INSERT INTO car_state (state, timestamp, user_id)
                VALUES (?, ?, ?)
            ''', (mode_state, timestamp, user_id))

            # Commit the transaction
            conn.commit()

            print(f"Inserted car state -'{mode_state}' with timestamp '{timestamp}' for user {user_id} into database.")
    except sqlite3.Error as e:
        print(f"Error inserting into database: {e}")


if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)