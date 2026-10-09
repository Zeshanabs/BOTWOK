"""S3-compatible storage adapter (SeaweedFS/MinIO locally, S3/R2 on a VPS)."""
from __future__ import annotations

import aioboto3
from botocore.config import Config

from app.config import settings
from app.core.logging import get_logger

log = get_logger("storage")
BUCKETS = [settings.s3_bucket_media, settings.s3_bucket_documents, settings.s3_bucket_reports, "exports", "tmp"]


def _session():
    return aioboto3.Session(aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
                            region_name=settings.s3_region)


def _client():
    return _session().client("s3", endpoint_url=settings.s3_endpoint, config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"))


class S3Storage:
    name = "s3"

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        async with _client() as c:
            await c.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, bucket: str, key: str) -> bytes:
        async with _client() as c:
            obj = await c.get_object(Bucket=bucket, Key=key)
            return await obj["Body"].read()

    async def delete(self, bucket: str, key: str) -> None:
        async with _client() as c:
            await c.delete_object(Bucket=bucket, Key=key)

    async def presign_put(self, bucket: str, key: str, content_type: str, expires_s: int = 900) -> str:
        async with _client() as c:
            return await c.generate_presigned_url("put_object", Params={"Bucket": bucket, "Key": key, "ContentType": content_type}, ExpiresIn=expires_s)

    async def presign_get(self, bucket: str, key: str, expires_s: int = 900) -> str:
        async with _client() as c:
            return await c.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_s)

    def public_url(self, bucket: str, key: str) -> str | None:
        if settings.public_media_base_url and bucket == settings.s3_bucket_media:
            return f"{settings.public_media_base_url.rstrip('/')}/{key}"
        return None


storage = S3Storage()


async def ensure_buckets() -> None:
    async with _client() as c:
        existing = {b["Name"] for b in (await c.list_buckets()).get("Buckets", [])}
        for b in BUCKETS:
            if b in existing:
                continue
            try:
                await c.create_bucket(Bucket=b)
                log.info("storage.bucket_created", bucket=b)
            except Exception as e:  # SeaweedFS/MinIO: BucketAlreadyOwnedByYou / BucketAlreadyExists are fine
                if "BucketAlready" not in str(e):
                    raise
