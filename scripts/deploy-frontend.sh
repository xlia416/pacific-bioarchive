#!/usr/bin/env bash
# Build the React application with CloudFormation outputs and publish it behind CloudFront.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] && { set -a; source .env; set +a; }
export AWS_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
STACK="${STACK_NAME:-pba}"

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

API_URL="$(output ApiUrl)"
WEB_URL="$(output WebUrl)"
WEB_BUCKET="$(output WebBucket)"
USER_POOL_ID="$(output UserPoolId)"
CLIENT_ID="$(output UserPoolClientId)"
COGNITO_DOMAIN="$(output CognitoDomain)"
GOOGLE_IDP_ENABLED="$(output GoogleIdPEnabled)"
DISTRIBUTION_ID="$(output CloudFrontDistributionId)"
ALIYUN_URL="${ALIYUN_QUERY_URL:-https://pba-query-iseukvgnef.cn-hangzhou.fcapp.run}"

npm --prefix frontend run build
CONFIG_JSON="$(jq -nc \
  --arg api "$API_URL" \
  --arg aliyun "$ALIYUN_URL" \
  --arg pool "$USER_POOL_ID" \
  --arg client "$CLIENT_ID" \
  --arg region "$AWS_REGION" \
  --arg domain "$COGNITO_DOMAIN" \
  --arg redirect "$WEB_URL/auth/callback" \
  --argjson google "$GOOGLE_IDP_ENABLED" \
  '{API_BASE:$api,ALIYUN_QUERY_BASE:$aliyun,USER_POOL_ID:$pool,USER_POOL_CLIENT_ID:$client,REGION:$region,COGNITO_DOMAIN:$domain,OAUTH_REDIRECT_URI:$redirect,GOOGLE_IDP_ENABLED:$google}')"
printf 'window.__PBA__ = %s;\n' "$CONFIG_JSON" > frontend/dist/config.js

aws s3 sync frontend/dist "s3://${WEB_BUCKET}" --delete --only-show-errors
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths '/*' \
  --query '{Id:Invalidation.Id,Status:Invalidation.Status}' --output json

echo "Frontend deployed: ${WEB_URL}"
