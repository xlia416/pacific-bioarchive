#!/usr/bin/env bash
# 上传模型到 S3 + 写 models/pointer.json（模型版本化）。
# 换模型只改指针不改代码。MODEL_DIR 可覆盖模型目录。
set -euo pipefail
cd "$(dirname "$0")/../.."

# .env 在仓库根，与 deploy-aws.sh 一致
[ -f ./.env ] && { set -a; source ./.env; set +a; }
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

BUCKET="$(aws cloudformation describe-stacks --stack-name pba \
  --query "Stacks[0].Outputs[?OutputKey=='ModelsBucket'].OutputValue" --output text 2>/dev/null || true)"
[ -z "$BUCKET" ] && { echo "未找到 ModelsBucket（先 sam deploy）。"; exit 1; }

MODEL_DIR="${MODEL_DIR:-../PacificBioArchive}"
[ -f "$MODEL_DIR/mdv5a.pt" ] || { echo "缺少 $MODEL_DIR/mdv5a.pt"; exit 1; }
[ -f "$MODEL_DIR/model.pt" ] || { echo "缺少 $MODEL_DIR/model.pt"; exit 1; }
echo "==> 上传模型（约 500MB，需几分钟）"
aws s3 cp "$MODEL_DIR/mdv5a.pt" "s3://$BUCKET/models/mdv5a.pt" --only-show-errors
aws s3 cp "$MODEL_DIR/model.pt" "s3://$BUCKET/models/model.pt" --only-show-errors

echo "==> 写 pointer.json（指向当前模型版本）"
printf '%s\n' '{"mdv5a":"mdv5a.pt","speciesnet":"model.pt"}' | \
  aws s3 cp - "s3://$BUCKET/models/pointer.json" --content-type application/json
echo "✅ 模型已上传：s3://$BUCKET/models/{mdv5a.pt, model.pt, pointer.json}"
