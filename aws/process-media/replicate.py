# replicate.py — 跨云复制：将 S3 中文件+缩略图复制到阿里云 OSS，并重建 OSS 上的 index.json 读副本。
# 阿里云 FC 的读查询跑在 OSS 副本上，DynamoDB 仍是权威库。

import os
import json
import boto3
from decimal import Decimal

s3 = boto3.client("s3")
OU_ENDPOINT = os.environ["OSS_ENDPOINT"]
OU_BUCKET = os.environ["OSS_BUCKET"]
OU_AK = os.environ["OSS_ACCESS_KEY_ID"]
OU_SK = os.environ["OSS_ACCESS_KEY_SECRET"]
FILES_TABLE = os.environ["FILES_TABLE"]

_oss = None
_dynamo = None


def _oss_client():
    global _oss
    if _oss is None:
        import oss2
        auth = oss2.Auth(OU_AK, OU_SK)
        _oss = oss2.Bucket(auth, OU_ENDPOINT, OU_BUCKET)
    return _oss


def _upload_bytes(key: str, data: bytes, content_type="application/octet-stream"):
    bucket = _oss_client()
    bucket.put_object(key, data, headers={"Content-Type": content_type})


def replicate_to_oss(result: dict, source_path: str, thumbnail_path: str):
    """复制原文件和缩略图到 OSS，然后刷新查询索引。"""
    bucket = _oss_client()
    with open(source_path, "rb") as source:
        bucket.put_object(
            result["oss_key"],
            source,
            headers={"Content-Type": result.get("content_type", "application/octet-stream")},
        )
    with open(thumbnail_path, "rb") as thumbnail:
        bucket.put_object(
            result["thumbnail_oss_key"],
            thumbnail,
            headers={"Content-Type": "image/jpeg"},
        )
def rebuild_index():
    """从 DynamoDB 权威表分页重建 OSS index.json。"""
    files_tbl = _dynamo_table()
    items = []
    request = {}
    while True:
        page = files_tbl.scan(**request)
        items.extend(page.get("Items", []))
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key

    index = [
        {
            "checksum": item["checksum"],
            "file_type": item.get("file_type"),
            "tags": item.get("tags", {}),
            "oss_key": item.get("oss_key"),
            "thumbnail_oss_key": item.get("thumbnail_oss_key"),
            "oss_url": item.get("oss_url"),
            "thumbnail_oss_url": item.get("thumbnail_oss_url"),
        }
        for item in items
        if item.get("status") == "processed"
    ]
    payload = json.dumps(index, ensure_ascii=False, default=_json_default).encode()
    _upload_bytes("index.json", payload, "application/json")


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _dynamo_table():
    global _dynamo
    if _dynamo is None:
        import boto3 as _b
        _dynamo = _b.resource("dynamodb").Table(FILES_TABLE)
    return _dynamo
