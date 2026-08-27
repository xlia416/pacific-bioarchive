# api-handler — AWS zip Lambda（HTTP API 后端）
# 处理：presign/去重、文件状态查询、批量标签、删除、query-by-file 编排、SNS 订阅、列表。
# 读路径查询（by-tags / by-thumbnail）由阿里云 FC 负责（见 aliyun/fc-query）。

import json
import os
import base64
import time
import urllib.parse
import uuid
from decimal import Decimal
from email.parser import BytesParser
from email.policy import default as email_policy
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
lambda_client = boto3.client("lambda")

FILES_TABLE = os.environ["FILES_TABLE"]
UPLOADS_BUCKET = os.environ["UPLOADS_BUCKET"]
THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
QUERY_BUCKET = os.environ["QUERY_BUCKET"]
PROCESS_FUNCTION_NAME = os.environ["PROCESS_FUNCTION_NAME"]
QUERY_JOBS_TABLE = os.environ["QUERY_JOBS_TABLE"]
SNS_TOPIC = os.environ["SNS_TOPIC"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

files = dynamodb.Table(FILES_TABLE)
query_jobs = dynamodb.Table(QUERY_JOBS_TABLE)

# ---- 工具 ----

def _json(body, status=200):
    return {"statusCode": status, "headers": _cors(), "body": json.dumps(body, default=_json_default)}


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")

def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "content-type,authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }

def _owner(event):
    """从 JWT 授权器注入的 context 取 sub（主张调）。"""
    claims = (event.get("requestContext", {}).get("authorizer", {}) or {}).get("jwt", {})
    return claims.get("claims", {}).get("sub")


def _headers(event):
    return {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}


def _body_bytes(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode() if isinstance(body, str) else bytes(body)


def _query_upload(event):
    """取出 query-by-file 的文件。支持 multipart/form-data，也支持原始二进制 body + x-filename。"""
    headers = _headers(event)
    content_type = headers.get("content-type", "application/octet-stream")
    body = _body_bytes(event)
    if not body:
        raise ValueError("query file body is empty")

    if content_type.lower().startswith("multipart/form-data"):
        envelope = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
            + body
        )
        message = BytesParser(policy=email_policy).parsebytes(envelope)
        for part in message.iter_parts():
            filename = part.get_filename()
            if filename:
                return os.path.basename(filename), part.get_content_type(), part.get_payload(decode=True)
        raise ValueError("multipart request has no file part")

    filename = os.path.basename(headers.get("x-filename", "query-upload.bin"))
    return filename, content_type.split(";", 1)[0], body

def _checksum_from_reference(value: str):
    """从 OSS/S3 规范 URL、签名 URL 或 object key 提取 uploads|thumbs/<checksum>/...。"""
    if not value:
        return None
    path = urllib.parse.unquote(urllib.parse.urlparse(value).path if "://" in value else value)
    parts = [part for part in path.strip("/").split("/") if part]
    for prefix in ("uploads", "thumbs"):
        if prefix in parts:
            index = parts.index(prefix)
            return parts[index + 1] if len(parts) > index + 1 else None
    # 也允许前端直接传 checksum。
    return parts[0] if len(parts) == 1 else None


def _invoke_maintenance(action, **payload):
    response = lambda_client.invoke(
        FunctionName=PROCESS_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({"mode": "maintenance", "action": action, **payload}).encode(),
    )
    raw = response.get("Payload").read() if response.get("Payload") else b"{}"
    result = json.loads(raw or b"{}")
    if response.get("FunctionError") or int(result.get("statusCode", 200)) >= 400:
        raise RuntimeError(f"media maintenance failed: {result}")
    return result

# ---- 端点 ----

def handler_presign(event, ctx):
    body = json.loads(event.get("body") or "{}")
    filename = body.get("filename")
    checksum = body.get("checksum")
    content_type = body.get("contentType", "application/octet-stream")
    if not filename or not checksum:
        return _json({"error": "filename & checksum required"}, 400)

    # 去重：条件写 records —— 已存在则 409 + 已有 URL
    record = {
        "checksum": checksum,
        "file_id": checksum,
        "filename": filename,
        "file_type": "video" if filename.lower().split(".")[-1] in ("mp4", "mov", "avi", "mkv", "webm") else "image",
        "s3_key": f"uploads/{checksum}/{filename}",
        "thumbnail_s3_key": "",  # process-media 填充
        "oss_url": "",           # 复制到 OSS 后填充（稳定 URL，供规范往返输入）
        "thumbnail_oss_url": "",
        "tags": {},              # M: {species: count}
        "owner": _owner(event),
        "status": "pending",
        "created_at": int(time.time()),
    }
    try:
        files.put_item(
            Item=record,
            ConditionExpression="attribute_not_exists(checksum)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            existing = files.get_item(Key={"checksum": checksum}).get("Item", {})
            return _json({"duplicate": True, "existing_url": existing.get("oss_url"), "status": existing.get("status")}, 409)
        raise

    # 预签名 PUT（仅新记录，直传 S3）
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": UPLOADS_BUCKET, "Key": record["s3_key"], "ContentType": content_type},
        ExpiresIn=900,
    )
    return _json({"upload_url": upload_url, "file_id": checksum})

def handler_get_file(event, ctx):
    checksum = event["pathParameters"]["checksum"]
    item = files.get_item(Key={"checksum": checksum}).get("Item")
    if not item:
        return _json({"error": "not found"}, 404)
    return _json(item)

def handler_list_files(event, ctx):
    # Gallery：扫描（作业规模足够）。生产应为 GSI。返回条目（公开 URL 字段）。
    scan = files.scan()
    return _json(scan.get("Items", []))

def handler_bulk_tags(event, ctx):
    body = json.loads(event.get("body") or "{}")
    urls = body.get("urls", [])       # 稳定 OSS URL（或 key）
    tags = body.get("tags", [])       # 物种名列表
    operation = int(body.get("operation", 1))  # 1=add, 0=remove
    updated = 0
    ignored = 0
    for url in urls:
        checksum = _checksum_from_reference(url)
        if not checksum:
            continue
        item = files.get_item(Key={"checksum": checksum}).get("Item")
        if not item:
            continue
        current = dict(item.get("tags", {}))
        for t in tags:
            if operation == 1:
                current[t] = current.get(t, 0) + 1
            else:
                if t in current:  # 删除不存在的 → 忽略
                    if current[t] <= 1:
                        del current[t]
                    else:
                        current[t] -= 1
                else:
                    ignored += 1
        files.update_item(
            Key={"checksum": checksum},
            UpdateExpression="SET tags = :tags",
            ExpressionAttributeValues={":tags": current},
        )
        updated += 1
    if updated:
        _invoke_maintenance("rebuild_index")
    return _json({"updated": updated, "ignored": ignored})

def handler_delete_files(event, ctx):
    body = json.loads(event.get("body") or "{}")
    urls = body.get("urls", [])
    deleted = 0
    for url in urls:
        checksum = _checksum_from_reference(url)
        if not checksum:
            continue
        item = files.get_item(Key={"checksum": checksum}).get("Item")
        if not item:
            continue
        # 先删 OSS；失败时保留权威库记录，便于安全重试。
        _invoke_maintenance(
            "delete_objects",
            keys=[item.get("oss_key"), item.get("thumbnail_oss_key")],
        )
        if item.get("s3_key"):
            s3.delete_object(Bucket=UPLOADS_BUCKET, Key=item["s3_key"])
        if item.get("thumbnail_s3_key"):
            s3.delete_object(Bucket=THUMBS_BUCKET, Key=item["thumbnail_s3_key"])
        files.delete_item(Key={"checksum": checksum})
        deleted += 1
    if deleted:
        _invoke_maintenance("rebuild_index")
    return _json({"deleted": deleted})

def handler_subscribe(event, ctx):
    body = json.loads(event.get("body") or "{}")
    email = body.get("email")
    tags = body.get("tags", [])
    if not email:
        return _json({"error": "email required"}, 400)
    tags = sorted({str(tag).strip() for tag in tags if str(tag).strip()})
    if not tags:
        return _json({"error": "at least one tag required"}, 400)
    sub = sns.subscribe(
        TopicArn=SNS_TOPIC,
        Protocol="email",
        Endpoint=email,
        Attributes={"FilterPolicy": json.dumps({"tag": tags})},
        ReturnSubscriptionArn=True,
    )
    return _json({"subscription_arn": sub.get("SubscriptionArn"), "watch_tags": tags})

def handler_query_file(event, ctx):
    """把查询文件放入无入库触发的 QueryBucket，再异步调用容器 Lambda。"""
    filename, content_type, payload = _query_upload(event)
    if len(payload) > 9 * 1024 * 1024:
        return _json({"error": "query file exceeds 9 MB API limit"}, 413)

    job_id = uuid.uuid4().hex
    key = f"query/{job_id}/{filename}"
    owner = _owner(event)
    ttl = int(time.time()) + 3600
    query_jobs.put_item(Item={
        "job_id": job_id,
        "owner": owner,
        "status": "pending",
        "query_key": key,
        "created_at": int(time.time()),
        "ttl": ttl,
    })
    try:
        s3.put_object(Bucket=QUERY_BUCKET, Key=key, Body=payload, ContentType=content_type)
        response = lambda_client.invoke(
            FunctionName=PROCESS_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({
                "mode": "query",
                "job_id": job_id,
                "owner": owner,
                "bucket": QUERY_BUCKET,
                "key": key,
            }).encode(),
        )
        if response.get("StatusCode") != 202:
            raise RuntimeError(f"query worker returned {response.get('StatusCode')}")
    except Exception as exc:
        s3.delete_object(Bucket=QUERY_BUCKET, Key=key)
        query_jobs.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #st = :st, #err = :err",
            ExpressionAttributeNames={"#st": "status", "#err": "error"},
            ExpressionAttributeValues={":st": "failed", ":err": str(exc)[:1000]},
        )
        raise
    return _json({"job_id": job_id, "status": "pending"}, 202)

def handler_get_query_job(event, ctx):
    job_id = event["pathParameters"]["job_id"]
    item = query_jobs.get_item(Key={"job_id": job_id}).get("Item")
    if not item or item.get("owner") != _owner(event):
        return _json({"error": "not found"}, 404)
    return _json(item)

# ---- 路由 ----

ROUTES = {
    "POST /upload/presign": handler_presign,
    "GET /files/{checksum}": handler_get_file,
    "GET /files": handler_list_files,
    "POST /tags/bulk": handler_bulk_tags,
    "POST /files/delete": handler_delete_files,
    "POST /notifications/subscribe": handler_subscribe,
    "POST /query/file": handler_query_file,
    "GET /query/jobs/{job_id}": handler_get_query_job,
}

def lambda_handler(event, context):
    try:
        if event.get("routeKey") == "$default" and event.get("httpMethod") and event.get("path"):
            # format-2.0 express 路由 fallback
            method = event["httpMethod"]
            path = event["path"]
        else:
            route_key = event.get("routeKey", "")
            method, path = route_key.split(" ", 1) if " " in route_key else ("GET", "/")

        handler = ROUTES.get(f"{method} {path}") or ROUTES.get(f"{method} {path.split('/')[-1]}")
        if not handler:
            # 尝试带参路径匹配
            for key, fn in ROUTES.items():
                km, kp = key.split(" ", 1)
                if km == method and "{" in kp:
                    # 简化匹配：按段数
                    k_segs, p_segs = kp.strip("/").split("/"), path.strip("/").split("/")
                    if len(k_segs) == len(p_segs):
                        handler = fn
                        event.setdefault("pathParameters", {})
                        for ks, ps in zip(k_segs, p_segs):
                            if ks.startswith("{"):
                                event["pathParameters"][ks.strip("{}")] = urllib.parse.unquote(ps)
                        break
            if not handler:
                return _json({"error": "not found"}, 404)
        return handler(event, context)
    except Exception as e:
        return _json({"error": str(e)}, 500)
