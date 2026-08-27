# Pacific BioArchive 进度记录

> 更新时间:2026-08-27 12:20 左右 · 距截止(08-30 23:55)约 3.5 天

## 一句话状态

AWS 基础设施、digest 固定镜像、阿里云 FC/OSS 和数据维护功能**已部署**；本地单测 10/10，FC 无/坏 token=401，maintenance=200 且 private OSS 已生成 `index.json`；**下一步是获取有效 Cognito access token 做数据 API 云端验收，再走真实媒体端到端**。

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

### 4. ECR 容器镜像重建+部署链路一致 ✅

时间线(均为 08-27):
- 11:28:18 容器代码最后修改(app.py / replicate.py / api-handler)
- 11:29:40 本地镜像构建(amd64,层缓存,仅 COPY 层变化)
- 11:29:43 推送 ECR,tag `latest`,digest `sha256:9fdf6870…`
- Lambda `pba-ProcessMediaFunction-fchVsBtcnysb` 绑定的 digest **= ECR latest digest** ✅

> 说明:期间 `deploy-ecr.sh` 曾因隔离 DOCKER_CONFIG 导致 buildx 插件不可见而中止过一轮;
> 修复(仅 login/push 用隔离配置,buildx 构建用原配置)已写入脚本,**且修复后的推送已在上面时间线中成功完成**。

### 5. 阿里云与数据维护云验证 ✅

- FC3 `pba-query`: `https://pba-query-iseukvgnef.cn-hangzhou.fcapp.run`
- private `pba-oss-copy`: ACL 已确认为 `private`
- 无 token=401，坏 token=401，CORS OPTIONS=204
- ProcessMedia maintenance `rebuild_index`=200，OSS `index.json=[]`
- 批量标签后刷新索引、跨云删除、SNS FilterPolicy 已实现并部署

### 6. 本地单元测试 10/10 通过 ✅(独立复跑确认)

- test_aliyun × 3:access-token 契约、FC3 HTTP handler+CORS、查询返回私有桶签名 URL
- test_p0 × 7:bulk-tags、跨云删除、FilterPolicy、multipart、查询入队/匹配、index 只含 processed
- 运行方式:`python3.12 -m unittest discover -s tests`(需 boto3 可导入,用临时 venv 即可)

### 7. Git 本地提交 8 个

数据维护实现提交:`feat: complete cross-cloud data maintenance`；本次进度同步提交后共 8 个。仍只有 `lxh` 一位作者，且未配置 remote。

## 待办(按优先级)

1. **有效 Cognito token 数据 API 云端验收**：bulk tag → 删标签 → 删不存在标签 → 删文件；SNS 需真实邮箱确认。
2. **真实媒体端到端**：小图上传 → 私有模型冷启动 → 标签/缩略图 → OSS 副本 → 阿里云查询。
3. **Git 风险(评分硬要求)**:目前 8 个 commit **全部单一作者(lxh)**,且**无 remote**。
   需尽快:建/连 GitHub 私有库 → push → 其他 3 位组员按分工提交各自模块
4. **前端部署**:config.ts 仍是占位符(设计为部署时注入
   `public/config.js`)；AWS/Cognito/FC URL 均已取得，待写入运行时配置 → 构建 → sync 到 WebBucket
5. **端到端冒烟**:真实图片上传 → ML 打标 → 缩略图 → OSS 复制 → 查询 → 删除;
   smoke-test.sh 目前只有 2 项真实断言,其余 8 项待实现
6. **交付物**:架构图、用户指南、团队报告(AI 使用声明必写)、演示演练

## 部署顺序(已定,勿回退)

ECR 镜像 → AWS 基础设施 → 模型上传 → **阿里云(OSS+FC)** → 前端配置注入+构建上传 → 冒烟测试

> 前端查询面板需要 FC URL;process-media 处理完成即写 OSS,故阿里云必须先于前端与首次上传。
