"""封装 S3 兼容知识文件对象存储。"""

from pathlib import Path
from typing import BinaryIO

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]

from app.config import Settings


class S3ObjectStorage:
    """只暴露知识服务需要的最小 S3 操作。"""

    def __init__(self, settings: Settings) -> None:
        if (
            settings.object_storage_access_key is None
            or settings.object_storage_secret_key is None
        ):
            raise ValueError("对象存储凭据尚未配置")
        self._bucket = settings.object_storage_bucket
        self._sse = settings.object_storage_sse
        self._client: BaseClient = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url,
            region_name=settings.object_storage_region,
            aws_access_key_id=(settings.object_storage_access_key.get_secret_value()),
            aws_secret_access_key=(
                settings.object_storage_secret_key.get_secret_value()
            ),
            use_ssl=settings.object_storage_secure,
        )

    def upload(
        self, source: BinaryIO, object_key: str, content_type: str | None
    ) -> None:
        """流式上传文件，不把内容整体读入内存。"""
        extra_args: dict[str, str] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if self._sse != "none":
            extra_args["ServerSideEncryption"] = self._sse
        self._client.upload_fileobj(
            source,
            self._bucket,
            object_key,
            ExtraArgs=extra_args or None,
        )

    def download(self, object_key: str, destination: Path) -> None:
        """下载对象到后台任务的临时文件。"""
        with destination.open("wb") as output:
            self._client.download_fileobj(self._bucket, object_key, output)

    def delete(self, object_key: str) -> None:
        """删除一个源文件对象。"""
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def ping(self) -> None:
        """验证私有知识 Bucket 已经存在且当前凭据可访问。"""
        self._client.head_bucket(Bucket=self._bucket)
