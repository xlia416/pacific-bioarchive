# process-media 容器 Lambda 入口
# 事件：S3 ObjectCreated:*（uploads 桶）。处理完写 DynamoDB Files，复制到 OSS，按标签发 SNS。
# 支持两种模式：`process`（S3 事件，正式入库）与 `query`（query-by-file，只用完即删的 temp 前缀）。

import json
import os
import boto3
import traceback
import urllib.parse
from decimal import Decimal

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")  # 可为空：S3 事件里自含 bucket
THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
FILES_TABLE = os.environ["FILES_TABLE"]
QUERY_JOBS_TABLE = os.environ["QUERY_JOBS_TABLE"]
SNS_TOPIC = os.environ["SNS_TOPIC"]

files_tbl = dynamodb.Table(FILES_TABLE)
query_jobs_tbl = dynamodb.Table(QUERY_JOBS_TABLE)

# 惰性加载模型（全局缓存，跨调用复用，冷启动 60-90s）
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pipeline import InferencePipeline
        _pipeline = InferencePipeline()  # 会读 MODELS_BUCKET 的 models/pointer.json 下载模型
    return _pipeline


def _download(bucket, key, local):
    s3.download_file(bucket, key, local)


def _generic_handler(event, context, mode: str):
    records = event.get("Records", [])
    if not records and event.get("key"):
        # query 编排：显式传 bucket（默认取进程内配置）
        records = [{"s3": {"bucket": {"name": event.get("bucket", UPLOADS_BUCKET)}, "object": {"key": event["key"]}}}]

    results = []
    failures = []
    for rec in records:
        bucket = ""
        key = ""
        local = ""
        try:
            bucket = rec["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(rec["s3"]["object"]["key"])
            local = f"/tmp/{key.split('/')[-1]}"
            _download(bucket, key, local)

            pipeline = _get_pipeline()
            if mode == "query":
                result = _process_query(event, pipeline, local, key)
                results.append(result)
            else:
                result = pipeline.process(local, checksum=key.split("/")[1], filename=key.split("/")[-1])

                # 先写入返回 URL/key，OSS 副本成功后才将状态置为 processed。
                files_tbl.update_item(
                    Key={"checksum": key.split("/")[1]},
                    UpdateExpression=(
                        "SET tags = :tags, thumbnail_s3_key = :th, "
                        "oss_key = :ok, thumbnail_oss_key = :tok, "
                        "oss_url = :oss, thumbnail_oss_url = :toss"
                    ),
                    ExpressionAttributeValues={
                        ":tags": result["tags"],
                        ":th": result["thumbnail_s3_key"],
                        ":ok": result["oss_key"],
                        ":tok": result["thumbnail_oss_key"],
                        ":oss": result["oss_url"],
                        ":toss": result["thumbnail_oss_url"],
                    },
                )

                # 复制原文件+缩略图到 OSS，并刷新 index.json。
                from replicate import rebuild_index, replicate_to_oss
                replicate_to_oss(
                    result,
                    source_path=local,
                    thumbnail_path=result["_thumbnail_path"],
                )

                files_tbl.update_item(
                    Key={"checksum": result["checksum"]},
                    UpdateExpression="SET #st = :st",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={":st": "processed"},
                )
                rebuild_index()

                # 按物种发 SNS（MessageAttributes.tag 过滤）
                _publish_sns(result)
                result.pop("_thumbnail_path", None)
                results.append(result)
        except Exception as exc:
            traceback.print_exc()
            failures.append(str(exc))
            _record_failure(event, mode, key, exc)
        finally:
            if mode == "query" and bucket and key:
                try:
                    s3.delete_object(Bucket=bucket, Key=key)
                except Exception:
                    traceback.print_exc()
            if local and os.path.exists(local):
                try:
                    os.remove(local)
                except OSError:
                    pass
    if failures and mode != "query":
        raise RuntimeError("; ".join(failures))
    return {"statusCode": 200, "body": json.dumps(results, default=_json_default)}


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _process_query(event, pipeline, local: str, key: str) -> dict:
    job_id = event["job_id"]
    tags = pipeline.detect_file(local)
    matches = []
    request = {}
    while True:
        page = files_tbl.scan(**request)
        for item in page.get("Items", []):
            item_tags = item.get("tags", {})
            if item.get("status") == "processed" and all(int(item_tags.get(tag, 0)) >= 1 for tag in tags):
                matches.append({
                    "checksum": item.get("checksum"),
                    "file_type": item.get("file_type"),
                    "url": item.get("thumbnail_oss_url") if item.get("file_type") == "image" else item.get("oss_url"),
                    "full_url": item.get("oss_url"),
                    "tags": item_tags,
                })
        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key

    query_jobs_tbl.update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET #st = :st, tags = :tags, matches = :matches",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":st": "completed", ":tags": tags, ":matches": matches},
    )
    return {"job_id": job_id, "key": key, "tags": tags, "matches": matches}


def _record_failure(event, mode: str, key: str, exc: Exception):
    try:
        if mode == "query" and event.get("job_id"):
            query_jobs_tbl.update_item(
                Key={"job_id": event["job_id"]},
                UpdateExpression="SET #st = :st, #err = :err",
                ExpressionAttributeNames={"#st": "status", "#err": "error"},
                ExpressionAttributeValues={":st": "failed", ":err": str(exc)[:1000]},
            )
        elif key.startswith("uploads/") and len(key.split("/")) >= 3:
            files_tbl.update_item(
                Key={"checksum": key.split("/")[1]},
                UpdateExpression="SET #st = :st, #err = :err",
                ExpressionAttributeNames={"#st": "status", "#err": "error"},
                ExpressionAttributeValues={":st": "failed", ":err": str(exc)[:1000]},
            )
    except Exception:
        traceback.print_exc()


def _publish_sns(result: dict):
    for species, count in result.get("tags", {}).items():
        sns.publish(
            TopicArn=SNS_TOPIC,
            Message=json.dumps({"file": result.get("oss_url"), "species": species, "count": count}),
            MessageAttributes={
                "tag": {"DataType": "String", "StringValue": species},
            },
        )


def _maintenance(event):
    """OSS 删除/索引维护不需要加载 470MB ML 模型。"""
    from replicate import delete_oss_objects, rebuild_index

    action = event.get("action")
    if action == "delete_objects":
        deleted = delete_oss_objects(event.get("keys", []))
        return {"statusCode": 200, "body": json.dumps({"deleted": deleted})}
    if action == "rebuild_index":
        rebuild_index()
        return {"statusCode": 200, "body": json.dumps({"rebuilt": True})}
    return {"statusCode": 400, "body": json.dumps({"error": "unknown maintenance action"})}


def lambda_handler(event, context):
    # S3 事件自带属性；编排传入 {"mode": "query"}
    mode = (event.get("mode") or "process")
    if mode == "maintenance":
        return _maintenance(event)
    return _generic_handler(event, context, mode)
