import requests
import json
from datetime import datetime
import time
import random
# Define the endpoint URL
url = "http://127.0.0.1:5000/data"  # Replace with your endpoint URL

# Define the sensor name
sensor_name = "Microwave Sensor"

# Loop to send data 5 times
for i in range(10):
    # Create the JSON payload
    data = {
        "sensor_name": sensor_name,
        "value": random.randint(1,10000),  # Example data value; replace with actual sensor value
        "timestamp":datetime.now().strftime("%d-%m-%y %H:%M:%S")  # Current timestamp in seconds
    }
    
    # Send POST request to the Flask app
    response = requests.post(url, json=data)
    
    # Print the status code and response from the server
    print(f"POST Request {i + 1}: Status Code: {response.status_code}, Response: {response.text}")
    
    # Wait for 4 seconds before sending the next data
    time.sleep(2)