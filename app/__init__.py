from flask import Flask
from app.config import Config
from app.extensions import db, jwt, socketio, limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="eventlet")
    limiter.init_app(app)

    from app.api.v1 import auth, devices, conversations, subscriptions, device_api, ota

    app.register_blueprint(auth.bp, url_prefix="/v1/auth")
    app.register_blueprint(devices.bp, url_prefix="/v1/devices")
    app.register_blueprint(conversations.bp, url_prefix="/v1/conversations")
    app.register_blueprint(subscriptions.bp, url_prefix="/v1/subscriptions")
    app.register_blueprint(device_api.bp, url_prefix="/v1/device")
    app.register_blueprint(ota.bp, url_prefix="/v1/ota")

    from app.websocket import handlers  # noqa: F401 — registers SocketIO event handlers

    with app.app_context():
        db.create_all()

    return app
