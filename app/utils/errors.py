from flask import jsonify, request


def error_response(code: str, message: str, status: int, details=None):
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
