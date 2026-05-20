from functools import wraps
from flask import request
from app.models import Device
from app.utils.errors import error_response


def require_device_cert(fn):
    """
    Resolves the mTLS client certificate to a Device record.

    In production, the TLS-terminating proxy (nginx / ALB) performs the
    handshake and forwards the certificate fingerprint as:
        X-SSL-Client-Fingerprint: <sha256-hex>

    In development you can set this header directly when calling the API.
    The resolved Device is attached to request.device for use in the handler.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        cert_fp = request.headers.get("X-SSL-Client-Fingerprint", "").strip()
        if not cert_fp:
            return error_response("CERT_MISSING", "mTLS client certificate required.", 403)

        device = Device.query.filter_by(cert_fp=cert_fp).first()
        if not device:
            return error_response("CERT_REVOKED", "Certificate unknown or revoked.", 403)
        if device.cert_revoked:
            return error_response("CERT_REVOKED", "Certificate has been revoked.", 403)

        request.device = device
        return fn(*args, **kwargs)
    return wrapper
