# Pacific BioArchive 实现计划（FIT5225 A2，40%）

## Context

作业要求构建多云 serverless 野生动物媒体平台：用户上传图片/视频 → 云存储 → 自动触发 serverless 函数用 ML 模型识别物种打标签、生成缩略图、去重、写入高可用数据库 → REST API 支持多种标签查询、批量标签增删、文件删除、基于标签的邮件通知（SNS）→ React Web UI。截止 2026-08-30，当前日期 2026-08-27。

**已确认决策**：
- 双云：**AWS（Learner Lab，Cognito 必须）+ 阿里云**（0 台服务器：FC 函数计算 + OSS 对象存储，全 serverless）
- 前端：React + Vite + TypeScript
- 部署：AWS 用 **SAM**，阿里云用 **Serverless Devs（s.yaml）**（Learner Lab 会话结束资源被删，全部必须 IaC 可重建）
- 评分权重：核心功能 50 分 > UI 20 分 > 报告/演示 20 分 > 认证 10 分 → 按此排优先级。
- **外部账号登录是必须完成项**：Rubric 3.4 独立占 5 分，不再作为可裁剪的加分项。

## 架构总览

```
React SPA (CloudFront HTTPS + private S3 origin)
   │
   ├─本地账号/Google─> Cognito User Pool + Hosted UI/Domain
   ├──access token──> AWS API Gateway(HTTP API + Cognito JWT authorizer)
   │                    └─> api-handler (zip Lambda): presign/标签增删/删除/订阅/query-job
   └──access token──> 阿里云 FC 3.0 (HTTP trigger): fc-query
                ├─ 自行验证 Cognito JWT（拉 JWKS，PyJWT 验签）← 跨云认证核心得分点
                ├─ 读 private OSS 上的 index.json 副本做查询
                └─ 认证成功后返回短期 OSS 签名 URL
S3 uploads/ ──ObjectCreated(prefix=uploads/)──> process-media (容器 Lambda, 3008MB/900s, /tmp 4096MB)
                ├─ OpenCV 缩略图（保宽高比、压缩）
                ├─ 视频用 ffmpeg 抽 1帧/秒 再逐帧检测
                ├─ MegaDetector(mdv5a.pt) → 裁剪 → SpeciesNet(model.pt) → 标签+计数
                ├─ 写 DynamoDB Files 表
                ├─ 复制文件+缩略图到阿里云 OSS + 重建 index.json（多云复制得分点）
                └─ SNS 按标签发布通知（MessageAttributes tag 过滤）
模型版本化：S3 models/pointer.json 指向模型文件，Lambda 冷启动读指针下载 → 换模型只改指针不改代码
S3 query/ (独立 QueryBucket，无 ObjectCreated 入库触发) ──显式 invoke mode=query──> process-media
                └─ 写 QueryJobsTable，finally 删除查询文件
```

**关键设计决策**：
- AWS 管写路径（上传/ML/变更），阿里云 FC 管读路径（查询）→ 真实的跨云 JWT 验证演示。
- Learner Lab 只有 LabRole、不能建 IAM 用户 → 阿里云无法持 AWS 密钥读 DynamoDB。方案：每次入库、标签修改和删除后，把 Files 表 Scan 成 `index.json` 推到 OSS 作为**读副本**（几十条数据毫秒级），DynamoDB 仍是权威库。
- 查询用 Scan + 代码内过滤/交集（作业规模足够正确），报告里说明生产方案应为倒排索引表。
- 去重：前端 WebCrypto 算 SHA-256 → presign 时 `PutItem` 带 `attribute_not_exists(checksum)` 条件写 → 冲突返回 409 + 已有 URL。
- 去重恢复：`pending` 记录带 TTL/上传截止时间；预签名 PUT 失败或超时后允许原用户重试，避免校验和永久占位。
- JWT 契约：前端只发 Cognito access token；阿里云验证 RS256、`iss`、`exp`、`client_id == app client id`和 `token_use == access`。

## 环境配置清单（现在一次性搞好，后续不再问）

### 本机已具备
git 2.51 ✅ · Node 18.20 + npm 10 ✅（升级到 20 LTS）· Docker 29 ✅ · Homebrew ✅

### 本机需安装（`scripts/setup-local.sh` 一键执行，4 人每人跑一次）
```bash
brew install poppler awscli aws-sam-cli ffmpeg node@20 python@3.12   # ffmpeg 供本地视频测试，python3.12 供本地跑流水线
npm install -g @serverless-devs/s                        # 阿里云 Serverless Devs CLI
python3.12 -m venv .venv && .venv/bin/pip install megadetector onnx2torch opencv-python-headless pillow boto3 oss2
```
安装后验证：`aws --version`、`sam --version`、`ffmpeg -version`、`s --version`、`python3.12 --version`。

### 账号级准备（人工步骤，各自完成）
| 事项 | 说明 | 谁做 |
|---|---|---|
| AWS Learner Lab | Moodle 进入 Vocareum，点 Start Lab 拿临时 AK/SK + session token，`aws configure` 写入（注意：会话结束凭证失效，每次重新粘贴） | 全员各自有一个 lab；**选定 1 个作为团队部署环境**（用谁的 $50 额度） |
| 阿里云账号 | 注册 + 实名认证（个人）；控制台开通 函数计算 FC3.0 和 OSS；建 RAM 用户（只授 FC+OSS 权限）拿 AccessKey | 1 个团队账号即可；每人建自己的 RAM 子账号便于分别部署 |
| Serverless Devs 配置 | `s config add` 选 Alibaba Cloud，填 RAM 用户的 AK/SK | 会部署阿里云的人（D 为主） |
| GitHub 私有仓库 | `pacific-bioarchive` 私有库；邀请 4 名成员 + 教学团队；每人配好 `git config user.name/email` + PAT/SSH | 全员 |
| 测试邮箱 | 1–2 个固定邮箱用于 Cognito 验证邮件（50 封/天配额）和 SNS 订阅确认 | 任意 |
| Google OAuth（必须） | Google Cloud Console 建 OAuth Web Client，配置 Cognito User Pool IdP、Domain、Hosted UI 和 HTTPS callback；确认外部账号在 Cognito 留有记录 | A |

### 项目脚手架（我来生成）
monorepo 目录（frontend/ aws/ aliyun/ docs/ scripts/）、`.gitignore`、`frontend/`（Vite+React+TS 初始化）、`aws/`（SAM init）、`aliyun/`（s.yaml 骨架）、`README.md`（每人如何跑 setup-local.sh + 各自部署命令）、`docs/env-setup.md`（记录上面的账号步骤，组员照抄）。

## 云部署形态（明确回答"部署到哪"）

代码在本地编写，通过分阶段脚本发布到云端，之后用户只用浏览器访问云端 URL：
- `./scripts/deploy-aws.sh` 只负责 AWS 基础设施：Cognito、API Gateway、Lambda×2、S3×5（uploads/thumbs/models/query/web）、DynamoDB×2、SNS、CloudFront。ECR repository/镜像由独立脚本以 `linux/amd64` 单 manifest 构建和推送，不声称由 SAM 重建镜像。
- `./scripts/deploy-aliyun.sh` 幂等创建 private OSS 副本桶，再用 `s build/deploy` 创建 fc-query FC3 函数和 HTTP 触发器。
- `./scripts/deploy-frontend.sh` 在 AWS 和阿里云都已输出 URL 后，生成运行时 `config.js`，再 build/sync 到 WebBucket 并通过 CloudFront HTTPS 访问。
- 本地不保留任何常驻服务；Learner Lab 会话重置后按“ECR → AWS → 模型 → 阿里云 → 前端”顺序重建。

## 仓库结构

```
pacific-bioarchive/
├── frontend/            # React 18 + Vite + TS
│   └── src/{auth,pages,components,api}/
├── aws/                 # SAM 项目
│   ├── template.yaml    # Cognito/CloudFront、S3×5、DynamoDB×2、HTTP API+JWT、Lambda×2、SNS
│   ├── api-handler/     # zip Lambda (Python 3.12)
│   ├── process-media/   # 容器 Lambda：Dockerfile, app.py, pipeline.py, media.py, replicate.py
│   └── scripts/upload-models.sh
├── aliyun/              # Serverless Devs 项目
│   ├── s.yaml
│   └── fc-query/index.py  # JWT 验证 + 查询逻辑
├── docs/                # 架构图（官方图标）、user guide、team report
└── scripts/             # deploy-aws.sh / deploy-aliyun.sh / smoke-test.sh
```

## 数据模型（DynamoDB，PAY_PER_REQUEST）

**Files 表**：PK `checksum`(SHA-256)；属性 `file_id, file_type(image|video), s3_key, thumbnail_s3_key, oss_url, thumbnail_oss_url, tags(M: {物种: 计数}), owner(Cognito sub), status(pending→processing→processed|failed), created_at`。

**URL 形态定案（对应评分表 2.1.3）**：
- DB 保存稳定规范标识：`oss_key`/`thumbnail_oss_key` 与不带签名查询串的规范 URL。
- OSS 副本桶保持 private。阿里云 FC 验证 JWT 后才生成短期签名 URL；图片查询返回缩略图签名 URL，视频返回完整媒体签名 URL。
- `by-thumbnail`、批量标签和删除对 URL 做规范化：去掉 query string，解析稳定 object key 后完成往返。
- AWS S3 桶保持私有，仅 presigned PUT 上传 + Lambda 内部处理。

**QueryJobs 表**：PK `job_id`，TTL=now+1h（按文件查询的结果临时存放，查询文件绝不永久存储）。

## API 设计

**AWS API Gateway**（每条路由挂 JWT authorizer，CORS 允许 localhost:5173 和 CloudFront 正式域名）：
| 方法+路径 | 请求 | 响应 |
|---|---|---|
| POST /upload/presign | {filename, checksum, content_type} | 200 {upload_url, file_id} / **409 重复+已有URL** |
| GET /files/{checksum} | — | 状态+标签+URL（前端轮询） |
| POST /query/file | multipart 文件 | 202 {job_id}（存独立 QueryBucket，显式异步调 process-media mode=query，用完即删） |
| GET /query/jobs/{job_id} | — | 检测到的标签+匹配文件 URL 列表 |
| POST /tags/bulk | {urls, tags, operation: 1\|0} | {updated, ignored}（删除不存在的标签→忽略） |
| POST /files/delete | {urls} | 删 S3+OSS+缩略图+DB 条目+重建索引 |
| POST /notifications/subscribe | {email, tags} | SNS 订阅（FilterPolicy 按 tag） |
| GET /files | — | Gallery 列表 |

**阿里云 FC**（代码内验 Cognito JWT，失败 401）：
| POST /query/tags | {"tags": {"wombat":2,"magpie":1}} 或 {"dingo": null}（无计数=≥1） | 结果列表：图片返回缩略图 URL，视频返回完整 URL |
| GET /query/by-thumbnail?url=... | 缩略图 URL | 对应原图完整 URL |

SNS 发布：process-media 对每个不同物种发一条消息，`MessageAttributes={"tag": 物种}`。正文包含物种、数量、文件名和 7 天有效的 HTTPS OSS 签名媒体 URL；收件人无需 Cognito 账号，OSS 仍保持 private。订阅创建时必须真实设置 `FilterPolicy`，并在邮箱确认后完成一次指定标签通知验收。

## ML 流水线（移植 batch.py）

1. 冷启动：用 boto3 `s3.get_object` 从 private ModelsBucket 读 `models/pointer.json` → 用 S3 SDK 下载 mdv5a.pt + model.pt 到 4096MB `/tmp` → 加载进全局变量。禁止使用公开 HTTPS URL 读 pointer。
2. 图片：OpenCV 生成缩略图（最长边 300px 保宽高比、JPEG q=70）→ MegaDetector 检测（conf≥0.05）→ 裁剪 bbox（相对坐标转像素）→ resize 600×600 BILINEAR → transform `Resize((480,480))+ToTensor` → `permute(0,2,3,1)` NHWC → model.pt → softmax → 46 类 argmax（classes 列表从 batch.py:148 原样复制）。`torch.load(..., weights_only=False)` 保持原样调用。
3. 视频：`ffmpeg -i in -vf fps=1 /tmp/frames/%04d.jpg` → 逐帧跑 2 → 计数跨帧累加；缩略图取第 0 帧。
4. 容器 Dockerfile：`public.ecr.aws/lambda/python:3.12` + ffmpeg + CPU 版 torch/torchvision + megadetector、onnx2torch、opencv-python-headless、boto3、oss2、pillow、numpy。镜像用 `docker buildx --platform linux/amd64 --provenance=false --sbom=false --load` 构建，推送后必须是单一 manifest，不能是带 attestation 的 OCI index。

## 前端页面

- 路由守卫 AuthGuard：无会话 → 重定向 /signup（作业要求未登录只能看注册页）。
- 认证：amazon-cognito-identity-js 完成 signUp(email, given_name, family_name, password)、confirmSignUp、signIn、signOut；`NEW_PASSWORD_REQUIRED` 必须真正调用 `completeNewPasswordChallenge`。
- 外部账号（必须）：Google OAuth 通过 Cognito Hosted UI/Domain 登录，HTTPS callback 回到 CloudFront SPA，前端换取会话并验证 Cognito 中有联邦用户记录。
- UploadPanel：拖拽 → SHA-256 → presign → PUT（必须携带与签名一致的 `Content-Type`）→ 轮询状态 → 409 显示去重提示。
- Gallery：缩略图网格（OSS URL），点开大图/视频播放，多选 → BulkTagEditor（批量加/删标签）、DeleteDialog。
- QueryPanel：动态 (物种, 最小计数) 行 → POST 阿里云 /query/tags → 结果缩略图预览 → 点击取全图。
- QueryByFile：选文件 → job 轮询 → 显示检测标签+匹配文件。
- NotificationsPanel：邮箱+标签订阅。

## 实施顺序（4 条并行轨道，4 人分工，各约 25%）

最终分工表（以本表为准）：
| 成员 | 建议负责内容 | 主要交付物 | 建议贡献 |
|---|---|---|--:|
| A：认证与云基础设施 | Cognito、JWT Authorizer、IAM、SAM、部署脚本、认证页面 | 注册/验证/登录/退出、路由保护、跨云 token 方案、`template.yaml` | 25% |
| B：上传与 ML 处理 | 去重、S3 触发、缩略图、视频 1 帧/秒、ML 识别、模型版本化 | `process-media`、模型加载、图片/视频处理、Upload UI | 25% |
| C：数据管理与通知 | DynamoDB、批量标签、删除、SNS 订阅、文件列表 | Files 表、bulk tag API、delete API、notification API、Gallery 管理 UI | 25% |
| D：查询与多云集成 | 阿里云 FC/OSS、JWT 验证、索引副本、全部查询功能、集成测试 | 标签查询、缩略图查询、文件查询、Query UI、`smoke-test.sh` | 25% |

对应评分点：A=认证10+Infra/IAM，B=文件处理20，C=数据管理10+部分查询，D=查询20+跨云认证+报告。

### Git 提交规范（评分硬要求：GitHub 有全员 commit）
- **谁实现就谁提交，commit 归属以 `git log`/`git blame` 记录为准，无需特意标注归属。**
- message 描述清楚做了什么，规范：
  `feat: 批量标签 API` / `fix: pipeline 裁剪 bbox 越界` / `test: smoke-test 跨云 401` / `docs: 写用户指南`
- 前端/后端各模块尽量各自 commit（便于看贡献，也符合分工）。首次搭建脚手架由实际提交人归属，不需单独声明。
- commit 用各自在 GitHub 上配好的 `user.name/email` 提交，记录贡献。
- 同步到 GitHub 用本机 token 身份 push（私有仓库 `pacific-bioarchive`，团队邀请 4 人 + 教学团队）。
- 每天至少一次 push，保证 everyone commits today。

### 当前真实进度（2026-08-27）

| 模块 | 状态 | 验证证据/剩余工作 |
|---|---|---|
| ECR 容器镜像 | ✅ 依赖/视频内存/通知链接修复并重新部署 | 固定 ML 依赖；视频帧在一次 MegaDetector 加载中顺序处理，SpeciesNet 分阶段驻留。当前 digest `sha256:1c056eb6992d…`，Lambda = ECR latest 已验证 |
| AWS SAM 基础栈 | ✅ 完成 | `pba` 在 `us-east-1` 已 `UPDATE_COMPLETE` |
| ProcessMedia Lambda 限制适配 | ✅ 云端实测 | Lab API 硬限 `MemorySize<=3008`；10 秒/10 帧视频冷启动峰值 2802 MB、耗时 126.3 s，`EphemeralStorage=4096`，`Timeout=900` |
| Cognito/API Outputs | ✅ 已取得 | UserPool/Client/API URL 由 CloudFormation Outputs 动态读取，不硬编码进仓库 |
| 模型上传 | ✅ 完成 | ModelsBucket 已有 `mdv5a.pt` (280767041 B)、`model.pt` (211878007 B)、`pointer.json` (45 B)，指针内容已校验 |
| private pointer 读取 | ✅ 云端实测 | `pipeline.py` 使用 `s3.get_object`；首次真实图片处理已从 private ModelsBucket 下载并加载两个模型 |
| QueryBucket/query-by-file | ✅ 云端实测 | 真实查询图识别 `Canis_familiaris:1` 并匹配正式文件；Files 表前后均 3 条，QueryBucket 最终 0 对象，QueryJobs=`completed` |
| 阿里云 FC/OSS | ✅ 已部署 | FC3 `pba-query` + private `pba-oss-copy`；HTTPS URL `https://pba-query-iseukvgnef.cn-hangzhou.fcapp.run`，无/坏 token=401、OPTIONS=204 |
| OSS 复制/索引/查询/删除 | ✅ 云端端到端 | 批量标签增/删/忽略不存在标签已验收；跨云删除后 AWS/OSS 四个对象、DDB 记录、index 与阿里云查询结果均消失；基准图不受影响 |
| 本地单元测试 | ✅ 16 项 | `test_aliyun`×5 + `test_p0`×9（含 OSS 签名 URL 与通知链接，本次容器内 9/9 通过）+ `test_pipeline`×2；全量复跑需带 boto3/Pillow 的 Python 3.12 环境 |
| Git 贡献记录 | 🟡 仓库已建立 | 私有仓库 `xlia416/pacific-bioarchive` 已建立并推送；当前仍为单一作者，Rubric 硬要求其他成员以各自账号认领模块并提交 |
| 前端认证/上传 | ✅ 已部署 | signup/确认/signin/临时密码/guard；预签名 Content-Type、处理轮询、去重和错误提示完整，运行时 config 已注入 |
| CloudFront HTTPS | ✅ 已部署 | private WebBucket + OAC；SPA 403/404 fallback、API CORS、`/auth/callback` 均已线上验证；URL `https://df3cv9pa7eg7p.cloudfront.net` |
| Google 外部账号 | 🟡 已启用，待交互验收 | Google IdP 已创建，App Client providers=`COGNITO,Google`，线上按钮和跳转到 `accounts.google.com` 已验证；待演示账号完成一次授权并确认 Cognito 联邦用户记录 |
| SNS 真实邮件通知 | 🟡 投递/过滤已实测，新链接待点击验收 | QQ 邮箱订阅并确认 `Sus_scrofa` FilterPolicy；上传 `Sus_scrofa_1.JPG` 识别为 `Sus_scrofa:1`，CloudWatch 显示邮件投递 1、失败 0。已部署 7 天 HTTPS OSS 签名链接，收件人无需 Cognito；待下一次匹配上传验收新邮件点击 |
| 视频 1 fps | ✅ 云端端到端 | 10 秒 H.264 抽取/处理 10 帧，`Sus_scrofa:10`；S3/OSS 原视频+缩略图、DDB/index、FC 计数查询和签名 URL 均通过 |
| Gallery/Query/Tag/Delete/Notification UI | ✅ 已部署并验收 | 英文 UI、私有 OSS 签名媒体 Gallery、四种查询、批量标签、跨云删除和 SNS 订阅已发布；雾蓝灰/暖白/海蓝视觉系统、轻量卡片、Media library 顶部 Bulk actions 工具条、独立 Notifications 面板和自动消失成功提示已上线 |
| query-by-file 浏览器 CORS | ✅ 已修复并部署 | API `AllowHeaders` 已加入 `x-filename`；CloudFront origin 的真实 OPTIONS 返回 204，并明确允许 `authorization,content-type,x-filename`（commit `fa260db`） |
| Smoke test | ❌ 待完成 | 当前仅骨架，必须实现下方 11 项可重复测试 |
| 报告/架构图/用户指南 | ❌ 待完成 | 官方云图标、贡献表、私有仓库链接、GenAI 声明 |

### 从当前进度开始的严格执行顺序

1. **上传模型 ✅**：两个 `.pt` 和 `pointer.json` 已上传 ModelsBucket，对象大小与指针内容已校验。
2. **修正运行时 P0 ✅**：private pointer SDK 读取、QueryBucket 隔离、QueryJobs/清理、原图/缩略图 OSS 复制与入库索引已实现；ECR 新镜像已按 digest 固定到 Lambda，SAM 更新成功。
3. **部署阿里云 ✅**：从 `pba` Outputs 注入 Cognito IDs，FC3 按 access-token `client_id/token_use` 验证，OSS 为 private 且查询结果签发短期 URL。
4. **验证 index.json 写入私有 OSS ✅（08-27 12:00 已完成）**：维护模式调用（不加载模型）返回 200 `{"rebuilt": true}`，`pba-oss-copy/index.json` 已落桶（内容 `[]`，Files 表暂无记录，属预期）；跨云复制链路与 RAM 权限已打通。
5. **修复 ML 镜像依赖、视频内存与通知链接 ✅**：禁止 pip 回退到无 `megadetector` namespace 的 5.0.4；解决 ONNX/YOLOv5 protobuf 约束；视频帧批量共用一次 MegaDetector，两模型分阶段驻留；SNS 邮件改用 7 天 OSS 签名链接；SAM 已绑定 `sha256:1c056eb6992d…`。
6. **Git 卫生（仓库/push ✅，多人提交待完成）**：私有 GitHub 仓库已建立并跟踪 `origin/main`；其他 3 位成员需以各自账号认领模块提交。Rubric 硬要求全员 commit。
7. **数据功能、SNS 与视频云端验收 ✅**：真实上传、去重、标签、query-by-file、跨云删除、邮件通知均已通过；10 秒视频按 1 fps 处理 10 帧，3008 MB 限制下峰值 2802 MB并完成跨云查询。
8. **部署完整前端与 CloudFront ✅**：运行时 `config.js` 注入 AWS API、Cognito、阿里云 FC；完整英文 Gallery/Query/Tag/Delete/Notification UI 已发布，上传进度、查询空/错误态、图片失败占位已补齐；缩略图反查由 FC 校验 OSS host/key 并返回新签名 URL；query-by-file 所需 `X-Filename` 已加入 CORS 白名单。最新视觉改版已使用浅色海蓝系统，Bulk actions 置于 Media library 工具条，Notifications 独立展示。
9. **激活外部账号（云端配置 ✅，待交互验收）**：Google OAuth Client 已通过本地 `.env` 安全注入 CloudFormation，Cognito Google IdP、App Client provider、CloudFront callback、PKCE/state 和线上按钮均已验证；最后由演示账号完成一次 Google 授权并确认 Cognito 生成联邦用户。
10. **冒烟测试**：先单图端到端，再执行全部 11 项；任一核心项失败不得标记总体通过。
11. **交付物与演示**：完成报告/架构图/用户指南/个人报告，确保全员 commit，按作业上限准备 3 分钟架构讲解和 15 分钟演示。

## 验证方案（用 30 张测试图，真值=文件名前缀）

1. 流水线准确率 ≥27/30 顶级物种正确（conf 0.05 偏低，个别误报在报告中讨论）。
2. 去重：重传一张 → 409 + S3 对象数不变。
3. 查询 AND+计数：`{"Perameles_nasuta":2}`、`{"Hypsiprymnodon_moschatus":1,"Thylogale_stigmatica":2}` 验证逻辑与。
4. by-thumbnail：结果页取缩略图 URL → 返回同一文件原图 URL。
5. query-by-file：上传查询后断言 Files 表条数不变、QueryBucket 临时对象为空、QueryJobs 已完成。
6. 批量标签：加→删→删不存在的（ignored）。
7. 删除：S3、OSS、DDB、后续查询全消失。
8. 视频：用 ffmpeg 把静帧拼 10s 测试片 → 标签计数≥帧数、可查到视频完整 URL。
9. 通知：订阅 `Sus_scrofa` 过滤 → 上传 Sus_scrofa_1.JPG → 收到确认邮件+通知邮件 → 不登录 Cognito 直接点击 7 天签名 URL 可打开媒体（注意 Cognito 50 封/天、SNS 配额，回收用同一邮箱）。
10. 认证：AWS/阿里云无 token、坏 token、过期 token → 401；有效 access token → 200；Google 外部账号登录成功且 Cognito 有记录。
11. 重建演练：fresh 环境按 ECR → AWS → 模型 → 阿里云 → 前端顺序重建，再重跑冒烟测试。

## 风险与注意

- **Learner Lab 会重置**：所有资源必须进 template.yaml / s.yaml / 脚本，绝不手动建控制台资源。
- **冷启动实测 126.5s**（大型镜像+470MB 模型+torch import）：演示前先传一张小图保温。峰值内存 2852/3008MB，余量小；短视频必须单独实测确认不 OOM。
- **IAM 限制**：只能用 LabRole；报告中说明"细粒度权限"设计（前端零凭证、仅预签名 URL、私有桶+Block Public Access、API 网关 JWT 授权、生产级各函数最小权限策略文档化）。
- **成本**：目标 $50 内花 <$10；process-media 3008MB×实际推理时间，演示数据集分批测试；阿里云使用 FC+OSS。
- **megadetector 依赖树**容易冲突：固定版本、用 headless opencv、本地 `docker run` 先验证镜像再推。
- **deploy-ecr.sh 的 DOCKER_CONFIG 隔离只作用于 `docker login` 和 `docker push`**：buildx 构建必须用用户原配置发现 CLI 插件，否则脚本在构建前中止（已修复并经 11:29 一轮成功推送验证；层缓存命中时增量重建约 1 分钟）。
- **Git 单一作者是评分硬伤**：Rubric 要求全员 commit 记录；任何成员当天必须有 push。
- **报告 AI 声明**：6.2/6.3 节必须提及 GenAI 使用，否则 0 分。

## 剩余关键交付文件

- `aws/template.yaml` — QueryBucket、CloudFront、Cognito Domain/Google IdP 参数与输出
- `aws/process-media/{app.py,pipeline.py,replicate.py}` — private pointer、query mode、真实 OSS 复制/索引
- `aws/api-handler/app.py` — query job、跨云删除、索引刷新、SNS FilterPolicy
- `aliyun/fc-query/index.py` — access-token claims 验证、private OSS 签名 URL
- `frontend/` — Google 登录、运行时 config、Gallery/Query/Tag/Delete/Notification UI
- `scripts/{deploy-ecr.sh,deploy-aws.sh,upload-models.sh,deploy-aliyun.sh,deploy-frontend.sh,smoke-test.sh}`
- `docs/` — 官方图标多云架构图、用户指南、团队报告、个人报告检查清单
