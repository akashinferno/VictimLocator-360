from flask import Flask, request, render_template, session, redirect, url_for
from flask_socketio import SocketIO, emit
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = 'hello'

# Enable CORS for the Flask app
CORS(app, resources={r"/*": {"origins": ["http://127.0.0.1:5000", "http://localhost:5000"]}})

# Initialize Flask-SocketIO with CORS support
socketio = SocketIO(app, cors_allowed_origins=["http://127.0.0.1:5000", "http://localhost:5000"])

@app.route('/', methods=['GET', 'POST'])
def homepage():
    if request.method == 'POST':
        session["username"] = request.form.get("username")
        username = session['username']
        return render_template("index.html", username=username)
    else:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        return redirect(url_for('homepage'))
    else:
        return render_template('login.html')

@app.route('/start-session')
def start_session():
    return render_template('start_session.html')

# WebSocket Handlers
@socketio.on('connect')
def handle_connect():
    print("Client connected")
    emit('server_message', {'message': 'Welcome to the WebSocket server!'})

@socketio.on('disconnect')
def handle_disconnect():
    print("Client disconnected")

@socketio.on('toggle_motor')
def handle_toggle_motor(data):
    motor = data.get('motor')
    action = data.get('action')
    print(f"Motor: {motor} toggled: {action}")
    # Optionally send a confirmation back to the client
    # emit('motor_status', {'motor': motor, 'status': action})

if __name__ == "__main__":
    socketio.run(app, port=5000, debug=True)
