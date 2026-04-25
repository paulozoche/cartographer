from pathlib import Path
import sys

BRANCH = sys.argv[1] if len(sys.argv) > 1 else "."

IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
    "runtime", "uploads", ".cache", "htmlcov", ".idea", ".vscode",
}

IGNORE_FILES = {"__init__.py", ".DS_Store"}

IGNORE_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".sqlite", ".db", ".csv", ".tsv",
    ".xlsx", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg",
    ".webp", ".svg",
}

def ignore(path: Path) -> bool:
    return (
        any(part in IGNORE_DIRS for part in path.parts)
        or path.name in IGNORE_FILES
        or path.suffix in IGNORE_SUFFIXES
    )

def tree(path: Path, prefix: str = ""):
    if not path.exists():
        print(f"não encontrado: {path}")
        return

    children = [p for p in path.iterdir() if not ignore(p)]
    children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

    for i, child in enumerate(children):
        last = i == len(children) - 1
        print(prefix + ("└── " if last else "├── ") + child.name)
        if child.is_dir():
            tree(child, prefix + ("    " if last else "│   "))

root = Path(BRANCH)
print(root)
tree(root)
