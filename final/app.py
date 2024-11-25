from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt
import io
import base64
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Initialize SocketIO
socketio = SocketIO(app)

DB_NAME = 'car_control.db'

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
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                          )''')
        conn.commit()

init_db()

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

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
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
            user = cursor.fetchone()
            if user:
                session['username'] = username
                return redirect(url_for('index'))
            else:
                return "Invalid username or password!"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/change_state', methods=['POST'])
def change_state():
    if 'username' not in session:
        return redirect(url_for('login'))

    new_state = request.form['state']
    valid_states = ['on', 'off', 'left', 'right', 'front', 'back']
    if new_state not in valid_states:
        return "Invalid state!", 400

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO car_state (state, timestamp) VALUES (?, ?)', (new_state, datetime.now()))
        conn.commit()

    # Emit the new state via WebSocket to update clients in real-time
    socketio.emit('state_change', {'state': new_state, 'timestamp': datetime.now()})

    return redirect(url_for('visualize'))

@app.route('/visualize')
def visualize():
    if 'username' not in session:
        return redirect(url_for('login'))

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT state, timestamp FROM car_state')
        car_data = cursor.fetchall()

    states = [row[0] for row in car_data]
    timestamps = [row[1] for row in car_data]

    state_counts = {'on': 0, 'off': 0, 'left': 0, 'right': 0, 'front': 0, 'back': 0}
    for state in states:
        if state in state_counts:
            state_counts[state] += 1

    # Generate state frequency graph
    plt.figure(figsize=(8, 4))
    plt.bar(state_counts.keys(), state_counts.values(), color=['green', 'red', 'blue', 'orange', 'purple', 'brown'])
    plt.title("Car States Frequency")
    plt.xlabel("States")
    plt.ylabel("Frequency")
    plt.grid(axis='y')

    # Save frequency graph as base64 image
    freq_img = io.BytesIO()
    plt.savefig(freq_img, format='png')
    freq_img.seek(0)
    freq_img_data = base64.b64encode(freq_img.getvalue()).decode('utf8')
    plt.close()

    # Generate timestamp visualization graph
    plt.figure(figsize=(10, 5))
    plt.plot(timestamps, states, marker='o', linestyle='-', color='blue')
    plt.title("State Changes Over Time")
    plt.xlabel("Timestamps")
    plt.ylabel("States")
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Save timestamp graph as base64 image
    time_img = io.BytesIO()
    plt.savefig(time_img, format='png')
    time_img.seek(0)
    time_img_data = base64.b64encode(time_img.getvalue()).decode('utf8')
    plt.close()

    car_state_data = zip(timestamps, states)

    return render_template(
        'visualize.html',
        car_data=car_state_data,
        freq_img_data=freq_img_data,
        time_img_data=time_img_data
    )

# WebSocket event to update car states in real-time
@socketio.on('connect')
def handle_connect():
    print('Client connected.')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected.')

if __name__ == '__main__':
    socketio.run(app, debug=True)

