# Pacific BioArchive process-media — 容器镜像 Lambda
# 用途：S3 ObjectCreated → 加载 MegaDetector + SpeciesNet → 缩略图/视频抽帧 → ML 打标签 → 写 DynamoDB + 复制到 OSS + SNS。
# 模型不打包进镜像：运行时冷启动从 MODELS_BUCKET 拉（models/pointer.json 版本化）。

# mega-sam 需要较高 python；用 AWS 官方 Lambda Python 3.12 基础镜像
FROM public.ecr.aws/lambda/python:3.12

# 系统依赖：OpenCV 运行时库 + ffmpeg（视频抽帧）
RUN dnf install -y \
        ffmpeg \
        libGL \
        glib2 \
        libXext libSM libXrender \
    && dnf clean all

# 先装 torch（CPU 版，镜像体积受控）
ENV PIP_NO_CACHE_DIR=1
RUN pip install --upgrade pip && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        torch torchvision --index-url https://download.pytorch.org/whl/cpu

# megadetector 依赖树敏感：固定版本序列
RUN pip install \
    megadetector==0.7.0.3 \
    onnx2torch \
    yaml \
    pyyaml \
    tqdm \
    opencv-python-headless \
    boto3 \
    oss2 \
    requests \
    numpy \
    pillow

# 业务代码
COPY app.py pipeline.py model.py replicate.py ./

CMD ["app.lambda_handler"]