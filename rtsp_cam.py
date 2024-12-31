from flask import Flask, Response
import cv2

# Flask app setup
app = Flask(__name__)

# Replace with the actual IP Webcam app's RTSP URL
RTSP_URL = "rtsp://192.168.29.99:8080/h264_ulaw.sdp"  # Example URL

def generate_frames():
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise Exception(f"Unable to open RTSP stream: {RTSP_URL}")

    frame_count = 0
    while True:
        success, frame = cap.read()
        if not success:
            break

        # Skip every 3rd frame for real-time performance
        frame_count += 1
        if frame_count % 3 == 0:
            continue

        # Reduce frame resolution to 640x480
        frame = cv2.resize(frame, (640, 480))

        # Encode with lower JPEG quality
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()


@app.route('/video_feed')
def video_feed():
    # Serve MJPEG stream
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    # Simple HTML to display video feed
    return """
    <html>
        <head>
            <title>IP Webcam Stream</title>
        </head>
        <body>
            <h1>RTSP Stream from IP Webcam</h1>
            <img src="/video_feed" width="640" height="480" 3/>
        </body>
    </html>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
