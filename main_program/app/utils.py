import os


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
