import logging
from logging import FileHandler, Formatter
from pathlib import Path
from time import perf_counter

from flask import Flask, g, request
from app.config import Config
from app.extensions import db, jwt, socketio, limiter


def _configure_logging(app: Flask) -> None:
    root_logger = logging.getLogger()
    log_path = Path(app.root_path).parent / "logFile.log"
    log_path.touch(exist_ok=True)

    if not any(
        isinstance(handler, FileHandler)
        and Path(getattr(handler, "baseFilename", "")) == log_path
        for handler in root_logger.handlers
    ):
        file_handler = FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root_logger.addHandler(file_handler)

    root_logger.setLevel(logging.INFO)
    app.logger.setLevel(logging.INFO)
    app.logger.info("Application logging initialized at %s", log_path)


def _register_request_logging(app: Flask) -> None:
    @app.before_request
    def _log_request_start():
        g._request_started_at = perf_counter()

    @app.after_request
    def _log_request_response(response):
        started_at = getattr(g, "_request_started_at", None)
        duration_ms = (
            round((perf_counter() - started_at) * 1000, 2)
            if started_at is not None
            else None
        )
        status_code = response.status_code
        level = logging.WARNING if status_code >= 400 else logging.INFO
        app.logger.log(
            level,
            "API %s %s -> %s ip=%s duration_ms=%s",
            request.method,
            request.path,
            status_code,
            request.headers.get("X-Forwarded-For", request.remote_addr),
            duration_ms,
        )
        return response


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    _configure_logging(app)
    _register_request_logging(app)

    db.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*", async_mode="eventlet")
    limiter.init_app(app)

    from app.api.v1 import (  # noqa: E402
        auth, devices, conversations, subscriptions, device_api, ota, ai
    )

    app.register_blueprint(auth.bp, url_prefix="/v1/auth")
    app.register_blueprint(devices.bp, url_prefix="/v1/devices")
    app.register_blueprint(conversations.bp, url_prefix="/v1/conversations")
    app.register_blueprint(subscriptions.bp, url_prefix="/v1/subscriptions")
    app.register_blueprint(device_api.bp, url_prefix="/v1/device")
    app.register_blueprint(ota.bp, url_prefix="/v1/ota")
    app.register_blueprint(ai.bp, url_prefix="/v1/ai")

    from app.websocket import handlers  # noqa: F401

    with app.app_context():
        db.create_all()

    return app
