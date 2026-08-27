# Google 外部账号配置

应用端、Cognito 条件资源、CloudFront HTTPS callback、PKCE 和 OAuth state 校验均已实现。当前只缺 Google Cloud 创建的 OAuth 2.0 Web Client 凭证。

## 1. Google Cloud Console

在 Google Auth Platform 中配置 consent screen，并创建 **Web application** 类型 OAuth client。

Authorized redirect URI 必须填写：

```text
https://pba-987040391588.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

如控制台要求 Authorized JavaScript origin，填写：

```text
https://pba-987040391588.auth.us-east-1.amazoncognito.com
```

若应用仍处于 Testing 状态，把演示用 Google 账号加入 Test users；否则该账号无法完成授权。

## 2. 仅写入本地 `.env`

```bash
GOOGLE_OAUTH_CLIENT_ID='Google 控制台生成的 Client ID'
GOOGLE_OAUTH_CLIENT_SECRET='Google 控制台生成的 Client secret'
```

`.env` 已被 Git 忽略，禁止把 secret 写入 template、前端 `config.js` 或 Git。

## 3. 激活并发布

```bash
./scripts/deploy-aws.sh
./scripts/deploy-frontend.sh
```

部署脚本会把凭证作为 CloudFormation 的 `NoEcho` 参数传入，创建 Cognito Google IdP，并让运行时配置显示 Google 登录按钮。前端永远不会收到 Google client secret。

## 4. 验收

1. 打开 <https://df3cv9pa7eg7p.cloudfront.net/signin>，点击“使用 Google 登录”。
2. Google 授权后应回到 `/auth/callback`，再进入媒体控制台。
3. 使用该 access token 调用 AWS API 和阿里云 FC，均应成功。
4. 在 Cognito 用户列表确认存在形如 `Google_...` 的联邦用户记录。

CloudFormation 输出 `GoogleIdPEnabled=true` 才表示云端 IdP 已启用；未提供两项凭证时它为 `false`，前端会安全隐藏 Google 按钮。
