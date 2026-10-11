#!/usr/bin/env python3
"""Run the trained YOLO OBB parking-spot model on a live laptop webcam.

Save this file beside model.py in the ``computer vision`` folder.
Run from the project root:
    python "computer vision\\webcam_test.py"

Optional:
    python "computer vision\\webcam_test.py" --camera 1
    python "computer vision\\webcam_test.py" --weights "computer vision\\runs\\obb\\parking-spots\\weights\\best.pt"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_WEIGHTS = BASE_DIR / "runs" / "obb" / "parking-spots" / "weights" / "best.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test the trained parking-spot OBB model on a webcam")
    parser.add_argument(
        "--weights",
        default=str(DEFAULT_WEIGHTS),
        help=f"path to trained best.pt (default: {DEFAULT_WEIGHTS})",
    )
    parser.add_argument("--camera", type=int, default=1, help="webcam device index (default: )")
    parser.add_argument("--imgsz", type=int, default=960, help="inference image size (default: 960)")
    parser.add_argument("--conf", type=float, default=0.25, help="minimum confidence threshold (default: 0.25)")
    parser.add_argument("--device", type=int, default=0, help="CUDA GPU index (default: 0)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    weights_path = Path(args.weights).expanduser().resolve()

    if not weights_path.is_file():
        print(f"ERROR: Trained weights not found:\n  {weights_path}")
        print("Check where your training run saved weights/ best.pt, or pass the correct path with --weights.")
        return 1

    try:
        import cv2
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"ERROR: Missing required package: {exc.name or exc}")
        print("Install dependencies in the same Python environment you used for training: pip install ultralytics opencv-python")
        return 1

    if not torch.cuda.is_available():
        print("ERROR: CUDA is not available to PyTorch. Webcam inference was stopped rather than using the CPU.")
        print("Check your NVIDIA driver and CUDA-enabled PyTorch installation.")
        return 1

    if args.device < 0 or args.device >= torch.cuda.device_count():
        print(f"ERROR: CUDA device {args.device} is unavailable; PyTorch sees {torch.cuda.device_count()} GPU(s).")
        return 1

    torch.cuda.set_device(args.device)
    print(f"Using GPU {args.device}: {torch.cuda.get_device_name(args.device)}")
    print(f"Loading trained weights: {weights_path}")
    model = YOLO(str(weights_path))

    if getattr(model, "task", None) != "obb":
        print(f"ERROR: This checkpoint reports task={getattr(model, 'task', 'unknown')!r}, not 'obb'.")
        print("Use the best.pt produced by your YOLO OBB training run.")
        return 1

    # CAP_DSHOW often opens webcams more reliably on Windows; fall back to default backend if needed.
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(args.camera)

    if not cap.isOpened():
        print(f"ERROR: Could not open camera index {args.camera}.")
        print("Close apps using the camera, check Windows camera permissions, or try --camera 1.")
        return 1

    print("Live camera started. Press Q in the video window to quit.")
    window_name = "Parking Spot Detection - press Q to quit"

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("WARNING: Could not read a frame from the camera.")
                break

            # Explicit device=args.device forces inference onto the selected CUDA GPU.
            predictions = model.predict(
                source=frame,
                imgsz=args.imgsz,
                conf=args.conf,
                device=args.device,
                verbose=False,
            )
            annotated = predictions[0].plot()
            cv2.imshow(window_name, annotated)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:  # Q or Esc
                break
    except KeyboardInterrupt:
        print("\nStopping webcam inference...")
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
