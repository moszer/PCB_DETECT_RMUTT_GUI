import os
import re

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _natural_key(name: str):
    """Sort key so board_2.jpg comes before board_10.jpg."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def list_images_in_folder(folder: str) -> list:
    """Absolute paths of every supported image directly inside `folder`,
    in natural filename order (non-recursive)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    images = []
    for name in sorted(names, key=_natural_key):
        if not name.lower().endswith(IMAGE_EXTENSIONS):
            continue
        path = os.path.abspath(os.path.join(folder, name))
        if os.path.isfile(path):
            images.append(path)
    return images


def resolve_asset_path(script_root: str, project_root: str, filename: str, create_in_project: bool = False) -> str:
    candidates = [
        os.path.join(script_root, filename),
        os.path.join(project_root, filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    if create_in_project:
        return os.path.join(project_root, filename)
    return candidates[0]
