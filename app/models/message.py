from datetime import datetime
from app.extensions import db


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    conv_id = db.Column(db.String(36), db.ForeignKey("conversations.id"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)  # "user" or "assistant"
    text = db.Column(db.Text, nullable=False)
    audio_url = db.Column(db.Text, nullable=True)
    ts = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "conv_id": self.conv_id,
            "role": self.role,
            "text": self.text,
            "audio_url": self.audio_url,
            "ts": self.ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
