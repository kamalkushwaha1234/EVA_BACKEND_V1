import logging

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


def _client():
    from flask import current_app

    # Credentials come from the EC2 instance role (aws-elasticbeanstalk-ec2-role).
    return boto3.client("s3", region_name=current_app.config["S3_REGION"])


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
            ContentType="audio/mpeg",
            ContentDisposition='inline'
        )
        public_url = current_app.config["S3_PUBLIC_URL"]
        if public_url:
            return f"{public_url}/{key}"
        return f"https://{bucket}.s3.{current_app.config['S3_REGION']}.amazonaws.com/{key}"
    except (ClientError, BotoCoreError, S3UploadFailedError):
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
            ContentDisposition='inline'
        )
        public_url = current_app.config["S3_PUBLIC_URL"]
        if public_url:
            return f"{public_url}/{key}"
        return f"https://{bucket}.s3.{current_app.config['S3_REGION']}.amazonaws.com/{key}"
    except (ClientError, BotoCoreError, S3UploadFailedError):
        logger.exception("[S3] Upload failed: %s", key)
        return None
