import uuid
from datetime import datetime

from flask import request
from flask_jwt_extended import decode_token
from flask_socketio import disconnect, emit, join_room, leave_room

from app.extensions import socketio
from app.models import Device

# sid -> user_id
_connected: dict[str, str] = {}
# user_id -> set[device_id]
_subscriptions: dict[str, set] = {}


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _evt_id() -> str:
    return f"evt_{uuid.uuid4().hex[:4]}"


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------
@socketio.on("connect")
def on_connect(auth):
    token = request.args.get("token") or (auth or {}).get("token", "")
    if not token:
        disconnect()
        return False
    try:
        payload = decode_token(token)
        if payload.get("type") == "refresh":
            raise ValueError("refresh token not accepted")
        user_id = payload["sub"]
        _connected[request.sid] = user_id
        _subscriptions.setdefault(user_id, set())
    except Exception:
        disconnect()
        return False


@socketio.on("disconnect")
def on_disconnect():
    user_id = _connected.pop(request.sid, None)
    if user_id:
        # Clean up rooms — Flask-SocketIO handles room membership automatically on disconnect
        _subscriptions.pop(user_id, None)


# ---------------------------------------------------------------------------
# Client → Server messages
# ---------------------------------------------------------------------------
@socketio.on("subscribe")
def on_subscribe(data):
    user_id = _connected.get(request.sid)
    if not user_id:
        emit("error", {"code": "UNAUTHORIZED", "message": "Not authenticated."})
        return

    device_ids = data.get("device_ids", [])
    for device_id in device_ids:
        device = Device.query.get(device_id)
        if not device or device.owner_id != user_id:
            emit("error", {
                "code": "FORBIDDEN",
                "message": f"Not the owner of device {device_id}.",
            })
            continue
        join_room(f"device:{device_id}")
        _subscriptions[user_id].add(device_id)


@socketio.on("unsubscribe")
def on_unsubscribe(data):
    user_id = _connected.get(request.sid)
    device_ids = data.get("device_ids", [])
    for device_id in device_ids:
        leave_room(f"device:{device_id}")
        if user_id:
            _subscriptions.get(user_id, set()).discard(device_id)


@socketio.on("pong")
def on_pong(_data):
    pass  # heartbeat reply; no response needed


# ---------------------------------------------------------------------------
# Server → Client helpers (called from other parts of the app)
# ---------------------------------------------------------------------------
def push_event(device_id: str, event_type: str, data: dict):
    """Broadcast a typed event envelope to all subscribers of a device."""
    socketio.emit(
        "message",
        {
            "type": event_type,
            "id": _evt_id(),
            "ts": _now(),
            "data": data,
        },
        room=f"device:{device_id}",
    )


def push_transcript_partial(device_id: str, conv_id: str, role: str, text: str):
    push_event(device_id, "transcript.partial", {
        "device_id": device_id,
        "conv_id": conv_id,
        "role": role,
        "text": text,
    })


def push_transcript_final(device_id: str, conv_id: str, message_id: int, role: str, text: str):
    push_event(device_id, "transcript.final", {
        "device_id": device_id,
        "conv_id": conv_id,
        "message_id": message_id,
        "role": role,
        "text": text,
    })


def push_device_online(device_id: str, fw_version: str):
    push_event(device_id, "device.online", {
        "device_id": device_id,
        "fw_version": fw_version,
    })


def push_device_offline(device_id: str, reason: str = "lwt"):
    push_event(device_id, "device.offline", {
        "device_id": device_id,
        "reason": reason,
    })


def push_command_ack(device_id: str, command_id: str, status: str):
    push_event(device_id, "command.ack", {
        "device_id": device_id,
        "command_id": command_id,
        "status": status,
    })


def push_ota_progress(device_id: str, version: str, phase: str, pct: int):
    push_event(device_id, "ota.progress", {
        "device_id": device_id,
        "version": version,
        "phase": phase,
        "pct": pct,
    })
