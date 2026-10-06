"""Small versions of stored station images, for fast previews.

Point images are full-resolution PNGs (~19 MB at 3840x3840): too slow to show over Tailscale
or on a phone. The UI shows a tiny blurred placeholder (LQIP, ~1 KB, inline in /meta) at
once, then a JPEG preview from /thumb, and the original only when zoomed in.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..core.thumbs import WIDTHS, lqip, original_size, resized
from .inspection import _storage_image

router = APIRouter(prefix="/api/media", tags=["media"])

_meta_cache: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()


@router.get("/thumb")
def thumb(url: str = Query(..., max_length=1024), w: int = Query(1600)):
    """A JPEG preview of a stored image (`w` one of 32, 480, 1600, 2400)."""
    if w not in WIDTHS:
        raise HTTPException(400, f"w must be one of {WIDTHS}")
    try:
        out = resized(_storage_image(url), w)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # The cache key includes the source's mtime, but the URL does not: revalidate after a day.
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/meta")
def meta(url: str = Query(..., max_length=1024)):
    """Original size plus an inline LQIP (data: URL): enough to lay out and draw boxes at once."""
    path = _storage_image(url)
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _meta_cache:
        _meta_cache.move_to_end(key)
        return _meta_cache[key]
    try:
        width, height = original_size(path)
        result = {"width": width, "height": height, "lqip": lqip(path)}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"Image could not be read: {exc}")
    _meta_cache[key] = result
    if len(_meta_cache) > 4000:
        _meta_cache.popitem(last=False)
    return result
