#!/usr/bin/env bash
# 构建并部署 AWS 基础设施。前端必须等阿里云 URL 生成后再单独部署。
# 会话重置后可重复运行以完整重建（幂等）。
set -euo pipefail
cd "$(dirname "$0")/.."

# 加载凭证（.env 在仓库根，已被 .gitignore 排除，不入 git）
if [ -f ./.env ]; then set -a; source ./.env; set +a; fi
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

STACK=pba
: "${ALIBABA_CLOUD_ACCESS_KEY_ID:?set ALIBABA_CLOUD_ACCESS_KEY_ID in .env}"
: "${ALIBABA_CLOUD_ACCESS_KEY_SECRET:?set ALIBABA_CLOUD_ACCESS_KEY_SECRET in .env}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
IMAGE_DIGEST="$(aws ecr describe-images --repository-name pba-process-media \
  --image-ids imageTag=latest --query 'imageDetails[0].imageDigest' --output text)"
PROCESS_IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/pba-process-media@${IMAGE_DIGEST}"
PARAMETER_OVERRIDES=(
  "ProcessMediaImageUri=${PROCESS_IMAGE_URI}"
  "AliyunOssAccessKeyId=${ALIBABA_CLOUD_ACCESS_KEY_ID}"
  "AliyunOssAccessKeySecret=${ALIBABA_CLOUD_ACCESS_KEY_SECRET}"
)
if [ -n "${GOOGLE_OAUTH_CLIENT_ID:-}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_SECRET:-}" ]; then
  PARAMETER_OVERRIDES+=(
    "GoogleOAuthClientId=${GOOGLE_OAUTH_CLIENT_ID}"
    "GoogleOAuthClientSecret=${GOOGLE_OAUTH_CLIENT_SECRET}"
  )
fi

echo "==> [1/2] SAM 构建与部署"
sam build --build-dir .aws-sam/build -t aws/template.yaml \
  --parameter-overrides "${PARAMETER_OVERRIDES[@]}"
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name "$STACK" \
  --region "$AWS_REGION" \
  --resolve-s3 \
  --resolve-image-repos \
  --parameter-overrides "${PARAMETER_OVERRIDES[@]}" \
  --capabilities CAPABILITY_IAM \
  --on-failure DELETE \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset

echo "==> [2/2] 输出端点"
aws cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs" --output table

echo "✅ AWS 基础设施部署完成。"
