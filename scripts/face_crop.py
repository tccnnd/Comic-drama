from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

try:  # OpenCV is optional. Without it we still produce a usable center crop.
    import cv2
    import numpy as np

    _HAS_CV2 = True
except ImportError:  # pragma: no cover - depends on local optional dependency
    cv2 = None
    np = None
    _HAS_CV2 = False


OUTPUT_SIZE = 512
MIN_INPUT_SIZE = 256

EXPAND_TOP = 0.6
EXPAND_BOTTOM = 1.0
EXPAND_LEFT = 0.5
EXPAND_RIGHT = 0.5


def preprocess_reference_image(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    input_path = Path(input_path)
    output_path = Path(output_path)
    warnings: list[str] = []

    try:
        image = Image.open(input_path).convert("RGB")
    except Exception as exc:
        return {
            "ok": False,
            "output_path": "",
            "crop_method": "failed",
            "face_box": None,
            "crop_box": None,
            "output_size": [0, 0],
            "warnings": [f"Unable to open reference image: {exc}"],
        }

    width, height = image.size
    if width < MIN_INPUT_SIZE or height < MIN_INPUT_SIZE:
        return {
            "ok": False,
            "output_path": "",
            "crop_method": "failed",
            "face_box": None,
            "crop_box": None,
            "output_size": [width, height],
            "warnings": [
                f"Reference image is too small: {width}x{height}; minimum is {MIN_INPUT_SIZE}x{MIN_INPUT_SIZE}.",
            ],
        }

    face_box = None
    crop_box = None
    crop_method = "center_fallback"

    if _HAS_CV2:
        face_box = _detect_largest_face(image)
        if face_box:
            crop_box = _expand_face_to_headshoulder(face_box, width, height)
            crop_method = "face_detect"
        else:
            warnings.append("No face detected; used center crop fallback.")
    else:
        warnings.append("OpenCV is not installed; used center crop fallback.")

    if crop_box is None:
        crop_box = _center_square_crop(width, height)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cropped = image.crop(crop_box)
    standardized = cropped.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
    standardized.save(output_path, "PNG", optimize=True)

    return {
        "ok": True,
        "output_path": str(output_path),
        "crop_method": crop_method,
        "face_box": list(face_box) if face_box else None,
        "crop_box": list(crop_box) if crop_box else None,
        "output_size": [OUTPUT_SIZE, OUTPUT_SIZE],
        "warnings": warnings,
    }


def _detect_largest_face(image: Image.Image) -> tuple[int, int, int, int] | None:
    if not _HAS_CV2 or cv2 is None or np is None:
        return None

    rgb = np.array(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return None

    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(60, 60),
    )
    if len(faces) == 0:
        return None

    largest = max(faces, key=lambda item: int(item[2]) * int(item[3]))
    return tuple(int(value) for value in largest)


def _expand_face_to_headshoulder(
    face_box: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    face_x, face_y, face_width, face_height = face_box
    x1 = face_x - int(face_width * EXPAND_LEFT)
    y1 = face_y - int(face_height * EXPAND_TOP)
    x2 = face_x + face_width + int(face_width * EXPAND_RIGHT)
    y2 = face_y + face_height + int(face_height * EXPAND_BOTTOM)

    side = max(x2 - x1, y2 - y1)
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    x1 = center_x - side // 2
    y1 = center_y - side // 2
    x2 = x1 + side
    y2 = y1 + side

    if x1 < 0:
        x2 -= x1
        x1 = 0
    if y1 < 0:
        y2 -= y1
        y1 = 0
    if x2 > image_width:
        x1 -= x2 - image_width
        x2 = image_width
    if y2 > image_height:
        y1 -= y2 - image_height
        y2 = image_height

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(image_width, x2)
    y2 = min(image_height, y2)
    return (x1, y1, x2, y2)


def _center_square_crop(image_width: int, image_height: int) -> tuple[int, int, int, int]:
    side = min(image_width, image_height)
    x1 = (image_width - side) // 2
    y1 = (image_height - side) // 2
    return (x1, y1, x1 + side, y1 + side)
