from app.extensions import db


class OtaRelease(db.Model):
    __tablename__ = "ota_releases"

    version = db.Column(db.String(32), primary_key=True)
    model = db.Column(db.String(64), nullable=False)
    channel = db.Column(db.String(16), default="stable")  # "stable" or "beta"
    blob_url = db.Column(db.Text, nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    signature = db.Column(db.Text, nullable=False)  # base64 Ed25519
    rollout_pct = db.Column(db.Integer, default=100)
    notes = db.Column(db.Text)
    mandatory = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime(timezone=True))

    def to_manifest(self, base_url="https://api.eva.ai"):
        return {
            "manifest_version": 1,
            "version": self.version,
            "model": self.model,
            "blob_url": f"{base_url}/v1/ota/blob/{self.version}",
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "signature": self.signature,
            "rollout_pct": self.rollout_pct,
            "notes": self.notes,
            "mandatory": self.mandatory,
        }
