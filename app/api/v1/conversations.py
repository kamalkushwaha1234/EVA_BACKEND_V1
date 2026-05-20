from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db, limiter
from app.models import Conversation, Device, Message
from app.utils.auth import require_scope
from app.utils.errors import error_response

bp = Blueprint("conversations", __name__)


# ---------------------------------------------------------------------------
# GET /v1/conversations/<conv_id>/messages
# ---------------------------------------------------------------------------
@bp.get("/<conv_id>/messages")
@jwt_required()
@require_scope("conversations:read")
@limiter.limit("120 per minute")
def get_messages(conv_id):
    user_id = get_jwt_identity()

    conv = db.session.get(Conversation, conv_id)
    if not conv:
        return error_response("CONVERSATION_NOT_FOUND", "No such conversation.", 404)

    device = db.session.get(Device, conv.device_id)
    if not device or device.owner_id != user_id:
        return error_response("NOT_OWNER", "Not authorized to access this conversation.", 403)

    limit = min(int(request.args.get("limit", 100)), 200)
    cursor = request.args.get("cursor", "")

    query = Message.query.filter_by(conv_id=conv_id).order_by(Message.ts.asc())
    if cursor:
        query = query.filter(Message.id > int(cursor))

    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return jsonify({
        "items": [m.to_dict() for m in items],
        "next_cursor": str(items[-1].id) if has_more else None,
    })
