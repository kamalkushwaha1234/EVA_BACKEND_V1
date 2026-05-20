import json
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db, limiter
from app.models import Conversation, Device
from app.utils.auth import require_scope
from app.utils.errors import error_response

bp = Blueprint("devices", __name__)

# Idempotency key store (use Redis + TTL in production)
_idempotency_cache: dict[str, dict] = {}

COMMAND_TYPES = {"set_volume", "set_led", "reboot", "mute", "factory_reset", "check_ota"}
REQUIRES_ONLINE = {"reboot", "factory_reset"}


def _publish_command(device_id: str, payload: str):
    """Best-effort MQTT publish; failures are silently swallowed."""
    try:
        import paho.mqtt.publish as mqtt_publish
        from flask import current_app

        mqtt_publish.single(
            f"eva/v1/d/{device_id}/cmd",
            payload=payload,
            hostname=current_app.config["MQTT_BROKER_HOST"],
            port=current_app.config["MQTT_BROKER_PORT"],
            qos=1,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# POST /v1/devices/claim
# ---------------------------------------------------------------------------
@bp.post("/claim")
@jwt_required()
@require_scope("devices:write")
@limiter.limit("30 per minute")
def claim_device():
    idem_key = request.headers.get("Idempotency-Key", "").strip()
    if idem_key and idem_key in _idempotency_cache:
        return jsonify(_idempotency_cache[idem_key]), 201

    data = request.get_json(silent=True) or {}
    serial = data.get("serial", "").strip()
    claim_code = data.get("claim_code", "").strip()
    name = (data.get("name") or "").strip()

    if not serial or not claim_code:
        return error_response("VALIDATION_FAILED", "serial and claim_code are required.", 400)

    device = Device.query.filter_by(serial=serial).first()
    if not device:
        return error_response("DEVICE_NOT_FOUND", "No device matches the supplied serial.", 404)
    if device.owner_id:
        return error_response("DEVICE_ALREADY_CLAIMED", "Device is already bound to another account.", 409)

    # Validate claim code against the stored value on the device record.
    # The device's claim_code is a 6-digit string generated at provisioning time
    # and stored in a column (not yet modelled; use a simple length check here
    # as a placeholder — real validation compares against devices.claim_code).
    if not (claim_code.isdigit() and len(claim_code) == 6):
        return error_response("INVALID_CLAIM_CODE", "Claim code does not match the device.", 422)

    user_id = get_jwt_identity()
    device.owner_id = user_id
    device.claimed_at = datetime.utcnow()
    device.name = name[:60] if name else device.model
    db.session.commit()

    result = device.to_dict()
    if idem_key:
        _idempotency_cache[idem_key] = result
    return jsonify(result), 201


# ---------------------------------------------------------------------------
# GET /v1/devices
# ---------------------------------------------------------------------------
@bp.get("")
@jwt_required()
@require_scope("devices:read")
@limiter.limit("120 per minute")
def list_devices():
    user_id = get_jwt_identity()
    online_param = request.args.get("online")
    limit = min(int(request.args.get("limit", 50)), 100)
    cursor = request.args.get("cursor", "")

    query = Device.query.filter_by(owner_id=user_id)
    if online_param is not None:
        query = query.filter_by(online=(online_param.lower() == "true"))
    if cursor:
        query = query.filter(Device.id > cursor)

    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return jsonify({
        "items": [d.to_dict() for d in items],
        "next_cursor": items[-1].id if has_more else None,
    })


# ---------------------------------------------------------------------------
# GET /v1/devices/<device_id>
# ---------------------------------------------------------------------------
@bp.get("/<device_id>")
@jwt_required()
@require_scope("devices:read")
@limiter.limit("120 per minute")
def get_device(device_id):
    user_id = get_jwt_identity()
    device = db.session.get(Device, device_id)
    if not device:
        return error_response("DEVICE_NOT_FOUND", "No such device.", 404)
    if device.owner_id != user_id:
        return error_response("NOT_OWNER", "Device belongs to another user.", 403)
    return jsonify(device.to_dict())


# ---------------------------------------------------------------------------
# PATCH /v1/devices/<device_id>
# ---------------------------------------------------------------------------
@bp.patch("/<device_id>")
@jwt_required()
@require_scope("devices:write")
@limiter.limit("30 per minute")
def update_device(device_id):
    user_id = get_jwt_identity()
    device = db.session.get(Device, device_id)
    if not device:
        return error_response("DEVICE_NOT_FOUND", "No such device.", 404)
    if device.owner_id != user_id:
        return error_response("NOT_OWNER", "Caller does not own the device.", 403)

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name or len(name) > 60:
            return error_response("VALIDATION_FAILED", "Name must be 1–60 characters.", 400)
        device.name = name
        db.session.commit()

    return jsonify(device.to_dict())


# ---------------------------------------------------------------------------
# DELETE /v1/devices/<device_id>
# ---------------------------------------------------------------------------
@bp.delete("/<device_id>")
@jwt_required()
@require_scope("devices:write")
@limiter.limit("30 per minute")
def unclaim_device(device_id):
    user_id = get_jwt_identity()
    device = db.session.get(Device, device_id)
    if not device:
        return error_response("DEVICE_NOT_FOUND", "No such device.", 404)
    if device.owner_id != user_id:
        return error_response("NOT_OWNER", "Caller does not own the device.", 403)

    _publish_command(device_id, json.dumps({
        "command_id": f"cmd_{uuid.uuid4().hex[:6]}",
        "type": "factory_reset",
        "payload": {},
    }))

    device.owner_id = None
    device.claimed_at = None
    device.online = False
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# POST /v1/devices/<device_id>/commands
# ---------------------------------------------------------------------------
@bp.post("/<device_id>/commands")
@jwt_required()
@require_scope("devices:write")
@limiter.limit("30 per minute")
def send_command(device_id):
    user_id = get_jwt_identity()
    device = db.session.get(Device, device_id)
    if not device:
        return error_response("DEVICE_NOT_FOUND", "No such device.", 404)
    if device.owner_id != user_id:
        return error_response("NOT_OWNER", "Caller does not own the device.", 403)

    data = request.get_json(silent=True) or {}
    cmd_type = data.get("type")
    payload = data.get("payload", {})
    ttl = min(int(data.get("ttl_seconds", 30)), 300)

    if cmd_type not in COMMAND_TYPES:
        return error_response(
            "VALIDATION_FAILED",
            f"type must be one of: {', '.join(sorted(COMMAND_TYPES))}",
            400,
        )
    if cmd_type in REQUIRES_ONLINE and not device.online:
        return error_response("DEVICE_OFFLINE", "Command rejected: device is offline.", 409)

    command_id = f"cmd_{uuid.uuid4().hex[:6]}"
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=ttl)

    _publish_command(device_id, json.dumps({
        "command_id": command_id,
        "type": cmd_type,
        "payload": payload,
        "ttl_seconds": ttl,
    }))

    return jsonify({
        "command_id": command_id,
        "type": cmd_type,
        "status": "dispatched",
        "dispatched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), 202


# ---------------------------------------------------------------------------
# GET /v1/devices/<device_id>/conversations
# ---------------------------------------------------------------------------
@bp.get("/<device_id>/conversations")
@jwt_required()
@require_scope("conversations:read")
@limiter.limit("120 per minute")
def list_conversations(device_id):
    user_id = get_jwt_identity()
    device = db.session.get(Device, device_id)
    if not device:
        return error_response("DEVICE_NOT_FOUND", "No such device.", 404)
    if device.owner_id != user_id:
        return error_response("NOT_OWNER", "Device belongs to another user.", 403)

    from_ts = request.args.get("from")
    to_ts = request.args.get("to")
    limit = min(int(request.args.get("limit", 20)), 100)
    cursor = request.args.get("cursor", "")

    query = (
        Conversation.query
        .filter_by(device_id=device_id)
        .order_by(Conversation.started_at.desc())
    )
    if from_ts:
        query = query.filter(Conversation.started_at >= datetime.fromisoformat(from_ts.rstrip("Z")))
    if to_ts:
        query = query.filter(Conversation.started_at <= datetime.fromisoformat(to_ts.rstrip("Z")))
    if cursor:
        query = query.filter(Conversation.id < cursor)

    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return jsonify({
        "items": [c.to_dict() for c in items],
        "next_cursor": items[-1].id if has_more else None,
    })
