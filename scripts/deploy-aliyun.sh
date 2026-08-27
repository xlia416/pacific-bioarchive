#!/usr/bin/env bash
# 一键部署阿里云侧（FC 函数 + OSS 副本桶）。用 Serverless Devs。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; source .env; set +a; fi
: "${ALIBABA_CLOUD_ACCESS_KEY_ID:?set in .env}"
: "${ALIBABA_CLOUD_ACCESS_KEY_SECRET:?set in .env}"
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export COGNITO_REGION="$AWS_REGION"
export OSS_BUCKET="${OSS_BUCKET:-pba-oss-copy}"
export OSS_ENDPOINT="${OSS_ENDPOINT:-oss-cn-hangzhou.aliyuncs.com}"

echo "==> 确保 Serverless Devs 已配置 Alibaba profile"
s config get -a default >/dev/null 2>&1 || \
  s config add \
    --AccessKeyID "${ALIBABA_CLOUD_ACCESS_KEY_ID:?set in .env}" \
    --AccessKeySecret "${ALIBABA_CLOUD_ACCESS_KEY_SECRET:?set in .env}" \
    -a default

echo "==> 从 AWS pba Outputs 导出 Cognito 参数"
export USER_POOL_ID="$(aws cloudformation describe-stacks --stack-name pba \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)"
export USER_POOL_CLIENT_ID="$(aws cloudformation describe-stacks --stack-name pba \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text)"
[ -n "$USER_POOL_ID" ] && [ -n "$USER_POOL_CLIENT_ID" ] || {
  echo "pba 栈缺少 Cognito Outputs"; exit 1;
}

echo "==> 确保 OSS 副本桶存在且为 private"
if ! aliyun oss stat "oss://${OSS_BUCKET}" --region cn-hangzhou >/dev/null 2>&1; then
  aliyun oss mb "oss://${OSS_BUCKET}" --region cn-hangzhou --acl private
fi
aliyun oss set-acl "oss://${OSS_BUCKET}" private --bucket --force --region cn-hangzhou >/dev/null

echo "==> 构建 Python 依赖并部署 FC 3.0"
s fc_query build -t aliyun/s.yaml \
  --custom-args="-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com"
s deploy -t aliyun/s.yaml -y

echo "==> 部署信息"
s info -t aliyun/s.yaml
echo "✅ 阿里云部署完成。函数 HTTP 触发 URL 见上方 triggers 输出。"
