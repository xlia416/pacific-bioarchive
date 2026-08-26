#!/usr/bin/env bash
# 一键安装本机工具 + Python 依赖。4 名成员各自跑一次。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 安装 brew 工具（已装则跳过）"
for pkg in poppler awscli aws-sam-cli ffmpeg node@20 python@3.12; do
  brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"
done

echo 'export PATH="$(brew --prefix node@20)/bin:$PATH"' >> ~/.zshrc || true
export PATH="$(brew --prefix node@20)/bin:$PATH"

echo "==> 全局安装 Serverless Devs"
npm install -g @serverless-devs/s

echo "==> 创建 Python venv 并装模型依赖"
if [ ! -d .venv ]; then python3.12 -m venv .venv; fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install megadetector onnx2torch opencv-python-headless pillow boto3 oss2 numpy

echo "==> 验证"
aws --version
sam --version
s --version
.venv/bin/python --version

echo
echo "✅ 本机环境就绪。账号级步骤见 docs/env-setup.md（.env、GitHub 仓库、测试邮箱）。"
echo "   然后跑 ./scripts/deploy-aws.sh 和 ./scripts/deploy-aliyun.sh 完成部署。"