# Pacific BioArchive

多云 serverless 野生动物媒体平台 —— FIT5225 2026 S2 Assignment 2（组，占分 40%）。

- **AWS**（Cognito 认证 / S3 存储 / Lambda 处理 / DynamoDB / SNS 通知）+ **阿里云**（FC 函数计算 / OSS 静态查询副本）
- 上传图片/视频 → 自动 ML 识别物种打标签 + 生成缩略图 + 去重 → 写库 → REST API / UI 查询、批量标签、删除、按标签邮件通知

## 目录结构

```
pacific-bioarchive/
├── frontend/            # React 18 + Vite + TypeScript
├── aws/                 # SAM 项目（template.yaml + Lambda×2 + ECR 容器）
├── aliyun/              # Serverless Devs（s.yaml + fc-query）
├── docs/                # 架构图、用户指南、报告
└── scripts/             # setup-local.sh / deploy-aws.sh / deploy-aliyun.sh / smoke-test.sh
```

## 首次准备（每人一次）

```bash
./scripts/setup-local.sh        # 装本机工具 + Python venv
```

账号级准备（AWS Learner Lab / 阿里云、RAM 用户、GitHub 私有仓库）见 [docs/env-setup.md](docs/env-setup.md)。

## 一键部署

```bash
./scripts/deploy-aws.sh         # Cognito + API 网关 + Lambda×2 + S3×3 + DynamoDB×2 + SNS，并把前端传到 S3 静态托管
./scripts/deploy-aliyun.sh      # fc-query 函数 + OSS 副本桶
```

部署后浏览器打开 AWS 静态站 URL 即使用。会话重置后重跑两个脚本即可完整重建。

## 分工（详见 PLAN.md）

- A：前端 + 认证（React / Cognito / 路由守卫）
- B：ML 流水线（容器 Lambda / 缩略图 / 视频）
- C：AWS 后端（SAM / API 端点 / 去重 / 批量标签 / 删除）
- D：阿里云 + 集成 + 交付物（跨云 JWT 验证 / OSS 复制 / SNS / 报告）

## 说明

- 完整架构与实现决策见 `PLAN.md`（仓库根上有副本）。
- **凭证只放 `.env`，已 gitignore，绝不提交。**