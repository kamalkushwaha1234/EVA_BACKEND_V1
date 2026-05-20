import uuid
from datetime import datetime
from app.extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    pwd_hash = db.Column(db.Text, nullable=False)
    display_name = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)
    failed_logins = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)

    devices = db.relationship("Device", backref="owner", lazy=True)
    subscriptions = db.relationship("Subscription", backref="user", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
