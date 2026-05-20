from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db, limiter
from app.models import Subscription
from app.utils.auth import require_scope
from app.utils.errors import error_response

bp = Blueprint("subscriptions", __name__)

VALID_PLANS = {"free", "plus", "pro"}


# ---------------------------------------------------------------------------
# GET /v1/subscriptions/me
# ---------------------------------------------------------------------------
@bp.get("/me")
@jwt_required()
@limiter.limit("120 per minute")
def get_subscription():
    user_id = get_jwt_identity()
    sub = Subscription.query.filter_by(user_id=user_id, status="active").first()
    if not sub:
        return error_response("NO_SUBSCRIPTION", "User has no subscription record.", 404)
    return jsonify(sub.to_dict())


# ---------------------------------------------------------------------------
# POST /v1/subscriptions/change
# ---------------------------------------------------------------------------
@bp.post("/change")
@jwt_required()
@require_scope("subscriptions:manage")
@limiter.limit("30 per minute")
def change_plan():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    plan = data.get("plan")
    device_id = data.get("device_id")

    if plan not in VALID_PLANS:
        return error_response(
            "VALIDATION_FAILED",
            f"plan must be one of: {', '.join(sorted(VALID_PLANS))}",
            400,
        )

    existing = Subscription.query.filter_by(user_id=user_id, status="active").first()
    if existing and existing.plan == plan:
        return error_response("ALREADY_ON_PLAN", "User is already on the requested plan.", 409)

    if plan == "free":
        if existing:
            existing.plan = "free"
            existing.provider = None
            existing.provider_sub_id = None
            existing.ends_at = None
        else:
            db.session.add(Subscription(
                user_id=user_id,
                plan="free",
                status="active",
                started_at=datetime.utcnow(),
                device_id=device_id,
            ))
        db.session.commit()
        return jsonify({"status": "changed", "checkout_url": None})

    # Paid upgrade — return a Stripe checkout URL (placeholder)
    checkout_url = (
        f"https://checkout.stripe.com/placeholder?plan={plan}"
        f"&user={user_id}"
        + (f"&device={device_id}" if device_id else "")
    )
    return jsonify({"status": "pending_checkout", "checkout_url": checkout_url})
