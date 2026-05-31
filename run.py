from app import create_app
from app.extensions import socketio
import logging

logger = logging.getLogger(__name__)

app = create_app()

if __name__ == "__main__":
    from bridge import start_bridge
    try:
        start_bridge(app)  # MQTT + UDP threads start here, non-blocking
        logger.info("Bridge started successfully")
    except Exception as e:
        logger.warning(f"Bridge failed to start (continuing without it): {e}")
    
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
