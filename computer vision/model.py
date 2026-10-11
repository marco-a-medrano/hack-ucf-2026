#!/usr/bin/env python3
"""Fine-tune a pretrained YOLOv8-OBB model on the split parking-spot dataset.

Save this file in the ``computer vision`` directory, alongside the ``images``
folder created by ``splitter/split_images.py``.

Expected layout:
    computer vision/
    ├── train.py
    ├── images/
    │   ├── data.yaml
    │   ├── train/images/ and train/labels/
    │   ├── eval/images/  and eval/labels/
    │   └── test/images/  and test/labels/
    └── runs/                 (created during training)

CUDA is required by default. The script stops rather than silently training on
CPU. It uses the OBB model because the source dataset is YOLO oriented-box data.

Run from any working directory:
    python "computer vision/train.py"

Optional overrides:
    python "computer vision/train.py" --imgsz 640 --batch 8 --epochs 100
    python "computer vision/train.py" --model yolov8n-obb.pt --motion-blur
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = BASE_DIR / "images" / "data.yaml"
DEFAULT_RUNS = BASE_DIR / "runs" / "obb"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLOv8-OBB parking-spot model")
    parser.add_argument(
        "--data",
        default=str(DEFAULT_DATA),
        help=f"dataset data.yaml (default: {DEFAULT_DATA})",
    )
    parser.add_argument(
        "--model",
        default="yolov8s-obb.pt",
        help="pretrained YOLO OBB weights (e.g. yolov8n-obb.pt or yolov8s-obb.pt)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=960,
        help="training image size; use 640 if GPU memory runs out",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument(
        "--batch",
        type=int,
        default=4,
        help="batch size; lower to 2 if CUDA runs out of memory",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=0,
        help="NVIDIA GPU index (default: 0); CPU is intentionally not supported",
    )
    parser.add_argument("--name", default="parking-spots")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--motion-blur",
        action="store_true",
        help="add motion-blur augmentation (requires albumentations and a compatible Ultralytics version)",
    )
    return parser.parse_args()


def require_gpu(device_index: int) -> None:
    try:
        import torch
    except ImportError as exc:
        raise SystemExit(
            "PyTorch is not installed in this Python environment. Install a CUDA-enabled "
            "PyTorch build before training."
        ) from exc

    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA is not available to PyTorch, so training was stopped instead of using CPU.\n"
            "Check your NVIDIA driver and CUDA-enabled PyTorch installation, then try again."
        )

    if device_index < 0 or device_index >= torch.cuda.device_count():
        raise SystemExit(
            f"GPU index {device_index} is unavailable. PyTorch sees "
            f"{torch.cuda.device_count()} CUDA GPU(s)."
        )

    torch.cuda.set_device(device_index)
    props = torch.cuda.get_device_properties(device_index)
    print(f"PyTorch version: {torch.__version__}")
    print(f"PyTorch CUDA build: {torch.version.cuda}")
    print(f"Using GPU {device_index}: {props.name}")
    print(f"GPU memory: {props.total_memory / (1024 ** 3):.1f} GiB")


def resolve_dataset_root(data_yaml: Path, config: dict[str, Any]) -> Path:
    raw_root = config.get("path", str(data_yaml.parent))
    root = Path(str(raw_root)).expanduser()
    if not root.is_absolute():
        root = data_yaml.parent / root
    return root.resolve()


def validate_dataset(data_yaml: Path) -> None:
    if not data_yaml.is_file():
        raise SystemExit(
            f"Dataset YAML not found: {data_yaml}\n"
            "Expected computer vision/images/data.yaml. Keep train.py in the "
            "computer vision directory and run splitter/split_images.py first."
        )

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("PyYAML is missing. Install it with: pip install pyyaml") from exc

    try:
        config = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise SystemExit(f"Could not read {data_yaml}: {exc}") from exc

    if "names" not in config or "nc" not in config:
        raise SystemExit(f"{data_yaml} must contain both 'names' and 'nc'.")

    names = config["names"]
    if not isinstance(names, (list, dict)) or len(names) == 0:
        raise SystemExit(f"The 'names' entry in {data_yaml} must be a non-empty list or mapping.")
    if int(config["nc"]) != len(names):
        raise SystemExit(
            f"Class count mismatch in {data_yaml}: nc={config['nc']} but names has {len(names)} class(es)."
        )

    dataset_root = resolve_dataset_root(data_yaml, config)
    label_counts: dict[str, int] = {}
    nonempty_label_counts: dict[str, int] = {}

    # Ultralytics expects the validation key to be called 'val'; the splitter maps it to eval/images.
    for yaml_key, display_name in (("train", "train"), ("val", "eval"), ("test", "test")):
        if yaml_key not in config:
            raise SystemExit(f"Missing '{yaml_key}' entry in {data_yaml}")

        split_path = Path(str(config[yaml_key])).expanduser()
        image_dir = split_path if split_path.is_absolute() else dataset_root / split_path
        image_dir = image_dir.resolve()
        if not image_dir.is_dir():
            raise SystemExit(f"The '{yaml_key}' image directory does not exist: {image_dir}")

        images = [
            path for path in image_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if not images:
            raise SystemExit(f"No images found in the '{yaml_key}' split: {image_dir}")

        label_dir = image_dir.parent / "labels"
        if not label_dir.is_dir():
            raise SystemExit(f"Matching labels directory does not exist: {label_dir}")

        label_files = list(label_dir.glob("*.txt"))
        nonempty_lines = 0
        bad_format: tuple[Path, int, int] | None = None
        for label_file in label_files:
            try:
                lines = label_file.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise SystemExit(f"Could not read label file {label_file}: {exc}") from exc

            for line_number, line in enumerate(lines, start=1):
                parts = line.split()
                if not parts:
                    continue
                # YOLO OBB labels: class + 8 normalized corner coordinates (9 values total).
                if len(parts) != 9 and bad_format is None:
                    bad_format = (label_file, line_number, len(parts))
                nonempty_lines += 1

        if bad_format:
            bad_file, line_no, value_count = bad_format
            raise SystemExit(
                f"Label format does not look like YOLO OBB at {bad_file}:{line_no}: "
                f"found {value_count} values, expected 9 (class + four x/y corners).\n"
                "This script uses an OBB model; do not use regular detection weights with OBB labels."
            )

        label_counts[display_name] = len(label_files)
        nonempty_label_counts[display_name] = nonempty_lines
        print(
            f"{display_name:5} split: {len(images):5} images | "
            f"{len(label_files):5} label files | {nonempty_lines:5} labeled boxes"
        )

    if nonempty_label_counts["train"] == 0:
        raise SystemExit(
            "The training split has no labeled OBB boxes. Check that train/labels contains the expected .txt files."
        )

    print(f"Dataset YAML: {data_yaml}")
    print(f"Dataset root: {dataset_root}")
    print(f"Classes: {names}")
    print("The test split is checked for files but will not be used during training.")


def main() -> None:
    args = parse_args()
    data_yaml = Path(args.data).expanduser().resolve()

    print("Checking CUDA GPU...")
    require_gpu(args.device)

    print("\nChecking dataset paths and OBB labels...")
    validate_dataset(data_yaml)

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("Ultralytics is missing. Install it with: pip install ultralytics") from exc

    print(f"\nLoading pretrained OBB model: {args.model}")
    model = YOLO(args.model)
    if getattr(model, "task", None) != "obb":
        raise SystemExit(
            f"Loaded model task is {getattr(model, 'task', 'unknown')!r}, not 'obb'.\n"
            "Use an OBB checkpoint such as yolov8n-obb.pt or yolov8s-obb.pt."
        )

    training_config: dict[str, Any] = {
        "data": str(data_yaml),
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "batch": args.batch,
        "device": args.device,       # Explicit NVIDIA CUDA GPU; CPU fallback is not enabled.
        "workers": args.workers,
        "name": args.name,
        "project": str(DEFAULT_RUNS),
        "patience": 30,
        "hsv_v": 0.5,                # Lighting changes between daytime, nighttime, and glare.
        "fliplr": 0.5,
        "flipud": 0.0,
        "degrees": 0.0,              # Keep the camera's expected orientation.
        "close_mosaic": 15,
        "amp": True,
        "cache": False,
        "seed": 42,
        "plots": True,
    }

    if args.motion_blur:
        try:
            import albumentations as A
            training_config["augmentations"] = [A.MotionBlur(blur_limit=(3, 9), p=0.3)]
        except ImportError:
            print("albumentations is not installed; continuing without motion blur (pip install albumentations).")

    print(f"\nStarting training on GPU {args.device}...")
    try:
        model.train(**training_config)
    except (SyntaxError, TypeError) as exc:
        if "augmentations" not in training_config:
            raise
        print(f"This Ultralytics version rejected custom augmentations ({exc}); retrying without motion blur.")
        training_config.pop("augmentations")
        model.train(**training_config)

    print("\nTraining finished.")
    print(f"Runs and weights are saved under: {DEFAULT_RUNS}")
    print("Use the best.pt from this run for inference, then evaluate on the held-out test split separately.")


if __name__ == "__main__":
    # Ultralytics uses multiprocessing on Windows; the main guard is required.
    main()
