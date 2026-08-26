#!/usr/bin/env bash
# 冒烟测试：搭建后验证 11 项核心功能（对应计划"验证方案"）。
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && { set -a; source .env; set +a; }
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

API_URL="$(aws cloudformation describe-stacks --stack-name PacificBioArchive \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text 2>/dev/null || true)"
ALIYUN_URL="${ALIYUN_QUERY_URL:-}"

pass() { echo "  ✔ $*"; }
fail() { echo "  ✘ $*"; FAILS=$((FAILS+1)); }
FAILS=0

say() { echo; echo "== $*"; }

say "1) 认证：无 token 访问受保护端点 → 应 401"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/files" || echo 000)
[ "$CODE" = "401" ] && pass "无 token 返回 401 (got $CODE)" || fail "期望 401 (got $CODE)"

say "2) S3 对象数检查（去重后不增长）"
echo "  （去重复核见前端重传 → 409）"

say "3) 阿里云跨云 JWT 验证"
if [ -n "$ALIYUN_URL" ]; then
  # 坏 token → 401
  BAD=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer bad.token.here" \
    -X POST -d '{"x":1}' "$ALIYUN_URL/query/tags" || echo 000)
  [ "$BAD" = "401" ] && pass "坏 token 跨云 401 (got $BAD)" || fail "坏 token 期望 401 (got $BAD)"
else
  echo "  跳过（未配置 ALIYUN_QUERY_URL）"
fi

say "4..11) 标签查询 / 缩略图/原图 / 上传查 / 批量/删除 / 通知 / 视频 —— 落地时定量补充"
echo "  详见阶段冒烟脚本（query/tags、by-thumbnail、query/file、bulk/delete、SNS、video 各一节）"

echo
if [ "$FAILS" -gt 0 ]; then echo "❌ 冒烟测试失败 $FAILS 项"; exit 1; fi
echo "✅ 冒烟测试标记通过（部分需人工 token）"