#!/usr/bin/env bash
# 构建 Lambda 可接受的 linux/amd64 单 manifest 镜像并推送 ECR。
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && { set -a; source .env; set +a; }
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REPOSITORY="pba-process-media"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${REPOSITORY}:latest"

# macOS Docker Desktop 的全局 credential helper 在非交互脚本中可能卡住。
# 使用本次运行专用的临时配置，不修改用户的 ~/.docker/config.json。
TASK_DOCKER_CONFIG="$(mktemp -d /tmp/pba-docker-config.XXXXXX)"
cleanup_docker_config() {
  rm -f "$TASK_DOCKER_CONFIG/config.json"
  rmdir "$TASK_DOCKER_CONFIG" 2>/dev/null || true
}
trap cleanup_docker_config EXIT

aws ecr describe-repositories --repository-names "$REPOSITORY" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$REPOSITORY" >/dev/null
aws ecr get-login-password --region "$AWS_REGION" | \
  DOCKER_CONFIG="$TASK_DOCKER_CONFIG" docker login --username AWS --password-stdin "$REGISTRY"

docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --load \
  --tag "$IMAGE_URI" \
  aws/process-media
DOCKER_CONFIG="$TASK_DOCKER_CONFIG" docker push "$IMAGE_URI"

MEDIA_TYPE="$(aws ecr describe-images --repository-name "$REPOSITORY" \
  --image-ids imageTag=latest --query 'imageDetails[0].imageManifestMediaType' --output text)"
case "$MEDIA_TYPE" in
  application/vnd.oci.image.manifest.v1+json|application/vnd.docker.distribution.manifest.v2+json) ;;
  *) echo "不支持的 ECR manifest: $MEDIA_TYPE"; exit 1 ;;
esac
echo "✅ 已推送 $IMAGE_URI ($MEDIA_TYPE)"
