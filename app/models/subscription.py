import uuid
from app.extensions import db


class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    device_id = db.Column(db.String(64), db.ForeignKey("devices.id"), nullable=True)
    plan = db.Column(db.String(16), nullable=False, default="free")      # free | plus | pro
    status = db.Column(db.String(16), nullable=False, default="active")  # active | past_due | canceled
    provider = db.Column(db.String(32))
    provider_sub_id = db.Column(db.String(128))
    started_at = db.Column(db.DateTime(timezone=True))
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "plan": self.plan,
            "status": self.status,
            "device_id": self.device_id,
            "provider": self.provider,
            "started_at": self.started_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.started_at else None,
            "ends_at": self.ends_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.ends_at else None,
        }
