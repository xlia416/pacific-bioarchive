#!/usr/bin/env bash
# 上传模型到 S3 + 写 models/pointer.json（模型版本化）。
# 换模型只改指针不改代码。模型文件需放在 ./models/ 下（mdv5a.pt / model.pt）。
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f ../.env ] && { set -a; source ../.env; set +a; }
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

BUCKET="$(aws cloudformation describe-stacks --stack-name PacificBioArchive \
  --query "Stacks[0].Outputs[?OutputKey=='ModelsBucket']||Stacks[0].Outputs[?OutputKey=='ModelsBucket'].OutputValue" --output text 2>/dev/null || true)"
[ -z "$BUCKET" ] && { echo "未找到 ModelsBucket（先 sam deploy）。"; exit 1; }

MODEL_DIR="$(dirname "$0")/../models"
echo "==> 上传模型（约 500MB，需几分钟）"
aws s3 cp "$MODEL_DIR/mdv5a.pt" "s3://$BUCKET/models/mdv5a.pt" --only-show-errors
aws s3 cp "$MODEL_DIR/model.pt" "s3://$BUCKET/models/model.pt" --only-show-errors

echo "==> 写 pointer.json（指向当前模型版本）"
cat > /tmp/pointer.json <<'JSON'
{"mdv5a": "mdv5a.pt", "speciesnet": "model.pt"}
JSON
aws s3 cp /tmp/pointer.json "s3://$BUCKET/models/pointer.json"
echo "✅ 模型已上传：s3://$BUCKET/models/{mdv5a.pt, model.pt, pointer.json}"