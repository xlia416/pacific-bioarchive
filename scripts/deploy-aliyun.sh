#!/usr/bin/env bash
# 一键部署阿里云侧（FC 函数 + OSS 副本桶）。用 Serverless Devs。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; source .env; set +a; fi

echo "==> 确保 Serverless Devs 已配置 Alibaba profile"
s config get -a default >/dev/null 2>&1 || \
  s config add \
    --AccessKeyID "${ALIBABA_CLOUD_ACCESS_KEY_ID:?set in .env}" \
    --AccessKeySecret "${ALIBABA_CLOUD_ACCESS_KEY_SECRET:?set in .env}" \
    -a default

echo "==> 从 AWS SAM 输出取 Cognito 参数并注入 s.yaml"
POOL_ID=$(aws cloudformation describe-stacks --stack-name PacificBioArchive --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text 2>/dev/null || echo "PLACEHOLDER")
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name PacificBioArchive --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text 2>/dev/null || echo "PLACEHOLDER")
# 就地替换 s.yaml 里的占位符（用临时文件避免改源）
sed "s/your-pool-id/$POOL_ID/g; s/your-client-id/$CLIENT_ID/g" aliyun/s.yaml > /tmp/s.render.yaml

echo "==> s deploy 部署函数 + OSS（用渲染后的配置）"
s deploy -t /tmp/s.render.yaml

echo "✅ 阿里云部署完成。函数 HTTP 触发 URL 见 s.deploy 输出（s.yaml 中 customDomain/触发器）。"