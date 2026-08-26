# api-handler — AWS zip Lambda（HTTP API 后端）
# 处理：presign/去重、文件状态查询、批量标签、删除、query-by-file 编排、SNS 订阅、列表。
# 读路径查询（by-tags / by-thumbnail）由阿里云 FC 负责（见 aliyun/fc-query）。

import json
import os
import hashlib
import time
import urllib.parse
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
lambda_client = boto3.client("lambda")

FILES_TABLE = os.environ["FILES_TABLE"]
UPLOADS_BUCKET = os.environ["UPLOADS_BUCKET"]
SNS_TOPIC = os.environ["SNS_TOPIC"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

files = dynamodb.Table(FILES_TABLE)

# ---- 工具 ----

def _json(body, status=200):
    return {"statusCode": status, "headers": _cors(), "body": json.dumps(body)}

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

def _parse_key_from_url(url: str, bucket: str) -> str:
    """兼容：OSS URL / S3 URL / 裸 key。返回对象 key。"""
    if not url:
        return None
    if "://" in url:
        parsed = urllib.parse.urlparse(url)
        # path 形如 /<bucket>/<key...>，取 bucket 之后的剩余部分
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) == 2:
            return parts[1]
        return parts[0]
    return url

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
        key = _parse_key_from_url(url, UPLOADS_BUCKET)
        checksum = key.split("/")[1] if key else None
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
    return _json({"updated": updated, "ignored": ignored})

def handler_delete_files(event, ctx):
    body = json.loads(event.get("body") or "{}")
    urls = body.get("urls", [])
    deleted = 0
    for url in urls:
        key = _parse_key_from_url(url, UPLOADS_BUCKET)
        checksum = key.split("/")[1] if key else None
        if not checksum:
            continue
        item = files.get_item(Key={"checksum": checksum}).get("Item")
        if not item:
            continue
        # 删对象（uploads + thumbs）
        for k in (item.get("s3_key"), item.get("thumbnail_s3_key")):
            if k:
                try:
                    s3.delete_object(Bucket=UPLOADS_BUCKET, Key=k)
                except ClientError:
                    pass
        # 删 OSS 副本（交给 process-media/replicate.py 通过跨云 API；此处标记待删键）
        # 记录在案供 replicate 消费：TODO 实现跨云删除
        files.delete_item(Key={"checksum": checksum})
        deleted += 1
    return _json({"deleted": deleted})

def handler_subscribe(event, ctx):
    body = json.loads(event.get("body") or "{}")
    email = body.get("email")
    tags = body.get("tags", [])
    if not email:
        return _json({"error": "email required"}, 400)
    # 为每个 tag 建一个带 FilterPolicy(Attribute=tag, ValuePrefix=spec 例) 的订阅
    # 简化：一个订阅 + FilterPolicy 匹配多个 tag；落地时用 ProtocolAttributes。
    sub = sns.subscribe(
        TopicArn=SNS_TOPIC,
        Protocol="email",
        Endpoint=email,
        ReturnSubscriptionArn=True,
    )
    return _json({"subscription_arn": sub.get("SubscriptionArn"), "watch_tags": tags})

def handler_query_file(event, ctx):
    """按上传文件查询：把 multipart 文件落到 temp/ 前缀，异步调 process-media(mode=query)，结果存 QueryJobs（TTL）。"""
    # 本骨架先返回占位；落地时：读 body → 写 temp/{job_id}.JPG → 触发 container Lambda
    body = event.get("body") or b""
    job_id = hashlib.sha1(body[:4096]).hexdigest()[:16] if body else "pending"
    return _json({"job_id": job_id, "message": "query job accepted (standing up MP multipart handling)"}, 202)

def handler_get_query_job(event, ctx):
    job_id = event["pathParameters"]["job_id"]
    return _json({"job_id": job_id, "tags": {}, "matches": [], "status": "pending"})

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