import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _client():
    from flask import current_app

    cfg = current_app.config
    kwargs = {"region_name": cfg["S3_REGION"]}
    if cfg["S3_ACCESS_KEY"] and cfg["S3_SECRET_KEY"]:
        kwargs["aws_access_key_id"] = cfg["S3_ACCESS_KEY"]
        kwargs["aws_secret_access_key"] = cfg["S3_SECRET_KEY"]
    return boto3.client("s3", **kwargs)


def upload(file_path: str, key: str) -> str | None:
    from flask import current_app

    bucket = current_app.config["S3_BUCKET"]
    if not bucket:
        return None

    try:
        _client().upload_file(
            Filename=file_path,
            Bucket=bucket,
            Key=key,
            ExtraArgs={"ACL": "public-read"},
        )
        public_url = current_app.config["S3_PUBLIC_URL"]
        if public_url:
            return f"{public_url}/{key}"
        return f"https://{bucket}.s3.{current_app.config['S3_REGION']}.amazonaws.com/{key}"
    except ClientError:
        logger.exception("[S3] Upload failed: %s", key)
        return None


def upload_bytes(data: bytes, key: str, content_type: str = "audio/mpeg") -> str | None:
    from flask import current_app

    bucket = current_app.config["S3_BUCKET"]
    if not bucket:
        return None

    try:
        _client().put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ACL="public-read",
        )
        public_url = current_app.config["S3_PUBLIC_URL"]
        if public_url:
            return f"{public_url}/{key}"
        return f"https://{bucket}.s3.{current_app.config['S3_REGION']}.amazonaws.com/{key}"
    except ClientError:
        logger.exception("[S3] Upload failed: %s", key)
        return None
