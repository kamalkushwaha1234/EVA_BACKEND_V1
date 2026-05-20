import uuid
from datetime import datetime
from app.extensions import db


class Conversation(db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(db.String(64), db.ForeignKey("devices.id"), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)

    messages = db.relationship(
        "Message", backref="conversation", lazy=True, order_by="Message.ts"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "started_at": self.started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ended_at": self.ended_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.ended_at else None,
        }
