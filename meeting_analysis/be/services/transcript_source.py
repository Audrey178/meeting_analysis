"""Đọc transcript từ ``source.transcript_uri`` khi request không gửi kèm ``items``.

Chỉ hỗ trợ ``s3://bucket/key`` (boto3; MinIO/S3 tương thích: đặt ``AWS_ENDPOINT_URL``, thông tin đăng
nhập theo biến môi trường chuẩn của AWS). Nội dung là JSON cùng dạng transcript gửi trực tiếp
(object có ``items``, hoặc mảng các item).
"""

from __future__ import annotations

import json
from urllib.parse import urlparse


class TranscriptSourceError(RuntimeError):
    """Không đọc được kho lưu transcript (mạng, quyền, dịch vụ lỗi); router trả 502."""


def _read_s3(uri: str) -> bytes:
    """Nội dung object ``s3://bucket/key``.

    Lỗi: ValueError nếu URI sai hoặc object không tồn tại; TranscriptSourceError nếu kho lỗi.
    """

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    parsed = urlparse(uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"transcript_uri phải có dạng s3://bucket/key: {uri}")
    try:
        return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "NoSuchBucket", "404"):
            raise ValueError(f"không tìm thấy transcript: {uri}") from exc
        raise TranscriptSourceError(f"không đọc được transcript {uri}: {exc}") from exc
    except BotoCoreError as exc:
        raise TranscriptSourceError(f"không đọc được transcript {uri}: {exc}") from exc


def with_transcript_items(payload: dict) -> dict:
    """``payload`` có ``items``: giữ nguyên; không có thì lấy ``items`` (và ``meeting_id`` nếu request
    không có) từ ``source.transcript_uri``.

    Đầu vào: payload - ``AnalyzeV3Request.model_dump()``.
    Đầu ra: payload có ``items``.
    Lỗi: ValueError (router trả 422) nếu thiếu cả ``items`` lẫn URI, URI không hỗ trợ/không tồn tại,
        hoặc nội dung không phải transcript; TranscriptSourceError (502) nếu kho lưu lỗi.
    """

    if payload.get("items") is not None:
        return payload
    uri = (payload.get("source") or {}).get("transcript_uri")
    if not uri:
        raise ValueError("request phải có items hoặc source.transcript_uri")
    if urlparse(uri).scheme != "s3":
        raise ValueError(f"transcript_uri chỉ hỗ trợ s3://: {uri}")
    try:
        transcript = json.loads(_read_s3(uri))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"transcript tại {uri} không phải JSON: {exc}") from exc
    if isinstance(transcript, list):
        transcript = {"items": transcript}
    if not isinstance(transcript, dict) or not isinstance(transcript.get("items"), list):
        raise ValueError(f"transcript tại {uri} không có mảng items")
    return {
        **payload,
        "items": transcript["items"],
        "meeting_id": payload.get("meeting_id") or transcript.get("meeting_id"),
    }


__all__ = ["TranscriptSourceError", "with_transcript_items"]
