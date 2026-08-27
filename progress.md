# Pacific BioArchive 进度记录

> 更新时间:2026-08-27 · 距截止(08-30 23:55)约 3.5 天

## 一句话状态

数据功能和 **SNS 真实邮件云端验收已通过**：真实上传、去重 409、标签增/删/ignored、query-by-file 隔离清理、跨云删除均成功；`Alectura_lathami_1.JPG` 保留为基准证据；**下一步是视频、Google 外部账号与前端**。

## 已完成(均有云上/本地证据)

### 1. AWS 栈 `pba` — UPDATE_COMPLETE ✅

| 输出 | 值 |
|---|---|
| API | https://o5g9c7rcac.execute-api.us-east-1.amazonaws.com |
| Cognito UserPool | us-east-1_FHAyKPNrs |
| Client ID | 2irism5thu55d8rp9b7aal5n4k |
| Web 静态站 | http://pba-web-987040391588.s3-website-us-east-1.amazonaws.com |
| 桶 | pba-uploads / thumbs / models / query / web(均 987040391588 后缀) |

### 2. P0 修订全部落地 ✅

- Cognito `CallbackURLs`(修复首轮部署回滚的根因)
- `EphemeralStorage: 4096`(模型 470MB + 媒体/帧)
- S3 触发器 `Filter: prefix uploads/`(query-by-file 隔离,rubric 2.2.3)
- 独立 `QueryBucket` + 1 天生命周期(查询临时文件绝不入库、自动清理)
- `ImageUri` 改为 digest 固定参数 `ProcessMediaImageUri`(同 tag 更新可被 CFN 感知)
- `pipeline.py` pointer.json 改 `s3.get_object`(私有桶,原公网 URL 会 403)
- `replicate.py` 补上真正的文件+缩略图 OSS 复制(原来只写 index.json,oss_url 全是死链)
- OSS 设计变更:**桶 private + 签名 URL**(放弃原 public-read;签名 URL 往返按规范化 key 匹配)

### 3. 模型已上传 ✅(10:42–10:45)

`s3://pba-models-987040391588/models/`:mdv5a.pt (280MB) · model.pt (211MB) · pointer.json

### 4. ECR 镜像依赖修复+部署链路一致 ✅

时间线(均为 08-27):
- 固定 `megadetector==10.0.24`，不再回退到无 import namespace 的 5.0.4
- 固定 `onnx==1.22.0`/`onnx2torch==1.5.15`/`protobuf==4.25.8`，只豁免 YOLOv5 对 protobuf 的过严元数据约束
- 构建期关键 import 通过；真实 `model.pt` 反序列化成功，真实 `mdv5a.pt` 733 层模型加载成功
- 修正 MegaDetector 10.x `load_and_run_detector_batch` 为全关键字参数调用
- 15:10 推送 ECR，digest `sha256:9cd6cd9997f58060f2c78434e7441a0aeaee30e1a1c5abd9ed9245d9e2cf047c`
- Lambda 状态 `Active`/`Successful`，绑定 digest **= ECR latest digest** ✅

> 说明:期间 `deploy-ecr.sh` 曾因隔离 DOCKER_CONFIG 导致 buildx 插件不可见而中止过一轮;
> 修复(仅 login/push 用隔离配置,buildx 构建用原配置)已写入脚本,**且修复后的推送已在上面时间线中成功完成**。

### 5. 阿里云与数据维护云验证 ✅

- FC3 `pba-query`: `https://pba-query-iseukvgnef.cn-hangzhou.fcapp.run`
- private `pba-oss-copy`: ACL 已确认为 `private`
- 无 token=401，坏 token=401，CORS OPTIONS=204
- ProcessMedia maintenance `rebuild_index`=200；上传后 OSS `index.json` 含 1 条正确媒体记录
- 批量标签后刷新索引、跨云删除、SNS FilterPolicy 已实现并部署
- 单图端到端：AWS/OSS 原图+缩略图、index、有效-token 按标签查询、签名 URL、缩略图反查均实测通过
- 可删除样本 `Canis_familiaris_3.JPG`：去重=409 且 S3 仍 1 对象；标签增/删/ignored 与 DDB/index/阿里云一致；query-by-file 完成后 Files 表仍 3 条、QueryBucket=0；删除后 AWS/OSS/DDB/index/查询均无该文件
- FC 依赖已固定为 Python 3.10 运行时兼容组合；OSS 读取失败重试后返回 502，不再静默伪装成空结果
- SNS 真实邮箱已确认订阅，FilterPolicy 为 `Sus_scrofa`；`Sus_scrofa_1.JPG` 处理为 `Sus_scrofa:1`，CloudWatch 最近窗口记录发布 2、邮件投递 1、失败 0；一次性 Cognito 用户已删除

### 6. 本地单元测试 11/11 通过 ✅(独立复跑确认)

- test_aliyun × 4:access-token 契约、FC3 HTTP handler+CORS、签名 URL、OSS 读失败不得静默返回空表
- test_p0 × 7:bulk-tags、跨云删除、FilterPolicy、multipart、查询入队/匹配、index 只含 processed
- 运行方式:`python3.12 -m unittest discover -s tests`(需 boto3 可导入,用临时 venv 即可)

### 7. Git 本地提交 11 个

本次数据功能云验收记录提交后共 11 个。仍只有 `lxh` 一位作者，且未配置 remote。

## 待办(按优先级)

1. **Git 风险(评分硬要求)**:本次 SNS 验收记录提交后 12 个 commit **全部单一作者(lxh)**,且**无 remote**。
   需尽快:建/连 GitHub 私有库 → push → 其他 3 位组员按分工提交各自模块
2. **视频云验收**：生成 10 秒测试视频，验证 1 fps 抽帧、标签计数和完整视频 URL。
3. **Google 外部账号**：配置 CloudFront HTTPS、Cognito Domain/Google IdP 与回调，验证联邦用户记录。
4. **前端部署**:config.ts 仍是占位符(设计为部署时注入
   `public/config.js`)；AWS/Cognito/FC URL 均已取得，待写入运行时配置 → 构建 → sync 到 WebBucket
5. **端到端冒烟**:单图、去重、query-by-file、标签、删除、通知已通过，待视频;
   smoke-test.sh 目前只有 2 项真实断言,其余 8 项待实现
6. **交付物**:架构图、用户指南、团队报告(AI 使用声明必写)、演示演练

## 部署顺序(已定,勿回退)

ECR 镜像 → AWS 基础设施 → 模型上传 → **阿里云(OSS+FC)** → 前端配置注入+构建上传 → 冒烟测试

> 前端查询面板需要 FC URL;process-media 处理完成即写 OSS,故阿里云必须先于前端与首次上传。
