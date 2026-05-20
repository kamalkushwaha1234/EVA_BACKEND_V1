import re
import uuid
from datetime import datetime, timedelta

import bcrypt
from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
)

from app.extensions import db, limiter
from app.models import User
from app.utils.errors import error_response

bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Maps user_id -> UTC timestamp of last logout; used to invalidate refresh tokens.
# Use Redis in production.
_logout_timestamps: dict[str, float] = {}

# Consumed refresh token jtis (single-use). Use Redis in production.
_revoked_jtis: set[str] = set()

DEFAULT_SCOPES = "devices:read devices:write conversations:read subscriptions:manage"


def _make_token_pair(user_id: str):
    access_token = create_access_token(
        identity=user_id,
        additional_claims={"type": "access", "scope": DEFAULT_SCOPES},
    )
    refresh_token = create_refresh_token(
        identity=user_id,
        additional_claims={"type": "refresh", "scope": DEFAULT_SCOPES},
    )
    return access_token, refresh_token


def _token_pair_response(access_token: str, refresh_token: str) -> dict:
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": 900,
    }


# ---------------------------------------------------------------------------
# POST /v1/auth/register
# ---------------------------------------------------------------------------
@bp.post("/register")
@limiter.limit("10 per minute")
def register():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    display_name = (data.get("display_name") or "").strip()

    errors = {}
    if not _EMAIL_RE.match(email):
        errors["email"] = "A valid email address is required."
    if not password or not (8 <= len(password) <= 128):
        errors["password"] = "Password must be 8–128 characters."
    if errors:
        return error_response("VALIDATION_FAILED", "Validation failed.", 400, errors)

    if User.query.filter_by(email=email).first():
        return error_response("EMAIL_ALREADY_REGISTERED", "An account with this email exists.", 409)

    pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(
        email=email,
        pwd_hash=pwd_hash,
        display_name=display_name[:80] or None,
    )
    db.session.add(user)
    db.session.commit()

    access_token, refresh_token = _make_token_pair(user.id)
    return jsonify({
        "user": user.to_dict(),
        **_token_pair_response(access_token, refresh_token),
    }), 201


# ---------------------------------------------------------------------------
# POST /v1/auth/login
# ---------------------------------------------------------------------------
@bp.post("/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(email=email).first()
    now = datetime.utcnow()

    if user and user.locked_until and user.locked_until > now:
        return error_response("INVALID_CREDENTIALS", "Email or password incorrect.", 401)

    valid = user and bcrypt.checkpw(password.encode(), user.pwd_hash.encode())

    if not valid:
        if user:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_logins = 0
            db.session.commit()
        return error_response("INVALID_CREDENTIALS", "Email or password incorrect.", 401)

    user.failed_logins = 0
    user.locked_until = None
    db.session.commit()

    access_token, refresh_token = _make_token_pair(user.id)
    return jsonify(_token_pair_response(access_token, refresh_token))


# ---------------------------------------------------------------------------
# POST /v1/auth/refresh
# ---------------------------------------------------------------------------
@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    claims = get_jwt()
    jti = claims.get("jti")
    user_id = get_jwt_identity()
    iat = claims.get("iat", 0)

    if jti in _revoked_jtis:
        # Theft detection: reuse of a consumed token; revoke the whole family
        # (here we just reject — family tracking needs a DB table in production)
        return error_response("TOKEN_INVALID", "Refresh token has been revoked.", 401)

    logout_ts = _logout_timestamps.get(user_id)
    if logout_ts and iat < logout_ts:
        return error_response("TOKEN_INVALID", "Refresh token has been revoked.", 401)

    _revoked_jtis.add(jti)  # single-use rotation

    access_token, refresh_token = _make_token_pair(user_id)
    return jsonify(_token_pair_response(access_token, refresh_token))


# ---------------------------------------------------------------------------
# POST /v1/auth/logout
# ---------------------------------------------------------------------------
@bp.post("/logout")
@jwt_required()
def logout():
    user_id = get_jwt_identity()
    _logout_timestamps[user_id] = datetime.utcnow().timestamp()
    return "", 204
