from functools import wraps
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from app.utils.errors import error_response


def require_scope(*scopes):
    """Decorator that ensures the JWT contains all listed scopes."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            token_scopes = set(get_jwt().get("scope", "").split())
            missing = [s for s in scopes if s not in token_scopes]
            if missing:
                return error_response(
                    "FORBIDDEN_SCOPE",
                    f"Token lacks required scope(s): {', '.join(missing)}",
                    403,
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
