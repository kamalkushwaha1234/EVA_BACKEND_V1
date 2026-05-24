from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    from bridge import start_bridge
    start_bridge(app)  # MQTT + UDP threads start here, non-blocking
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
