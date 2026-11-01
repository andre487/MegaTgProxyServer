from __future__ import annotations

import os
import subprocess
from pathlib import Path


def find_hooks(root: Path, event: str) -> list[Path]:
    hooks_dir = root / ".hooks"
    candidates = [hooks_dir / event]
    event_dir = hooks_dir / f"{event}.d"
    if event_dir.is_dir():
        candidates.extend(sorted(path for path in event_dir.iterdir() if path.is_file()))

    return [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]


def run_hooks(root: Path, event: str, inventory: Path, ansible_inventory: Path,
              links_file: Path | None = None, limit: str | None = None) -> int:
    environment = os.environ.copy()
    environment.update(
        {
            "MEGATG_EVENT": event,
            "MEGATG_INVENTORY": str(inventory.resolve()),
            "MEGATG_ANSIBLE_INVENTORY": str(ansible_inventory.resolve()),
            "MEGATG_ROOT": str(root.resolve()),
            "MEGATG_LINKS_FILE": str(links_file.resolve()) if links_file else "",
            "MEGATG_LIMIT": limit or "",
        }
    )
    for hook in find_hooks(root, event):
        print(f"Running hook: {hook}", flush=True)
        result = subprocess.run([str(hook)], cwd=root, env=environment)
        if result.returncode:
            return result.returncode
    return 0
