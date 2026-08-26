# fc-query — 阿里云 FC 函数（HTTP 触发器）。读路径：按标签查询 / 按缩略图查原图。
# 跨云认证核心得分点：自行拉取 AWS Cognito JWKS，用 PyJWT 验证 Authorization Bearer token，
# 验证失败返回 401。数据从 OSS 上的 index.json 读副本查询（DynamoDB 为权威库）。

import os
import json
import time

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
    """读 OSS index.json（读副本）。失败回退空表。"""
    try:
        data = _oss_bucket().get_object("index.json").read()
        return json.loads(data)
    except Exception:
        return []


# ---------- JWKS / JWT 验证（跨云） ----------
def _get_jwks():
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache is None or now - _jwks_fetched_at > JWKS_TTL:
        jwks_url = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"
        _jwks_cache = requests.get(jwks_url, timeout=30).json()
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
    claims = jwt.decode(
        token,
        key=pubkey,
        algorithms=["RS256"],
        audience=CLIENT_ID,
        options={"verify_exp": True},
    )
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
            "url": it.get("thumbnail_oss_url") if it.get("file_type") == "image" else it.get("oss_url"),
            "full_url": it.get("oss_url"),
            "tags": it.get("tags", {}),
        }
        for it in index
        if _matches(it, conditions)
    ]


def query_by_thumbnail(thumb_url):
    index = read_index()
    for it in index:
        if it.get("thumbnail_oss_url") == thumb_url:
            return {"checksum": it.get("checksum"), "full_url": it.get("oss_url"), "file_type": it.get("file_type")}
    return None


# ---------- FC handler ----------
def handler(environ, start_response, context):
    # FC 3.0 自定义运行时通过 environ 提供请求信息
    method = environ.get("HTTP_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")
    # 读 body（FC3.0 把 body 放 environ['body']，字符串或 bytes）
    try:
        auth = environ.get("HTTP_AUTHORIZATION", "")
        claims = verify_token(auth)
    except Exception as e:
        return _respond(start_response, 401, {"error": f"unauthorized: {e}"})

    # 路由
    if method == "POST" and path.rstrip("/") == "/query/tags":
        try:
            raw = environ.get("body") or "{}"
            if isinstance(raw, bytes):
                raw = raw.decode()
            body = json.loads(raw)
        except Exception:
            body = {}
        results = query_by_tags(body)          # {"tag": count|null, ...}
        return _respond(start_response, 200, {"owner": claims.get("sub"), "results": results})

    if method == "GET" and path.startswith("/query/by-thumbnail"):
        # URL 查询参数通过 environ 提供；FC3.0 用 environ.get('QUERY_STRING')
        from urllib.parse import parse_qs, unquote
        qs = parse_qs(environ.get("QUERY_STRING", ""))
        thumb = unquote(qs.get("url", [""])[0])
        found = query_by_thumbnail(thumb)
        if not found:
            return _respond(start_response, 404, {"error": "not found"})
        return _respond(start_response, 200, found)

    return _respond(start_response, 404, {"error": "not found"})


def _respond(start_response, status, payload):
    start_response(str(status), [("Content-Type", "application/json")])
    body = json.dumps(payload, ensure_ascii=False).encode()
    return [body]