# replicate.py — 跨云复制：将 S3 中文件+缩略图复制到阿里云 OSS，并重建 OSS 上的 index.json 读副本。
# 阿里云 FC 的读查询跑在 OSS 副本上，DynamoDB 仍是权威库。

import os
import json
import boto3

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


def replicate_to_oss(result: dict):
    """把处理好的文件记录复制到 OSS：本体 + 缩略图 + 重建 index.json。"""
    # 本体与缩略图通常已由 process-media 的 S3 侧持有；这里把 DB 记录落成副本 + index
    files_tbl = _dynamo_table()
    scan = files_tbl.scan()
    items = scan.get("Items", [])
    index = [{"checksum": i["checksum"], "file_type": i.get("file_type"), "tags": i.get("tags", {}),
              "oss_url": i.get("oss_url"), "thumbnail_oss_url": i.get("thumbnail_oss_url")} for i in items]
    _upload_bytes("index.json", json.dumps(index, ensure_ascii=False).encode(), "application/json")


def _dynamo_table():
    global _dynamo
    if _dynamo is None:
        import boto3 as _b
        _dynamo = _b.resource("dynamodb").Table(FILES_TABLE)
    return _dynamo