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

# 锁定真正提供 `megadetector` import namespace 的版本。
# 10.0.24 支持 Python 3.12，且 wheel 包含本项目使用的
# megadetector.detection.run_detector_batch。先单独解析它，禁止 pip
# 为了 ONNX 的 protobuf 约束静默回退到 5.0.4。
RUN pip install \
    "megadetector==10.0.24" \
    pyyaml \
    tqdm \
    opencv-python-headless \
    boto3 \
    oss2 \
    requests \
    numpy \
    pillow

# model.pt 的 pickle 实际引用 onnx2torch，因此 ONNX 不能删除。
# ONNX 1.22 需要 protobuf>=4.25.1，而 ultralytics-yolov5 0.1.1 的元数据
# 保守地限制 protobuf<=3.20.1。YOLOv5 的 .pt 推理路径不使用 protobuf；
# 这里显式升级 protobuf，并在下面只豁免这一条已知元数据冲突。
RUN pip install --upgrade \
        "protobuf==4.25.8" \
        "onnx==1.22.0" \
        "onnx2torch==1.5.15" \
        onnxruntime \
    && pip show megadetector protobuf onnx onnx2torch \
    && (pip check > /tmp/pip-check.txt 2>&1 || true) \
    && (grep -v '^ultralytics-yolov5 0.1.1 has requirement protobuf<=3.20.1' \
        /tmp/pip-check.txt > /tmp/unexpected-pip-check.txt || true)

# 任何除上述 protobuf 元数据以外的依赖异常都必须使构建失败；
# 同时在构建期执行与业务代码完全相同的关键 import。
RUN cat /tmp/pip-check.txt \
    && test ! -s /tmp/unexpected-pip-check.txt \
    && python -c "import onnx2torch; from megadetector.detection.run_detector_batch import load_and_run_detector_batch; print('MegaDetector and onnx2torch imports OK')"

# 业务代码
COPY app.py pipeline.py replicate.py ./

CMD ["app.lambda_handler"]
