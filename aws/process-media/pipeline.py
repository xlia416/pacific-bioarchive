# pipeline.py — 媒体处理 + ML 物种识别（移植自 batch.py）
# 流程：读 models/pointer.json → 下载 mdv5a.pt + model.pt → 缩略图 → MegaDetector 检测 → 裁剪 bbox → resize 600x600 → SpeciesNet 分类。

import os
import json
import mimetypes
import subprocess
import boto3
import numpy as np

# ---------- 常量与惰性模型加载 ----------
s3 = boto3.client("s3")
MODELS_BUCKET = os.environ["MODELS_BUCKET"]
THUMBS_BUCKET = os.environ["THUMBS_BUCKET"]
OU_ENDPOINT = os.environ["OSS_ENDPOINT"]
OU_BUCKET = os.environ["OSS_BUCKET"]

# 支持的物种类别（batch.py 第 148 行原样复制）
CLASSES = ['Alectura_lathami', 'Antechinus_agilis', 'Bos_taurus', 'Burhinus_grallarius', 'Canis_familiaris', 'Chalcophaps_longirostris', 'Colluricincla_harmonica', 'Corcorax_melanorhamphos', 'Dacelo_novaeguineae', 'Dama_dama', 'Eopsaltria_australis', 'Felis_catus', 'Geopelia_humeralis', 'Gymnorhina_tibicen', 'Homo_sapiens', 'Isoodon_macrourus', 'Lepus_europaeus', 'Macropus_giganteus', 'Menura_novaehollandiae', 'Mus_musculus', 'Oryctolagus_cuniculus', 'Perameles_nasuta', 'Pitta_versicolor', 'Rattus', 'Rattus_fuscipes', 'Rattus_rattus', 'Strepera_graculina', 'Sus_scrofa', 'Tachyglossus_aculeatus', 'Thylogale_stigmatica', 'Trichosurus_caninus', 'Trichosurus_cunninghami', 'Trichosurus_vulpecula', 'Varanus_varius', 'Vombatus_ursinus', 'Vulpes_vulpes', 'Wallabia_bicolor', 'Canis_dingo', 'Capra_hircus', 'Casuarius_casuarius', 'Heteromyias_cinereifrons', 'Hypsiprymnodon_moschatus', 'Megapodius_reinwardt', 'Notamacropus_rufogriseus', 'Orthonyx_spaldingii', 'Uromys_caudimaculatus']


class InferencePipeline:
    """惰性加载模型 + 核心分类逻辑。查询模式可复用于 query-by-file。"""

    def __init__(self):
        self.md = None
        self.classifier = None
        self.transform = None
        # ModelsBucket 是私有桶；始终通过 Lambda execution role 读取指针。
        response = s3.get_object(Bucket=MODELS_BUCKET, Key="models/pointer.json")
        ptr = json.loads(response["Body"].read())
        self._load_md(ptr["mdv5a"])
        self._load_classifier(ptr["speciesnet"])

    # ---- 加载 ----
    def _download_model(self, key):
        local = f"/tmp/models/{key.replace('/', '_')}"
        os.makedirs("/tmp/models", exist_ok=True)
        if not os.path.exists(local):
            print(f"[model] downloading {key}")
            s3.download_file(MODELS_BUCKET, f"models/{key}", local)
        return local

    def _load_md(self, key):
        local = self._download_model(key)
        self.md_path = local
        print("[model] md ready at", local)

    def _load_classifier(self, key):
        import torch
        import torchvision.transforms as transforms
        local = self._download_model(key)
        device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
        self.device = device
        self.classifier = torch.load(local, map_location=device, weights_only=False)
        self.classifier.eval().to(device)
        self.transform = transforms.Compose([
            transforms.Resize((480, 480)),
            transforms.ToTensor(),
        ])
        print(f"[model] classifier loaded on {device}")

    # ---- 单类分类（batch.py 的 classify_image，去掉绘图） ----
    def _classify_crop(self, crop_pil):
        import torch
        import torch.nn.functional as F
        img = self.transform(crop_pil).unsqueeze(0).permute(0, 2, 3, 1).to(self.device)
        with torch.no_grad():
            logits = self.classifier(img)
            probs = F.softmax(logits, dim=1)[0].cpu().numpy()
        idx = int(np.argmax(probs))
        return CLASSES[idx], float(probs[idx])

    # ---- 对外 ----
    def detect(self, image: str) -> dict:
        """MegaDetector → 裁剪 → SpeciesNet。返回 {species: count}。"""
        from PIL import Image
        from megadetector.detection.run_detector_batch import load_and_run_detector_batch
        # 使用关键字参数，避免 MegaDetector 10.x 中 model_file 作为
        # 第一个位置参数时与显式 model_file 重复绑定。
        res = load_and_run_detector_batch(
            model_file=self.md_path,
            image_file_names=[image],
        )
        tags: dict = {}
        for entry in res:
            for det in entry.get("detections", []):
                if det.get("category") != "1":
                    continue
                if det.get("conf", 0) < 0.05:
                    continue
                img = Image.open(image).convert("RGB")
                W, H = img.size
                x, y, w, h = det["bbox"]
                crop = img.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)))
                crop = crop.resize((600, 600), Image.BILINEAR)
                species, conf = self._classify_crop(crop)
                tags[species] = tags.get(species, 0) + 1
        return tags or {"no_animal": 1}   # 无动物则打一个噪音标签占位，报告讨论阈值

    def detect_file(self, source: str) -> dict:
        """查询文件共用检测路径；视频同样严格按 1 帧/秒处理。"""
        ext = source.rsplit(".", 1)[-1].lower() if "." in source else ""
        if ext not in ("mp4", "mov", "avi", "mkv", "webm"):
            return self.detect(source)
        tags = {}
        for frame in self.extract_frames(source):
            tags = _merge(tags, self.detect(frame))
        return tags or {"no_animal": 1}

    def make_thumbnail(self, source: str, size=300) -> str:
        import cv2
        img = cv2.imread(source)
        h, w = img.shape[:2]
        scale = size / max(h, w)
        if scale < 1:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        out = f"/tmp/{os.path.basename(source)}_thumb.jpg"
        cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return out

    def extract_frames(self, video: str, out_dir="/tmp/frames") -> list:
        """视频：ffmpeg 抽 1 帧/秒。返回帧文件列表。"""
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))
        subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-vf", "fps=1", f"{out_dir}/%04d.jpg"],
            check=True, capture_output=True,
        )
        return sorted(os.path.join(out_dir, f) for f in os.listdir(out_dir))

    def process(self, source: str, checksum: str, filename: str) -> dict:
        """正式入库：生成缩略图/抽帧 + 检测 + 写 S3 缩略图 + 组装 DB/OSS record。"""
        ext = filename.split(".")[-1].lower()
        is_video = ext in ("mp4", "mov", "avi", "mkv", "webm")

        thumb = None
        tags: dict = {}
        if is_video:
            frames = self.extract_frames(source)
            for fr in frames:
                tags = _merge(tags, self.detect(fr))
            thumb = self.make_thumbnail(frames[0]) if frames else None
        else:
            thumb = self.make_thumbnail(source)
            tags = self.detect(source)

        # 上传缩略图到 S3（私有桶）
        thumb_key = f"thumbs/{checksum}/thumb.jpg"
        s3.upload_file(thumb, THUMBS_BUCKET, thumb_key, ExtraArgs={"ContentType": "image/jpeg"})

        # 稳定 OSS URL（跨云副本）：文件本体 + 缩略图
        oss_url = f"https://{OU_BUCKET}.{OU_ENDPOINT}/uploads/{checksum}/{filename}"
        thumb_oss_url = f"https://{OU_BUCKET}.{OU_ENDPOINT}/thumbs/{checksum}/thumb.jpg"

        return {
            "checksum": checksum,
            "filename": filename,
            "file_type": "video" if is_video else "image",
            "s3_key": f"uploads/{checksum}/{filename}",
            "thumbnail_s3_key": thumb_key,
            "oss_key": f"uploads/{checksum}/{filename}",
            "thumbnail_oss_key": f"thumbs/{checksum}/thumb.jpg",
            "oss_url": oss_url,
            "thumbnail_oss_url": thumb_oss_url,
            "content_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "_thumbnail_path": thumb,
            "tags": tags,
            "status": "processed",
        }


def _merge(a: dict, b: dict) -> dict:
    m = dict(a)
    for k, v in b.items():
        m[k] = m.get(k, 0) + v
    return m
