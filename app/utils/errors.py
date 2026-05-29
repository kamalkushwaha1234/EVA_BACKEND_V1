from flask import current_app, jsonify, request


def error_response(code: str, message: str, status: int, details=None):
    current_app.logger.warning(
        "API error code=%s status=%s path=%s request_id=%s",
        code,
        status,
        request.path,
        request.headers.get("X-Request-Id", "req_unknown"),
    )
    body = {
        "error": {
            "code": code,
            "message": message,
            "status": status,
            "request_id": request.headers.get("X-Request-Id", "req_unknown"),
        }
    }
    if details:
        body["error"]["details"] = details
    return jsonify(body), status
