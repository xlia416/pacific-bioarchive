import importlib.util
import os
import pathlib
import sys
import tempfile
import types
import unittest

from PIL import Image


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "MODELS_BUCKET": "models",
        "THUMBS_BUCKET": "thumbs",
        "OSS_BUCKET": "oss",
        "OSS_ENDPOINT": "oss.example.com",
    }
)


spec = importlib.util.spec_from_file_location(
    "pba_pipeline", ROOT / "aws/process-media/pipeline.py"
)
pipeline_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline_module)


class PipelineTests(unittest.TestCase):
    def test_detect_many_loads_detector_once_for_all_frames(self):
        calls = []

        def fake_batch(**kwargs):
            calls.append(kwargs)
            return [
                {
                    "file": filename,
                    "detections": [
                        {"category": "1", "conf": 0.9, "bbox": [0, 0, 1, 1]}
                    ],
                }
                for filename in kwargs["image_file_names"]
            ]

        run_detector = types.ModuleType("megadetector.detection.run_detector_batch")
        run_detector.load_and_run_detector_batch = fake_batch
        detection = types.ModuleType("megadetector.detection")
        detection.run_detector_batch = run_detector
        megadetector = types.ModuleType("megadetector")
        megadetector.detection = detection

        old_modules = {
            name: sys.modules.get(name)
            for name in (
                "megadetector",
                "megadetector.detection",
                "megadetector.detection.run_detector_batch",
            )
        }
        sys.modules.update(
            {
                "megadetector": megadetector,
                "megadetector.detection": detection,
                "megadetector.detection.run_detector_batch": run_detector,
            }
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                frames = []
                for index in range(10):
                    frame = pathlib.Path(directory) / f"{index:04d}.jpg"
                    Image.new("RGB", (40, 30), "white").save(frame)
                    frames.append(str(frame))

                pipeline = pipeline_module.InferencePipeline.__new__(
                    pipeline_module.InferencePipeline
                )
                pipeline.md_path = "/tmp/mdv5a.pt"
                pipeline.classifier = object()
                pipeline.transform = object()
                pipeline._classify_crop = lambda _crop: ("Sus_scrofa", 0.99)

                self.assertEqual(pipeline.detect_many(frames), {"Sus_scrofa": 10})
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["image_file_names"], frames)
                self.assertEqual(calls[0]["batch_size"], 1)
                self.assertIsNone(pipeline.classifier)
                self.assertIsNone(pipeline.transform)
        finally:
            for name, module in old_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_pillow_thumbnail_preserves_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "wide.jpg"
            Image.new("RGB", (800, 400), "white").save(source)
            pipeline = pipeline_module.InferencePipeline.__new__(
                pipeline_module.InferencePipeline
            )
            thumbnail = pipeline.make_thumbnail(str(source), size=300)
            try:
                with Image.open(thumbnail) as image:
                    self.assertEqual(image.size, (300, 150))
                    self.assertEqual(image.format, "JPEG")
            finally:
                pipeline_module._remove_files([thumbnail])


if __name__ == "__main__":
    unittest.main()
