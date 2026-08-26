#!/usr/bin/env bash
# 一键构建并部署整个 AWS 栈（SAM），并把前端 build 产物传到 S3 静态托管。
# 会话重置后可重复运行以完整重建。
set -euo pipefail
cd "$(dirname "$0")/.."

# 若 .env 存在则加载凭证
if [ -f .env ]; then set -a; source .env; set +a; fi

export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "==> [1/4] 构建前端 (Vite)"
( cd frontend && npm install && npm run build )

STACK=SAM_BUCKET_PLACEHOLDER  # 见下面 TODO
S3_WEBSITE_BUCKET=$(aws cloudformation describe-stacks --stack-name PacificBioArchive --query "Stacks[0].Outputs[?OutputKey=='WebBucket'].OutputValue" --output text 2>/dev/null || true)

echo "==> [2/4] SAM 构建与部署"
sam build --build-dir .aws-sam/build -t aws/template.yaml
sam deploy \
  --stack-name PacificBioArchive \
  --capabilities CAPABILITY_IAM \
  --s3-bucket "$(aws cloudformation describe-stacks --stack-name PacificBioArchive --query 'Stacks[0].Outputs[?OutputKey==`DeployBucket`].OutputValue' --output text 2>/dev/null || echo "pba-deploy-bucket")" \
  --no-fail-on-empty-changeset

echo "==> [3/4] 上传前端静态站点"
WEB_BUCKET=$(aws cloudformation describe-stacks --stack-name PacificBioArchive --query "Stacks[0].Outputs[?OutputKey=='WebBucket'].OutputValue" --output text)
aws s3 sync frontend/dist "s3://$WEB_BUCKET" --delete

echo "==> [4/4] 输出端点"
aws cloudformation describe-stacks --stack-name PacificBioArchive \
  --query "Stacks[0].Outputs" --output table

echo "✅ AWS 部署完成。打开上面的 WebSiteURL 即可使用。"
echo "   然后跑 ./scripts/deploy-aliyun.sh 部署阿里云读路径。"

# TODO(实现期): 替换 SAM_BUCKET_PLACEHOLDER 为 部署前先 create-bucket 的引导 bucket，
# 首个部署用一次性 bucket 名，后续复用同一个。