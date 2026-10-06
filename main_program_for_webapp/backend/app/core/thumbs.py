"""Resized JPEG copies of stored images (previews and LQIP placeholders), cached on disk."""
from __future__ import annotations

import base64
import hashlib
import logging
import threading
from pathlib import Path
from typing import Dict, Tuple

import cv2

from ..config import STORAGE_DIR

logger = logging.getLogger(__name__)

THUMB_DIR = STORAGE_DIR / ".thumbs"
WIDTHS = (32, 480, 1600, 2400)  # only these, so the cache stays bounded
LQIP_WIDTH = 32
PREVIEW_WIDTH = 1600
_locks: Dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _key(path: Path, width: int) -> str:
    st = path.stat()
    return hashlib.sha1(f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{width}".encode()).hexdigest()


def resized(path: Path, width: int) -> Path:
    """JPEG of the image at most `width` px wide (never enlarged), made once and cached."""
    key = _key(path, width)
    out = THUMB_DIR / key[:2] / f"{key}.jpg"
    if out.is_file():
        return out
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:  # several viewers asking at once: resize once
        if not out.is_file():
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("Image could not be read")
            h, w = img.shape[:2]
            if w > width:
                img = cv2.resize(img, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.stem + ".tmp.jpg")
            quality = 70 if width <= LQIP_WIDTH else 82
            if not cv2.imwrite(str(tmp), img, [int(cv2.IMWRITE_JPEG_QUALITY), quality, int(cv2.IMWRITE_JPEG_PROGRESSIVE), 1]):
                raise IOError("Could not write the preview")
            tmp.replace(out)
    with _guard:
        _locks.pop(key, None)
    return out


def original_size(path: Path) -> Tuple[int, int]:
    """Pixel size from the file header (no full decode of a 19 MB PNG)."""
    from PIL import Image

    with Image.open(path) as im:
        return int(im.width), int(im.height)


def lqip(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(resized(path, LQIP_WIDTH).read_bytes()).decode()


def warm(path: Path) -> None:
    """Make the placeholder and the preview in the background, right after an image is saved."""
    def run():
        try:
            resized(path, LQIP_WIDTH)
            resized(path, PREVIEW_WIDTH)
        except Exception:
            logger.debug("Preview of %s not made", path, exc_info=True)

    threading.Thread(target=run, name="thumbs", daemon=True).start()
