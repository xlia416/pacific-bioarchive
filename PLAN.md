# Pacific BioArchive 实现计划（FIT5225 A2，40%）

## Context

作业要求构建多云 serverless 野生动物媒体平台：用户上传图片/视频 → 云存储 → 自动触发 serverless 函数用 ML 模型识别物种打标签、生成缩略图、去重、写入高可用数据库 → REST API 支持多种标签查询、批量标签增删、文件删除、基于标签的邮件通知（SNS）→ React Web UI。截止 2026-08-30，今天 08-26，约 4 天，3–4 人小组。

**已确认决策**：
- 双云：**AWS（Learner Lab，Cognito 必须）+ 阿里云**（0 台服务器：FC 函数计算 + OSS 对象存储，全 serverless）
- 前端：React + Vite + TypeScript
- 部署：AWS 用 **SAM**，阿里云用 **Serverless Devs（s.yaml）**（Learner Lab 会话结束资源被删，全部必须 IaC 可重建）
- 评分权重：核心功能 50 分 > UI 20 分 > 报告/演示 20 分 > 认证 10 分 → 按此排优先级

## 架构总览

```
React SPA ──JWT──> AWS API Gateway(HTTP API + Cognito JWT authorizer)
   │                    └─> api-handler (zip Lambda): presign/标签增删/删除/订阅/query-job
   └──JWT──> 阿里云 FC 3.0 (HTTP trigger): fc-query
                ├─ 自行验证 Cognito JWT（拉 JWKS，PyJWT 验签）← 跨云认证核心得分点
                └─ 读 OSS 上的 index.json 副本做查询
S3 uploads/ ──ObjectCreated 事件──> process-media (容器 Lambda, 6GB/900s)
                ├─ OpenCV 缩略图（保宽高比、压缩）
                ├─ 视频用 ffmpeg 抽 1帧/秒 再逐帧检测
                ├─ MegaDetector(mdv5a.pt) → 裁剪 → SpeciesNet(model.pt) → 标签+计数
                ├─ 写 DynamoDB Files 表
                ├─ 复制文件+缩略图到阿里云 OSS + 重建 index.json（多云复制得分点）
                └─ SNS 按标签发布通知（MessageAttributes tag 过滤）
模型版本化：S3 models/pointer.json 指向模型文件，Lambda 冷启动读指针下载 → 换模型只改指针不改代码
```

**关键设计决策**：
- AWS 管写路径（上传/ML/变更），阿里云 FC 管读路径（查询）→ 真实的跨云 JWT 验证演示。
- Learner Lab 只有 LabRole、不能建 IAM 用户 → 阿里云无法持 AWS 密钥读 DynamoDB。方案：每次变更后把 Files 表 Scan 成 `index.json` 推到 OSS 作为**读副本**（几十条数据毫秒级），DynamoDB 仍是权威库。阿里云侧可建只读 RAM 用户，展示真正的最小权限。
- 查询用 Scan + 代码内过滤/交集（作业规模足够正确），报告里说明生产方案应为倒排索引表。
- 去重：前端 WebCrypto 算 SHA-256 → presign 时 `PutItem` 带 `attribute_not_exists(checksum)` 条件写 → 冲突返回 409 + 已有 URL。

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
| Google OAuth（加分项，可 Day 3 再搞） | Google Cloud Console 建 OAuth 客户端（Web），拿 Client ID/Secret 填进 Cognito Identity Provider | A |

### 项目脚手架（我来生成）
monorepo 目录（frontend/ aws/ aliyun/ docs/ scripts/）、`.gitignore`、`frontend/`（Vite+React+TS 初始化）、`aws/`（SAM init）、`aliyun/`（s.yaml 骨架）、`README.md`（每人如何跑 setup-local.sh + 各自部署命令）、`docs/env-setup.md`（记录上面的账号步骤，组员照抄）。

## 云部署形态（明确回答"部署到哪"）

代码在本地编写，通过两条命令全部发布到云端，之后用户只用浏览器访问云端 URL：
- `./scripts/deploy-aws.sh` = `sam build && sam deploy` → 在 AWS 建：Cognito 用户池、API 网关（JWT 授权）、api-handler（zip Lambda）、process-media（ECR 容器 Lambda）、S3 桶×3（uploads/thumbnails/models）、DynamoDB×2、SNS Topic，**并把 `npm run build` 产出的前端传到 S3 静态网站托管**（配 CORS + Cognito 回调 URL，前端也上云，不依赖 localhost）。
- `./scripts/deploy-aliyun.sh` = `s deploy` → 在阿里云建：fc-query 函数（HTTP 触发器）+ OSS 副本桶（RAM 只读用户）。
- 本地不保留任何常驻服务；Learner Lab 会话重置后重跑两个脚本即可完整重建（这正是必须 IaC 的原因）。

## 仓库结构

```
pacific-bioarchive/
├── frontend/            # React 18 + Vite + TS
│   └── src/{auth,pages,components,api}/
├── aws/                 # SAM 项目
│   ├── template.yaml    # Cognito 池/客户端、S3×3、DynamoDB×2、HTTP API+JWT授权、Lambda×2、ECR、SNS Topic
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

**URL 形态定案（对应评分表 2.1.3 "URLs (image/thumbnail) to the DB" 字面要求）**：
- `oss_url`/`thumbnail_oss_url` = **稳定永久 URL**（OSS 副本桶 public-read），存 DB、所有查询接口返回、并作为 2.2.2 按缩略图查原图 / 2.3 批量打标签 / 2.3 删除三个接口的**往返输入**（作业正文把 URL 当标识符来回传，临时签名 URL 会导致这三个功能断裂）。后端从 URL 解析 key，同时兼容裸 key 输入。
- AWS S3 桶保持私有（Block Public Access），仅 presigned PUT 上传 + ML 内部处理；`s3_key` 作内部字段。
- 报告中写明该设计：DB 同时存 key 与规范 URL，安全性（私有桶）与评分字面要求（URLs in DB）兼得。

**QueryJobs 表**：PK `job_id`，TTL=now+1h（按文件查询的结果临时存放，查询文件绝不永久存储）。

## API 设计

**AWS API Gateway**（每条路由挂 JWT authorizer，CORS 允许 localhost:5173）：
| 方法+路径 | 请求 | 响应 |
|---|---|---|
| POST /upload/presign | {filename, checksum, content_type} | 200 {upload_url, file_id} / **409 重复+已有URL** |
| GET /files/{checksum} | — | 状态+标签+URL（前端轮询） |
| POST /query/file | multipart 文件 | 202 {job_id}（存 temp/ 前缀，异步调 process-media mode=query，用完即删） |
| GET /query/jobs/{job_id} | — | 检测到的标签+匹配文件 URL 列表 |
| POST /tags/bulk | {urls, tags, operation: 1\|0} | {updated, ignored}（删除不存在的标签→忽略） |
| POST /files/delete | {urls} | 删 S3+OSS+缩略图+DB 条目+重建索引 |
| POST /notifications/subscribe | {email, tags} | SNS 订阅（FilterPolicy 按 tag） |
| GET /files | — | Gallery 列表 |

**阿里云 FC**（代码内验 Cognito JWT，失败 401）：
| POST /query/tags | {"tags": {"wombat":2,"magpie":1}} 或 {"dingo": null}（无计数=≥1） | 结果列表：图片返回缩略图 URL，视频返回完整 URL |
| GET /query/by-thumbnail?url=... | 缩略图 URL | 对应原图完整 URL |

SNS 发布：process-media 对每个不同物种发一条消息，`MessageAttributes={"tag": 物种}`，正文为文件 URL JSON —— 与订阅 FilterPolicy 精确匹配。

## ML 流水线（移植 batch.py）

1. 冷启动：读 `models/pointer.json` → 下载 mdv5a.pt + model.pt 到 /tmp → 加载进全局变量。
2. 图片：OpenCV 生成缩略图（最长边 300px 保宽高比、JPEG q=70）→ MegaDetector 检测（conf≥0.05）→ 裁剪 bbox（相对坐标转像素）→ resize 600×600 BILINEAR → transform `Resize((480,480))+ToTensor` → `permute(0,2,3,1)` NHWC → model.pt → softmax → 46 类 argmax（classes 列表从 batch.py:148 原样复制）。`torch.load(..., weights_only=False)` 保持原样调用。
3. 视频：`ffmpeg -i in -vf fps=1 /tmp/frames/%04d.jpg` → 逐帧跑 2 → 计数跨帧累加；缩略图取第 0 帧。
4. 容器 Dockerfile：`public.ecr.aws/lambda/python:3.12` + dnf 装 ffmpeg + CPU 版 torch/torchvision + megadetector、onnx2torch、opencv-python-headless、boto3、oss2、pillow、numpy。镜像约 4GB（模型不打包，运行时从 S3 拉）。

## 前端页面

- 路由守卫 AuthGuard：无会话 → 重定向 /signup（作业要求未登录只能看注册页）。
- 认证：amazon-cognito-identity-js —— signUp(email, given_name, family_name, password)、confirmSignUp、signIn、signOut；另做一个 NEW_PASSWORD_REQUIRED 强制改密页（用 admin-create-user 种一个临时密码用户来演示）。加分项（时间允许）：Cognito 挂 Google IdP 外部登录。
- UploadPanel：拖拽 → SHA-256 → presign → PUT → 轮询状态（冷启动 60–90s，显示 processing 状态徽章）→ 409 显示去重提示。
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
- **每实现一小块 → 归属到人 → 本地 commit，message 首行带上归属**，格式：
  `[A] feat: Cognito 注册页 + 路由守卫` / `[B] fix: pipeline 裁剪 bbox 越界` / `[C] feat: bulk tag API` / `[D] test: smoke-test 跨云 401`
- 归属不清/共用脚手架用 `[team] chore: ...`（如首次搭建目录+gitignore）。
- commit 用各自在 GitHub 上配好的 `user.name/email` 提交，记录贡献。
- 同步到 GitHub 用本机 token 身份 push（私有仓库 `pacific-bioarchive`，团队邀请 4 人 + 教学团队）。
- 每天至少一次 push，保证 everyone commits today。

### 当前状态（脚手架已按模块归属）
| 模块 | 负责人 | 状态 |
|---|---|---|
| Cognito 前端认证（signup/signin/logout/守卫） | A | 已写，待 `sam deploy` 后填真实 UserPoolId |
| `template.yaml`（UserPool/JWT/API/S3/DDB/SNS/ECR） | A | 已写，`sam validate --lint` 通过 |
| `process-media` Docker+pipeline+replicate | B | 已写，待模型上传+构建镜像 |
| api-handler 端点（presign/tags/delete/subscribe/files） | C | 已写，待落地+CORS/OSS 删除 |
| fc-query + s.yaml + AND 逻辑 | D | 已写，待集成测试 |

**Day 1（今天 8/26）**
- A（认证+基础设施）：`sam deploy` 建 Cognito 用户池；React 注册/登录/登出+路由守卫已就绪，填入真实 UserPoolId/ClientId。
- B（ML）：upload-models.sh 传模型+指针到 S3；构建容器镜像推 ECR（**多 GB 上传今晚启动，最长路径**）。
- C（数据）：DynamoDB+api-handler 端点落地；process-media 先打通 S3 事件链路。
- D（查询+集成）：fc-query + s.yaml + smoke-test 骨架已就绪，Ju 建立对照。
- 全员：建私有 GitHub 仓库，按 `[归属]` 规范 commit，全员当天就有 commit。

**Day 2（8/27）**
- B：真实流水线（MD+裁剪+SpeciesNet+缩略图+写库）端到端跑通。
- C：阿里云账号+RAM 用户+OSS 桶+s.yaml+fc-query JWT 验证+查询端点；replicate.py（OSS 复制+索引重建）接入。
- A：UploadPanel（WebCrypto 校验和+轮询）+ QueryPanel 调阿里云。

**Day 3（8/28）**
- C：批量标签/删除/SNS 订阅/by-thumbnail 端点。
- B：视频路径（ffmpeg 1fps）+ query-by-file 模式。
- A：Gallery+批量编辑+删除+QueryByFile+通知面板。
- 晚上跑完整 smoke-test.sh。

**Day 4（8/29）**
- 缓冲（冷启动/CORS/ECR 重建）；架构图（AWS+阿里云官方图标）、用户指南、团队报告+贡献表、个人报告；录备用演示视频；演练两遍。
- 落后裁剪线：Google 登录（加分项）→ 视频支持（只留短视频）→ 倒排索引。

## 验证方案（用 30 张测试图，真值=文件名前缀）

1. 流水线准确率 ≥27/30 顶级物种正确（conf 0.05 偏低，个别误报在报告中讨论）。
2. 去重：重传一张 → 409 + S3 对象数不变。
3. 查询 AND+计数：`{"Perameles_nasuta":2}`、`{"Hypsiprymnodon_moschatus":1,"Thylogale_stigmatica":2}` 验证逻辑与。
4. by-thumbnail：结果页取缩略图 URL → 返回同一文件原图 URL。
5. query-by-file：上传查询后断言 Files 表条数不变、temp/ 前缀为空。
6. 批量标签：加→删→删不存在的（ignored）。
7. 删除：S3、OSS、DDB、后续查询全消失。
8. 视频：用 ffmpeg 把静帧拼 10s 测试片 → 标签计数≥帧数、可查到视频完整 URL。
9. 通知：订阅 `Sus_scrofa` 过滤 → 上传 Sus_scrofa_1.JPG → 收到确认邮件+通知邮件（注意 Cognito 50 封/天、SNS 配额，回收用同一邮箱）。
10. 跨云认证：无 token/坏 token/过期 token → 401；有效 token → 200（截图进报告）。
11. 重建演练：结束 Lab 会话→fresh 会话跑两个 deploy 脚本→重跑冒烟测试。

## 风险与注意

- **Learner Lab 会重置**：所有资源必须进 template.yaml / s.yaml / 脚本，绝不手动建控制台资源。
- **冷启动** 60–90s（4GB 镜像+470MB 模型+torch import）：演示前先传一张小图保温。
- **IAM 限制**：只能用 LabRole；报告中说明"细粒度权限"设计（前端零凭证、仅预签名 URL、私有桶+Block Public Access、API 网关 JWT 授权、生产级各函数最小权限策略文档化）。
- **成本**：目标 $50 内花 <$10；process-media 6GB×数分钟/文件，30 张约几美元；阿里云新账号免费额度覆盖 FC+OSS。
- **megadetector 依赖树**容易冲突：固定版本、用 headless opencv、本地 `docker run` 先验证镜像再推。
- **报告 AI 声明**：6.2/6.3 节必须提及 GenAI 使用，否则 0 分。

## 首批要写的关键文件

- `aws/template.yaml` — 全部 AWS 资源
- `aws/process-media/Dockerfile` + `app.py` + `pipeline.py`（移植 `/Users/lxh/Documents/Monash/5225-周一/project2/PacificBioArchive/batch.py`，classes 列表在 148 行）
- `aws/api-handler/app.py` — 路由器
- `aliyun/fc-query/index.py` — JWKS JWT 验证 + 查询
- `frontend/src/auth/cognito.ts` + `components/UploadPanel.tsx`
- `scripts/smoke-test.sh`
