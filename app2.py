from flask import Flask
import requests
import random
import time
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Welcome to the Flask app! Use /start-sending to start sending random data."

# Function to send data continuously
def send_data_continuously():
    while True:
        random_value = random.randint(1, 100)
        data = {'value': random_value}
        
        try:
            # Send data to the receiver app using POST
            response = requests.post('http://127.0.0.1:5001/receive-data', json=data)
            print(f"Sent data: {data}")
        except Exception as e:
            print(f"Error sending data: {e}")
        
        # Wait for 5 seconds before sending the next data
        time.sleep(5)

@app.route('/start-sending', methods=['POST','GET'])
def start_sending_data():
    # Start the continuous sending in a separate thread
    thread = threading.Thread(target=send_data_continuously, daemon=True)
    thread.start()  # Start the thread
    return "Started sending data continuously!"

if __name__ == '__main__':
    # Ensure the app runs with threaded=True so it doesn't block
    app.run(port=5000, threaded=True,debug=True)
