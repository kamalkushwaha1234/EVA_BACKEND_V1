import hashlib

from flask import Blueprint, jsonify, request

from app.extensions import limiter
from app.models import OtaRelease
from app.utils.errors import error_response
from app.utils.mtls import require_device_cert

bp = Blueprint("ota", __name__)


def _semver_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0, 0, 0)


def _in_rollout(device_id: str, pct: int) -> bool:
    """Deterministic hash-bucket check for staged rollout (0–100)."""
    bucket = int(hashlib.md5(device_id.encode()).hexdigest(), 16) % 100
    return bucket < pct


# ---------------------------------------------------------------------------
# GET /v1/ota/check
# ---------------------------------------------------------------------------
@bp.get("/check")
@require_device_cert
@limiter.limit("6 per hour")
def check_ota():
    device = request.device
    model = request.args.get("model", "").strip()
    current = request.args.get("current", "").strip()
    channel = request.args.get("channel", "stable")

    if not model or not current:
        return error_response("VALIDATION_FAILED", "model and current are required.", 400)
    if channel not in ("stable", "beta"):
        channel = "stable"

    release = (
        OtaRelease.query
        .filter_by(model=model, channel=channel)
        .all()
    )
    # Pick the highest version greater than current
    newer = [r for r in release if _semver_tuple(r.version) > _semver_tuple(current)]
    if not newer:
        return "", 204

    latest = max(newer, key=lambda r: _semver_tuple(r.version))

    if not _in_rollout(device.id, latest.rollout_pct):
        return "", 204

    return jsonify(latest.to_manifest())


# ---------------------------------------------------------------------------
# GET /v1/ota/blob/<version>
# ---------------------------------------------------------------------------
@bp.get("/blob/<version>")
@require_device_cert
def download_blob(version):
    release = OtaRelease.query.get(version)
    if not release:
        return error_response("VERSION_NOT_FOUND", "No release with that version.", 404)

    # In production, redirect to a short-lived signed S3/GCS URL:
    #   return redirect(generate_signed_url(release.blob_url))
    # For now we return the raw blob_url so the device can fetch it directly.
    from flask import redirect
    return redirect(release.blob_url, code=302)
