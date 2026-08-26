# 环境配置指南

> 目标：一次性把 4 个成员的本地 + 云端环境全部搞定，以后不再反复问。每人按此照做一遍。

## 1. 本机工具（`scripts/setup-local.sh` 一键）

```bash
brew install poppler awscli aws-sam-cli ffmpeg node@20 python@3.12
npm install -g @serverless-devs/s
python3.12 -m venv .venv && .venv/bin/pip install \
  megadetector onnx2torch opencv-python-headless pillow boto3 oss2
```

验证：`aws --version`、`sam --version`、`s --version`、`python3.12 --version`、`ffmpeg -version`。

Node 若仍指向旧版：`export PATH="/opt/homebrew/opt/node@20/bin:$PATH"`（装完把这一行加进 `~/.zshrc`）。

## 2. 凭证文件 `.env`（仓库根，已 gitignore）

```
ALIBABA_CLOUD_ACCESS_KEY_ID=...
ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=          # Learner Lab 每会话临时凭证，按需
AWS_DEFAULT_REGION=us-east-1
```

## 3. 账号级准备

### AWS（Learner Lab 或自有账号）
- 团队选 **1 个环境**作为部署目标（用谁的额度先说清楚）。
- 本机已配置好 **root 密钥**（账号 `987040391588`，`us-east-1`，经 `aws sts get-caller-identity` 验证）。部署走 SAM，全部 IaC 可重建。
- 若改用 Learner Lab：每次 Start Lab 后取临时 AK/SK + Session Token，重新 `source .env` 即可（会话结束资源被删，重跑 deploy 脚本重建）。

### 阿里云（1 个团队账号即可）
- 注册 + 实名认证；控制台开通 **函数计算 FC(3.0)** 与 **OSS**。
- 建 RAM 用户（只授 FC + OSS 权限）→ 拿 AccessKey 填进 `.env`。
- Serverless Devs 已配置 profile（`s config add -a default`），验证通过（AccountID `125*******073`）。

### GitHub
- 建私有仓库 `pacific-bioarchive`，邀请 4 名成员 + 教学团队。
- 每人在机器上 `git config user.name/email`，配 SSH 或 PAT。**每天至少 commit**。

### 测试邮箱
- 1–2 个固定邮箱，用于 Cognito 验证邮件（50 封/天配额）与 SNS 订阅确认。反复用同一个。

## 4. 校验凭证

```bash
aws sts get-caller-identity   # 应返回账号与 arn
s config get -a default       # 应显示 Alibaba Cloud profile
```

> 安全提醒：项目结束后删除此 root access key，或轮换为受限 IAM 用户密钥。