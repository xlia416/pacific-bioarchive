# Pacific BioArchive process-media — 容器镜像 Lambda
# 用途：S3 ObjectCreated → 加载 MegaDetector + SpeciesNet → 缩略图/视频抽帧 → ML 打标签 → 写 DynamoDB + 复制到 OSS + SNS。
# 模型不打包进镜像：运行时冷启动从 MODELS_BUCKET 拉（models/pointer.json 版本化）。

# mega-sam 需要较高 python；用 AWS 官方 Lambda Python 3.12 基础镜像
FROM public.ecr.aws/lambda/python:3.12

# 系统依赖：OpenCV 运行时库 + ffmpeg（视频抽帧）。
# AWS Lambda python:3.12 基础镜像是 AlmaLinux（极精简，无 tar/curl），dnf 默认源无 ffmpeg。
# 方案：dnf 只装 libGL/OpenCV 需要的库；ffmpeg 用 John Van Sickle 静态构建（单文件可执行），
#       用内嵌 Python 下载+解压（基础镜像必有 Python，绕开缺 tar/curl）。
RUN dnf install -y \
        libGL \
        glib2 \
        libXext libSM libXrender \
    && dnf clean all \
    && python3 -c "import urllib.request,tarfile,shutil; \
u='https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz'; \
urllib.request.urlretrieve(u,'/tmp/ffmpeg.tar.xz'); \
tarfile.open('/tmp/ffmpeg.tar.xz').extractall('/tmp/ff'); \
p=next(m for m in __import__('os').listdir('/tmp/ff') if m.startswith('ffmpeg'))+'/ffmpeg'; \
shutil.copy('/tmp/ff/'+p,'/usr/local/bin/ffmpeg')" \
    && chmod +x /usr/local/bin/ffmpeg \
    && ffmpeg -version | head -1

# 先装 torch（CPU 版：Lambda 无 GPU，避免带 CUDA 的体积/冷启动开销，推理走 CPU）
ENV PIP_NO_CACHE_DIR=1
RUN pip install --upgrade pip && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 按作业 README：python -m pip install megadetector tqdm + python -m pip install onnx2torch。
# onnx2torch 仅要求 onnx>=1.9.0，但 pip 可能自动选 onnx 1.15（py3.12 无 wheel → 源码编译）。
# 根治：把 onnx>=1.30 带进同一个 pip 解析（1.22.0 在 linux-x86_64+py3.12 有预编译 wheel，已验证），
# 锁住版本避免换回 1.15 重编译。megadetector 走 onnxruntime（有 wheel）。
RUN pip install \
    "onnx>=1.22" \
    "megadetector" \
    "onnx2torch==1.5.15" \
    onnxruntime \
    pyyaml \
    tqdm \
    opencv-python-headless \
    boto3 \
    oss2 \
    requests \
    numpy \
    pillow

# 业务代码
COPY app.py pipeline.py replicate.py ./

CMD ["app.lambda_handler"]