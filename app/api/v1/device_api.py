import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from app.extensions import db, limiter
from app.models import Conversation
from app.utils.errors import error_response
from app.utils.mtls import require_device_cert

bp = Blueprint("device_api", __name__)


# ---------------------------------------------------------------------------
# POST /v1/device/bootstrap
# ---------------------------------------------------------------------------
@bp.post("/bootstrap")
@require_device_cert
@limiter.limit("30 per minute")
def bootstrap():
    device = request.device
    data = request.get_json(silent=True) or {}

    serial = data.get("serial", "").strip()
    model = data.get("model", "").strip()
    fw_version = data.get("fw_version", "").strip()
    hw_revision = data.get("hw_revision")
    mac = data.get("mac")

    if not serial or not model or not fw_version:
        return error_response("VALIDATION_FAILED", "serial, model, and fw_version are required.", 400)

    # Reject if this serial is already bound to a *different* device record
    from app.models import Device

    existing = Device.query.filter_by(serial=serial).first()
    if existing and existing.id != device.id:
        return error_response(
            "SERIAL_CERT_MISMATCH",
            "Serial is already bound to a different certificate.",
            409,
        )

    is_new = device.serial is None
    device.serial = serial
    device.model = model
    device.fw_version = fw_version
    device.hw_revision = hw_revision
    device.mac = mac
    device.last_seen = datetime.utcnow()
    db.session.commit()

    config = {
        "device_id": device.id,
        "mqtt": {
            "host": "mqtt.eva.ai",
            "port": 8883,
            "topic_root": f"eva/v1/d/{device.id}",
        },
        "claimed": device.owner_id is not None,
        "heartbeat_interval_s": device.heartbeat_interval_s,
        "ota_poll_interval_s": device.ota_poll_interval_s,
        "server_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return jsonify(config), 201 if is_new else 200


# ---------------------------------------------------------------------------
# POST /v1/device/audio/session
# ---------------------------------------------------------------------------
@bp.post("/audio/session")
@require_device_cert
@limiter.limit("60 per minute")
def audio_session():
    device = request.device
    if not device.owner_id:
        return error_response(
            "DEVICE_NOT_CLAIMED",
            "Device must be claimed before starting a voice session.",
            409,
        )

    data = request.get_json(silent=True) or {}
    trigger = data.get("trigger")
    if trigger not in ("wakeword", "button"):
        return error_response("VALIDATION_FAILED", "trigger must be 'wakeword' or 'button'.", 400)

    codec = data.get("codec", "opus")
    sample_rate = int(data.get("sample_rate", 16000))

    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, device_id=device.id)
    db.session.add(conv)
    device.last_seen = datetime.utcnow()
    db.session.commit()

    expires_at = (datetime.utcnow() + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return jsonify({
        "session_id": f"as_{uuid.uuid4().hex[:6]}",
        "session_token": f"aud_{uuid.uuid4().hex}",
        "conv_id": conv_id,
        "gateway": {"host": "audio.eva.ai", "port": 5684},
        "codec": codec,
        "sample_rate": sample_rate,
        "expires_at": expires_at,
    }), 201


# ---------------------------------------------------------------------------
# POST /v1/device/heartbeat
# ---------------------------------------------------------------------------
@bp.post("/heartbeat")
@require_device_cert
@limiter.limit("120 per minute")
def heartbeat():
    device = request.device
    data = request.get_json(silent=True) or {}

    fw_version = data.get("fw_version", "").strip()
    uptime_s = data.get("uptime_s")
    if not fw_version or uptime_s is None:
        return error_response("VALIDATION_FAILED", "fw_version and uptime_s are required.", 400)

    device.fw_version = fw_version
    device.uptime_s = int(uptime_s)
    device.wifi_rssi = data.get("wifi_rssi", device.wifi_rssi)
    device.last_seen = datetime.utcnow()
    device.online = True
    db.session.commit()

    return jsonify({
        "ack": True,
        "server_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heartbeat_interval_s": device.heartbeat_interval_s,
        "pending_action": None,
    })


# ---------------------------------------------------------------------------
# POST /v1/device/logs
# ---------------------------------------------------------------------------
@bp.post("/logs")
@require_device_cert
@limiter.limit("30 per minute")
def upload_logs():
    device = request.device  # noqa: F841
    data = request.get_json(silent=True) or {}

    reason = data.get("reason")
    entries = data.get("entries", [])

    VALID_REASONS = {"crash", "error", "periodic", "requested"}
    if reason not in VALID_REASONS:
        return error_response(
            "VALIDATION_FAILED",
            f"reason must be one of: {', '.join(sorted(VALID_REASONS))}",
            400,
        )
    if not isinstance(entries, list) or len(entries) > 500:
        return error_response("VALIDATION_FAILED", "entries must be a list of at most 500 items.", 400)

    # Ingest entries into your logging pipeline here (e.g. Cloud Logging, Datadog)
    log_batch_id = f"log_{uuid.uuid4().hex[:8]}"
    return jsonify({"accepted": len(entries), "log_batch_id": log_batch_id}), 202
