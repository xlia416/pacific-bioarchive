# fc-query — 阿里云 FC 函数（HTTP 触发器）。读路径：按标签查询 / 按缩略图查原图。
# 跨云认证核心得分点：自行拉取 AWS Cognito JWKS，用 PyJWT 验证 Authorization Bearer token，
# 验证失败返回 401。数据从 OSS 上的 index.json 读副本查询（DynamoDB 为权威库）。

import os
import json
import time
from urllib.parse import unquote, urlparse

import jwt
import requests

COGNITO_REGION = os.environ.get("COGNITO_REGION", "us-east-1")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
CLIENT_ID = os.environ.get("USER_POOL_CLIENT_ID", "")
# OSS 读副本（由 AWS process-media 的 replicate.py 维护）
OSS_BUCKET = os.environ.get("OSS_BUCKET", "")
OSS_ENDPOINT = os.environ.get("OSS_ENDPOINT", "")
OSS_AK = os.environ.get("OSS_ACCESS_KEY_ID", "")
OSS_SK = os.environ.get("OSS_ACCESS_KEY_SECRET", "")

_jwks_cache = None
_jwks_fetched_at = 0
JWKS_TTL = 3600
_oss = None


# ---------- OSS 读副本 ----------
def _oss_bucket():
    global _oss
    if _oss is None:
        import oss2
        _oss = oss2.Bucket(oss2.Auth(OSS_AK, OSS_SK), OSS_ENDPOINT, OSS_BUCKET)
    return _oss


def read_index():
    """读 OSS index.json（读副本）。

    读取失败不能回退为空表，否则权限/网络/格式错误会被伪装成
    “查询无结果”。对短暂 OSS 错误重试后将异常交给 HTTP 层返回 502。
    """
    last_error = None
    for attempt in range(3):
        try:
            data = _oss_bucket().get_object("index.json").read()
            index = json.loads(data)
            if not isinstance(index, list):
                raise ValueError("OSS index must be a JSON array")
            return index
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    raise RuntimeError("OSS index unavailable") from last_error


def _signed_url(key):
    """仅在 JWT 验证后签发短期读 URL；OSS 桶始终保持 private。"""
    return _oss_bucket().sign_url("GET", key, 900, slash_safe=True)


def _canonical_key(value):
    """将带签名 URL、规范 URL 或裸 key 统一为 OSS object key。"""
    if not value:
        return ""
    if "://" not in value:
        return unquote(value).lstrip("/")
    path = unquote(urlparse(value).path).lstrip("/")
    if path.startswith(f"{OSS_BUCKET}/"):
        path = path[len(OSS_BUCKET) + 1:]
    return path


# ---------- JWKS / JWT 验证（跨云） ----------
def _get_jwks():
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache is None or now - _jwks_fetched_at > JWKS_TTL:
        jwks_url = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
        response = requests.get(jwks_url, timeout=30)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_fetched_at = now
    return _jwks_cache


def verify_token(auth_header: str):
    """验证 Bearer JWT。返回 claims dict，失败抛异常。"""
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise PermissionError("missing bearer token")
    token = auth_header.split(" ", 1)[1]
    jwks = _get_jwks()
    # 按 kid 找公钥
    kid = jwt.get_unverified_header(token).get("kid")
    key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
    if not key:
        raise PermissionError("unknown kid")
    pubkey = jwt.algorithms.RSAAlgorithm.from_jwk(key)
    issuer = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}"
    # Cognito access token 使用 client_id claim，通常没有 aud；不能按 ID token 验 aud。
    claims = jwt.decode(
        token,
        key=pubkey,
        algorithms=["RS256"],
        issuer=issuer,
        options={"verify_exp": True, "verify_aud": False},
    )
    if claims.get("token_use") != "access":
        raise PermissionError("token_use must be access")
    if claims.get("client_id") != CLIENT_ID:
        raise PermissionError("client_id mismatch")
    return claims


# ---------- 查询逻辑 ----------
def _matches(item, conditions):
    """AND 逻辑：每条 tag 都需满足 item.tags[tag] >= count。count 可为 null（视为 ≥1）。"""
    tags = item.get("tags", {})
    for name, count in conditions.items():
        got = tags.get(name, 0)
        need = 1 if not count else int(count)
        if got < need:
            return False
    return True


def query_by_tags(conditions):
    index = read_index()
    return [
        {
            "checksum": it.get("checksum"),
            "file_type": it.get("file_type"),
            # 图片返回缩略图 URL，视频返回完整 URL
            "url": _signed_url(
                it.get("thumbnail_oss_key") if it.get("file_type") == "image" else it.get("oss_key")
            ),
            "full_url": _signed_url(it.get("oss_key")),
            "tags": it.get("tags", {}),
        }
        for it in index
        if _matches(it, conditions)
    ]


def query_by_thumbnail(thumb_url):
    requested_key = _canonical_key(thumb_url)
    index = read_index()
    for it in index:
        stored_key = it.get("thumbnail_oss_key") or _canonical_key(it.get("thumbnail_oss_url"))
        if stored_key == requested_key:
            return {
                "checksum": it.get("checksum"),
                "full_url": _signed_url(it.get("oss_key")),
                "file_type": it.get("file_type"),
            }
    return None


# ---------- FC 3.0 built-in runtime handler ----------
def handler(event, context):
    # FC 3.0 内置运行时将 HTTP 请求映射为 event JSON，不再使用 FC 2.0 WSGI 签名。
    try:
        request = json.loads(event) if isinstance(event, (bytes, str)) else event
        request = request or {}
    except (TypeError, ValueError):
        request = {}
    http_context = request.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET")
    path = request.get("rawPath") or http_context.get("path") or "/"
    headers = {str(k).lower(): str(v) for k, v in (request.get("headers") or {}).items()}
    if method == "OPTIONS":
        return _respond(204, {})

    try:
        auth = headers.get("authorization", "")
        claims = verify_token(auth)
    except Exception as e:
        return _respond(401, {"error": f"unauthorized: {e}"})

    # 路由
    if method == "POST" and path.rstrip("/") == "/query/tags":
        try:
            raw = request.get("body") or "{}"
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
        except Exception:
            return _respond(400, {"error": "invalid JSON tag conditions"})
        try:
            results = query_by_tags(body)      # {"tag": count|null, ...}
        except RuntimeError:
            return _respond(502, {"error": "OSS index unavailable"})
        return _respond(200, {"owner": claims.get("sub"), "results": results})

    if method == "GET" and path.startswith("/query/by-thumbnail"):
        thumb = unquote((request.get("queryParameters") or {}).get("url", ""))
        try:
            found = query_by_thumbnail(thumb)
        except RuntimeError:
            return _respond(502, {"error": "OSS index unavailable"})
        if not found:
            return _respond(404, {"error": "not found"})
        return _respond(200, found)

    return _respond(404, {"error": "not found"})


def _respond(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "authorization,content-type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "isBase64Encoded": False,
        "body": "" if status == 204 else json.dumps(payload, ensure_ascii=False),
    }
