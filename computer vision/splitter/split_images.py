from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required to read/write data.yaml. Install it with: pip install pyyaml")

# This script is in: computer vision/splitter/split_images.py
# Paths are based on this file, so the script can be run from any working directory.
BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = BASE_DIR / "ucf parking 2.yolov8-obb" / "train"
SOURCE_IMAGES = SOURCE_DIR / "images"
SOURCE_LABELS = SOURCE_DIR / "labels"
SOURCE_DATA_YAML = BASE_DIR / "ucf parking 2.yolov8-obb" / "data.yaml"
OUTPUT_DIR = BASE_DIR / "images"
OUTPUT_DATA_YAML = OUTPUT_DIR / "data.yaml"

# Conventional dataset split: 70% train, 20% evaluation/validation, 10% test.
SPLIT_RATIOS = {"train": 0.70, "eval": 0.20, "test": 0.10}
RANDOM_SEED = 42
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def find_files(folder: Path, extensions: set[str]) -> list[Path]:
    return sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    )


def build_stem_map(files: list[Path], kind: str) -> dict[str, Path]:
    by_stem: dict[str, Path] = {}
    for path in files:
        if path.stem in by_stem:
            sys.exit(
                f"Duplicate {kind} filename stem '{path.stem}'.\n"
                f"  First: {by_stem[path.stem]}\n  Second: {path}\n"
                "Resolve duplicate names before splitting."
            )
        by_stem[path.stem] = path
    return by_stem


def main() -> None:
    # Validate source paths and source class configuration before copying anything.
    for folder in (SOURCE_IMAGES, SOURCE_LABELS):
        if not folder.is_dir():
            sys.exit(f"Required folder not found: {folder}")
    if not SOURCE_DATA_YAML.is_file():
        sys.exit(f"Dataset config not found: {SOURCE_DATA_YAML}")

    source_config = yaml.safe_load(SOURCE_DATA_YAML.read_text(encoding="utf-8")) or {}
    names = source_config.get("names")
    if names is None:
        sys.exit(f"No 'names' entry found in {SOURCE_DATA_YAML}; cannot create the output data.yaml safely.")
    class_count = source_config.get("nc", len(names))

    images = find_files(SOURCE_IMAGES, IMAGE_EXTENSIONS)
    labels = find_files(SOURCE_LABELS, {".txt"})
    if not images:
        sys.exit(f"No images found in {SOURCE_IMAGES}")

    label_by_stem = build_stem_map(labels, "label")
    # This script writes files into flat images/labels folders, so duplicate image stems
    # could cause ambiguous label pairing even if the image extensions differ.
    image_by_stem = build_stem_map(images, "image")

    # Avoid overwriting a previous split. Empty pre-created folders are fine.
    if OUTPUT_DATA_YAML.exists():
        sys.exit(
            f"Output config already exists: {OUTPUT_DATA_YAML}\n"
            "This splitter is intended to run once. Check the existing split before rerunning."
        )
    for split in SPLIT_RATIOS:
        for subfolder in ("images", "labels"):
            target = OUTPUT_DIR / split / subfolder
            if target.exists() and any(p.is_file() for p in target.rglob("*")):
                sys.exit(
                    f"Output folder already contains files: {target}\n"
                    "No files were changed. Check or clear the previous output before rerunning."
                )

    shuffled_images = images[:]
    random.Random(RANDOM_SEED).shuffle(shuffled_images)

    total = len(shuffled_images)
    train_count = round(total * SPLIT_RATIOS["train"])
    eval_count = round(total * SPLIT_RATIOS["eval"])
    test_count = total - train_count - eval_count
    if min(train_count, eval_count, test_count) <= 0:
        sys.exit(
            f"Only {total} images found; there are too few to populate all three splits. "
            "Use at least 10 images or adjust the ratios."
        )

    split_files = {
        "train": shuffled_images[:train_count],
        "eval": shuffled_images[train_count:train_count + eval_count],
        "test": shuffled_images[train_count + eval_count:],
    }

    missing_labels = 0
    used_label_stems: set[str] = set()
    for split, split_images in split_files.items():
        destination_images = OUTPUT_DIR / split / "images"
        destination_labels = OUTPUT_DIR / split / "labels"
        destination_images.mkdir(parents=True, exist_ok=True)
        destination_labels.mkdir(parents=True, exist_ok=True)

        for image_path in split_images:
            shutil.copy2(image_path, destination_images / image_path.name)
            label_path = label_by_stem.get(image_path.stem)
            if label_path is None:
                # In YOLO datasets, an image without a .txt label is treated as a background image.
                missing_labels += 1
            else:
                shutil.copy2(label_path, destination_labels / label_path.name)
                used_label_stems.add(label_path.stem)

    unused_labels = sorted(set(label_by_stem) - used_label_stems)

    output_config = {
        "path": str(OUTPUT_DIR.resolve()),
        "train": "train/images",
        "val": "eval/images",
        "test": "test/images",
        "nc": class_count,
        "names": names,
    }
    OUTPUT_DATA_YAML.write_text(
        yaml.safe_dump(output_config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    print(f"Split complete: {total} images copied from {SOURCE_DIR}")
    print(f"  train: {len(split_files['train'])} images ({len(split_files['train']) / total:.1%})")
    print(f"  eval:  {len(split_files['eval'])} images ({len(split_files['eval']) / total:.1%})")
    print(f"  test:  {len(split_files['test'])} images ({len(split_files['test']) / total:.1%})")
    print(f"Images missing a matching .txt label: {missing_labels}")
    if unused_labels:
        print(f"Warning: {len(unused_labels)} label file(s) had no matching image and were not copied.")
    print(f"YOLO dataset config written to: {OUTPUT_DATA_YAML}")
    print("Original files were kept unchanged.")


if __name__ == "__main__":
    main()
