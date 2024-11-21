from flask import Flask, request,render_template

app = Flask(__name__)


@app.route('/')
def home():
    return render_template('index2.html', data=received_data or "No data received yet!")

@app.route('/receive-data', methods=['POST'])
def receive_data():
    global received_data
    data = request.get_json()
    print(f"Received data: {data}")
    
    # Store the received data in the global variable
    received_data = data['value']
    
    # Simply return a success message
    return "Data received successfully! Go to the home page to see it."

if __name__ == '__main__':
    app.run(port=5001,debug=True)
