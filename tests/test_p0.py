import importlib.util
import json
import os
import pathlib
import sys
import unittest
from decimal import Decimal


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "FILES_TABLE": "files",
        "QUERY_JOBS_TABLE": "query-jobs",
        "UPLOADS_BUCKET": "uploads",
        "QUERY_BUCKET": "queries",
        "THUMBS_BUCKET": "thumbs",
        "MODELS_BUCKET": "models",
        "PROCESS_FUNCTION_NAME": "process-media",
        "SNS_TOPIC": "topic",
        "OSS_BUCKET": "oss",
        "OSS_ENDPOINT": "oss.example.com",
        "OSS_ACCESS_KEY_ID": "test",
        "OSS_ACCESS_KEY_SECRET": "test",
    }
)


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


api = load_module("pba_api_handler", "aws/api-handler/app.py")
worker = load_module("pba_process_worker", "aws/process-media/app.py")
replicate = load_module("pba_replicate", "aws/process-media/replicate.py")


class FakeS3:
    def __init__(self):
        self.puts = []
        self.deletes = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)


class FakeJobs:
    def __init__(self):
        self.items = {}
        self.updates = []

    def put_item(self, Item):
        self.items[Item["job_id"]] = Item

    def update_item(self, **kwargs):
        self.updates.append(kwargs)

    def get_item(self, Key):
        return {"Item": self.items.get(Key["job_id"])} if Key["job_id"] in self.items else {}


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202 if kwargs.get("InvocationType") == "Event" else 200}


class QueryApiTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.jobs = FakeJobs()
        self.lambda_client = FakeLambda()
        api.s3 = self.s3
        api.query_jobs = self.jobs
        api.lambda_client = self.lambda_client

    def test_raw_query_upload_is_queued(self):
        event = {
            "headers": {"content-type": "image/jpeg", "x-filename": "animal.jpg"},
            "body": "image-bytes",
            "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-1"}}}},
        }
        response = api.handler_query_file(event, None)
        self.assertEqual(response["statusCode"], 202)
        job_id = json.loads(response["body"])["job_id"]
        self.assertEqual(self.jobs.items[job_id]["owner"], "user-1")
        self.assertEqual(self.s3.puts[0]["Bucket"], "queries")
        payload = json.loads(self.lambda_client.calls[0]["Payload"])
        self.assertEqual(payload["mode"], "query")
        self.assertEqual(payload["job_id"], job_id)

    def test_multipart_parser_extracts_file(self):
        boundary = "pba-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="query.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
            "abc123\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        filename, content_type, payload = api._query_upload(
            {"headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"}, "body": body}
        )
        self.assertEqual(filename, "query.jpg")
        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(payload, b"abc123")


class ManageFiles:
    def __init__(self):
        self.item = {
            "checksum": "abc",
            "tags": {"dingo": Decimal(1)},
            "s3_key": "uploads/abc/photo.jpg",
            "thumbnail_s3_key": "thumbs/abc/thumb.jpg",
            "oss_key": "uploads/abc/photo.jpg",
            "thumbnail_oss_key": "thumbs/abc/thumb.jpg",
        }
        self.updates = []
        self.deletes = []

    def get_item(self, Key):
        return {"Item": self.item} if Key["checksum"] == "abc" else {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)

    def delete_item(self, **kwargs):
        self.deletes.append(kwargs)


class DataManagementTests(unittest.TestCase):
    def setUp(self):
        self.files = ManageFiles()
        self.s3 = FakeS3()
        self.worker = FakeLambda()
        api.files = self.files
        api.s3 = self.s3
        api.lambda_client = self.worker

    def test_bulk_tags_parses_signed_oss_url_and_rebuilds_index(self):
        response = api.handler_bulk_tags(
            {
                "body": json.dumps(
                    {
                        "urls": ["https://bucket.oss.example/uploads/abc/photo.jpg?signature=x"],
                        "tags": ["cat"],
                        "operation": 1,
                    }
                )
            },
            None,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.files.updates[0]["ExpressionAttributeValues"][":tags"]["cat"], 1
        )
        maintenance = json.loads(self.worker.calls[-1]["Payload"])
        self.assertEqual(maintenance["action"], "rebuild_index")

    def test_delete_uses_correct_s3_buckets_and_deletes_oss_first(self):
        response = api.handler_delete_files(
            {"body": json.dumps({"urls": ["thumbs/abc/thumb.jpg"]})}, None
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            self.s3.deletes,
            [
                {"Bucket": "uploads", "Key": "uploads/abc/photo.jpg"},
                {"Bucket": "thumbs", "Key": "thumbs/abc/thumb.jpg"},
            ],
        )
        actions = [json.loads(call["Payload"])["action"] for call in self.worker.calls]
        self.assertEqual(actions, ["delete_objects", "rebuild_index"])

    def test_subscription_has_real_filter_policy(self):
        calls = []
        api.sns = type("FakeSns", (), {"subscribe": lambda self, **kwargs: calls.append(kwargs) or {"SubscriptionArn": "pending"}})()
        response = api.handler_subscribe(
            {"body": json.dumps({"email": "person@example.com", "tags": ["dingo", "cat"]})},
            None,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(calls[0]["Attributes"]["FilterPolicy"]), {"tag": ["cat", "dingo"]})


class FakeFiles:
    def scan(self, **kwargs):
        return {
            "Items": [
                {
                    "checksum": "a",
                    "status": "processed",
                    "file_type": "image",
                    "tags": {"dingo": Decimal(2)},
                    "thumbnail_oss_url": "thumb-a",
                    "oss_url": "full-a",
                },
                {
                    "checksum": "b",
                    "status": "processed",
                    "file_type": "image",
                    "tags": {"cat": Decimal(1)},
                },
            ]
        }


class FakePipeline:
    def detect_file(self, local):
        return {"dingo": 1}


class WorkerQueryTests(unittest.TestCase):
    def test_query_worker_matches_all_detected_tags(self):
        jobs = FakeJobs()
        worker.files_tbl = FakeFiles()
        worker.query_jobs_tbl = jobs
        result = worker._process_query(
            {"job_id": "job-1"}, FakePipeline(), "/tmp/query.jpg", "query/job-1/query.jpg"
        )
        self.assertEqual(result["tags"], {"dingo": 1})
        self.assertEqual([item["checksum"] for item in result["matches"]], ["a"])
        self.assertEqual(jobs.updates[0]["ExpressionAttributeValues"][":st"], "completed")


class NotificationTests(unittest.TestCase):
    def test_notification_contains_accessible_temporary_url(self):
        calls = []
        fake_sns = type(
            "FakeSns",
            (),
            {"publish": lambda self, **kwargs: calls.append(kwargs)},
        )()
        old_sns = worker.sns
        old_url = worker._notification_url
        old_ttl = worker.NOTIFICATION_URL_TTL_SECONDS
        try:
            worker.sns = fake_sns
            worker._notification_url = lambda key: f"https://private.example/{key}?Signature=test"
            worker.NOTIFICATION_URL_TTL_SECONDS = 604800
            worker._publish_sns({
                "filename": "animal.jpg",
                "oss_key": "uploads/abc/animal.jpg",
                "tags": {"Sus_scrofa": 2},
            })
        finally:
            worker.sns = old_sns
            worker._notification_url = old_url
            worker.NOTIFICATION_URL_TTL_SECONDS = old_ttl

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["Subject"], "Pacific BioArchive: Sus_scrofa detected")
        self.assertIn("link valid for 7 days", calls[0]["Message"])
        self.assertIn("?Signature=test", calls[0]["Message"])
        self.assertNotIn("oss_url", calls[0]["Message"])
        self.assertEqual(calls[0]["MessageAttributes"]["tag"]["StringValue"], "Sus_scrofa")


class FakeIndexTable:
    def scan(self, **kwargs):
        return {
            "Items": [
                {
                    "checksum": "a",
                    "status": "processed",
                    "file_type": "image",
                    "tags": {"dingo": Decimal(2)},
                    "oss_key": "uploads/a/a.jpg",
                    "thumbnail_oss_key": "thumbs/a/thumb.jpg",
                },
                {"checksum": "pending", "status": "pending", "tags": {}},
            ]
        }


class FakeOss:
    def __init__(self):
        self.objects = {}

    def put_object(self, key, data, headers=None):
        self.objects[key] = data.read() if hasattr(data, "read") else data

    def sign_url(self, method, key, expires, slash_safe=False):
        return f"https://oss.example.com/{key}?expires={expires}"


class ReplicationTests(unittest.TestCase):
    def test_signed_read_url_uses_private_object_key_and_expiry(self):
        fake_oss = FakeOss()
        replicate._oss = fake_oss
        url = replicate.signed_read_url("uploads/a/a.jpg", 604800)
        self.assertEqual(url, "https://oss.example.com/uploads/a/a.jpg?expires=604800")

    def test_index_contains_only_processed_json_safe_records(self):
        fake_oss = FakeOss()
        replicate._dynamo = FakeIndexTable()
        replicate._oss = fake_oss
        replicate.rebuild_index()
        index = json.loads(fake_oss.objects["index.json"])
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["tags"]["dingo"], 2)


if __name__ == "__main__":
    unittest.main()
