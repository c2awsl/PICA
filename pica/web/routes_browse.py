import sys
from pathlib import Path

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/api/browse")
async def browse_directory(path: str = Query("")):
    try:
        if not path:
            return _list_drives()

        p = Path(path)
        if not p.is_dir():
            return {"current": path, "parent": None, "dirs": [], "error": "目录不存在"}

        parent = str(p.parent) if p.parent != p else None
        dirs = sorted(
            [str(d.name) for d in p.iterdir() if d.is_dir() and not d.name.startswith("$")],
            key=lambda x: x.lower(),
        )
        return {
            "current": str(p),
            "parent": parent,
            "dirs": dirs,
            "error": None,
        }
    except PermissionError:
        return {"current": path, "parent": None, "dirs": [], "error": "无权限访问"}
    except Exception as e:
        return {"current": path, "parent": None, "dirs": [], "error": str(e)}


def _list_drives():
    drives = []
    if sys.platform == "win32":
        import string
        from ctypes import windll
        buf = windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if buf & 1:
                drives.append(f"{letter}:\\")
            buf >>= 1
    else:
        drives.append("/")
    return {"current": "", "parent": None, "dirs": drives, "error": None, "is_root": True}
