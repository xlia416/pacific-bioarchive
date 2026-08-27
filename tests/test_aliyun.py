import importlib.util
import json
import os
import pathlib
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.update(
    {
        "COGNITO_REGION": "us-east-1",
        "USER_POOL_ID": "pool-1",
        "USER_POOL_CLIENT_ID": "client-1",
        "OSS_BUCKET": "private-bucket",
        "OSS_ENDPOINT": "oss.example.com",
        "OSS_ACCESS_KEY_ID": "test",
        "OSS_ACCESS_KEY_SECRET": "test",
    }
)


stub_jwt = types.ModuleType("jwt")
stub_jwt.algorithms = types.SimpleNamespace(
    RSAAlgorithm=types.SimpleNamespace(from_jwk=lambda key: "public-key")
)
stub_jwt.get_unverified_header = lambda token: {"kid": "key-1"}
stub_jwt.decode = lambda *args, **kwargs: {
    "sub": "user-1",
    "token_use": "access",
    "client_id": "client-1",
}
stub_requests = types.ModuleType("requests")
sys.modules["jwt"] = stub_jwt
sys.modules["requests"] = stub_requests
spec = importlib.util.spec_from_file_location(
    "pba_aliyun_query", ROOT / "aliyun/fc-query/index.py"
)
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)
sys.modules.pop("jwt", None)
sys.modules.pop("requests", None)


class FakeOss:
    def sign_url(self, method, key, expires, slash_safe=False):
        return f"https://private-bucket.oss.example.com/{key}?signed=yes"


class AliyunQueryTests(unittest.TestCase):
    def setUp(self):
        fc._oss = FakeOss()
        fc._jwks_cache = {"keys": [{"kid": "key-1", "kty": "RSA"}]}
        fc._jwks_fetched_at = 10**20
        fc.jwt.decode = lambda *args, **kwargs: {
            "sub": "user-1",
            "token_use": "access",
            "client_id": "client-1",
        }

    def test_access_token_contract(self):
        claims = fc.verify_token("Bearer token")
        self.assertEqual(claims["sub"], "user-1")

        fc.jwt.decode = lambda *args, **kwargs: {
            "token_use": "id",
            "client_id": "client-1",
        }
        with self.assertRaisesRegex(PermissionError, "token_use"):
            fc.verify_token("Bearer token")

    def test_index_read_failure_is_not_silently_empty(self):
        class BrokenOss:
            def get_object(self, key):
                raise ConnectionError("unavailable")

        old_oss = fc._oss
        old_sleep = fc.time.sleep
        try:
            fc._oss = BrokenOss()
            fc.time.sleep = lambda _seconds: None
            with self.assertRaisesRegex(RuntimeError, "OSS index unavailable"):
                fc.read_index()
        finally:
            fc._oss = old_oss
            fc.time.sleep = old_sleep

    def test_query_returns_signed_private_urls(self):
        fc.read_index = lambda: [
            {
                "checksum": "abc",
                "file_type": "image",
                "tags": {"dingo": 2, "cat": 1},
                "oss_key": "uploads/abc/photo.jpg",
                "thumbnail_oss_key": "thumbs/abc/thumb.jpg",
            }
        ]
        result = fc.query_by_tags({"dingo": 2, "cat": None})
        self.assertEqual(len(result), 1)
        self.assertIn("?signed=yes", result[0]["url"])
        self.assertIn("uploads/abc/photo.jpg", result[0]["full_url"])

    def test_fc3_http_handler_and_cors(self):
        fc.verify_token = lambda header: {"sub": "user-1"}
        original_query = fc.query_by_tags
        fc.query_by_tags = lambda body: [{"conditions": body}]
        event = {
            "rawPath": "/query/tags",
            "headers": {"Authorization": "Bearer token"},
            "body": json.dumps({"dingo": 1}),
            "requestContext": {"http": {"method": "POST", "path": "/query/tags"}},
        }
        try:
            response = fc.handler(json.dumps(event).encode(), None)
            self.assertEqual(response["statusCode"], 200)
            self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")
            self.assertEqual(json.loads(response["body"])["owner"], "user-1")
        finally:
            fc.query_by_tags = original_query


if __name__ == "__main__":
    unittest.main()
