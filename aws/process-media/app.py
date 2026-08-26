# process-media 容器 Lambda 入口
# 事件：S3 ObjectCreated:*（uploads 桶）。处理完写 DynamoDB Files，复制到 OSS，按标签发 SNS。
# 支持两种模式：`process`（S3 事件，正式入库）与 `query`（query-by-file，只用完即删的 temp 前缀）。

import json
import os
import boto3
import traceback

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")  # 可为空：S3 事件里自含 bucket
THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
FILES_TABLE = os.environ["FILES_TABLE"]
SNS_TOPIC = os.environ["SNS_TOPIC"]

files_tbl = dynamodb.Table(FILES_TABLE)

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
    for rec in records:
        try:
            bucket = rec["s3"]["bucket"]["name"]
            key = rec["s3"]["object"]["key"]
            local = f"/tmp/{key.split('/')[-1]}"
            _download(bucket, key, local)

            pipeline = _get_pipeline()
            if mode == "query":
                tags = pipeline.detect(local)   # 仅检测，返回 {species:count}，不写库
                results.append({"key": key, "tags": tags})
            else:
                result = pipeline.process(local, checksum=key.split("/")[1], filename=key.split("/")[-1])
                results.append(result)

                # 写 DynamoDB（tags: M {species:count}）
                files_tbl.update_item(
                    Key={"checksum": key.split("/")[1]},
                    UpdateExpression=(
                        "SET #st = :st, tags = :tags, thumbnail_s3_key = :th, "
                        "oss_url = :oss, thumbnail_oss_url = :toss"
                    ),
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={
                        ":st": "processed",
                        ":tags": result["tags"],
                        ":th": result["thumbnail_s3_key"],
                        ":oss": result["oss_url"],
                        ":toss": result["thumbnail_oss_url"],
                    },
                )

                # 复制到 OSS（多云读副本）——replicate.py
                from replicate import replicate_to_oss
                replicate_to_oss(result)

                # 按物种发 SNS（MessageAttributes.tag 过滤）
                _publish_sns(result)
        except Exception:
            traceback.print_exc()
            try:
                files_tbl.update_item(
                    Key={"checksum": key.split("/")[1]},
                    UpdateExpression="SET #st = :st",
                    ExpressionAttributeNames={"#st": "status"},
                    ExpressionAttributeValues={":st": "failed"},
                )
            except Exception:
                pass
    return {"statusCode": 200, "body": json.dumps(results)}


def _publish_sns(result: dict):
    for species, count in result.get("tags", {}).items():
        sns.publish(
            TopicArn=SNS_TOPIC,
            Message=json.dumps({"file": result.get("oss_url"), "species": species, "count": count}),
            MessageAttributes={
                "tag": {"DataType": "String", "StringValue": species},
            },
        )


def lambda_handler(event, context):
    # S3 事件自带属性；编排传入 {"mode": "query"}
    mode = (event.get("mode") or "process")
    return _generic_handler(event, context, mode)