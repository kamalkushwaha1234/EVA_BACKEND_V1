from app.extensions import db


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.String(64), primary_key=True)
    serial = db.Column(db.String(128), unique=True, nullable=True)
    model = db.Column(db.String(64))
    fw_version = db.Column(db.String(32))
    hw_revision = db.Column(db.String(32))
    mac = db.Column(db.String(17))
    name = db.Column(db.String(60))
    owner_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True)
    cert_fp = db.Column(db.String(128), unique=True, nullable=False, index=True)
    cert_revoked = db.Column(db.Boolean, default=False)
    claimed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen = db.Column(db.DateTime(timezone=True), nullable=True)
    online = db.Column(db.Boolean, default=False)
    volume = db.Column(db.Integer, default=50)
    muted = db.Column(db.Boolean, default=False)
    led_mode = db.Column(db.String(16), default="idle")
    wifi_rssi = db.Column(db.Integer)
    uptime_s = db.Column(db.Integer)
    heartbeat_interval_s = db.Column(db.Integer, default=300)
    ota_poll_interval_s = db.Column(db.Integer, default=3600)

    conversations = db.relationship("Conversation", backref="device", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "serial": self.serial,
            "model": self.model,
            "name": self.name or self.model,
            "fw_version": self.fw_version,
            "owner_id": self.owner_id,
            "claimed_at": _fmt(self.claimed_at),
            "last_seen": _fmt(self.last_seen),
            "online": self.online,
        }


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None
