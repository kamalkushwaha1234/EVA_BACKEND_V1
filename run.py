from app import create_app
from app.extensions import socketio
import logging

logger = logging.getLogger(__name__)

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
