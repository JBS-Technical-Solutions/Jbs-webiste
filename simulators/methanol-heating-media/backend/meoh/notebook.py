"""Runs code from the methanol heating-media notebooks."""

import ast
import contextlib
import io
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[2]
PHYSICS_NB = ROOT / "Physics_HeatingMedia.ipynb"
SERIAL_NB = ROOT / "Serial_HeatingMedia.ipynb"
PARALLEL_NB = ROOT / "Parallel_HeatingMedia.ipynb"
PINN_NB = ROOT / "PINN_HeatingMedia.ipynb"


def code_cells(notebook: Path) -> list[str]:
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    return [
        "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        for c in cells
        if c["cell_type"] == "code"
    ]


@contextlib.contextmanager
def _in_notebook_dir():
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(cwd)


def _namespace() -> dict:
    return {"__name__": "__notebook__", "display": lambda *a, **k: None}


def run_notebook(notebook: Path, skip=("input(",), patches: dict[str, str] | None = None, quiet=True) -> dict:
    ns = _namespace()
    patches = dict(patches or {})
    with _in_notebook_dir():
        for src in code_cells(notebook):
            for old, new in list(patches.items()):
                if old in src:
                    src = src.replace(old, new)
                    patches.pop(old)
            if not src.strip() or any(s in src for s in skip):
                continue
            with contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext():
                exec(compile(src, str(notebook), "exec"), ns)
    if patches:
        raise RuntimeError(f"{notebook.name}: patch targets not found: {list(patches)}")
    return ns


def load_definitions(notebook: Path, names: set[str], **preset) -> dict:
    ns = _namespace()
    with _in_notebook_dir(), contextlib.redirect_stdout(io.StringIO()):
        for src in code_cells(notebook):
            for node in ast.parse(src).body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name not in names:
                        continue
                elif not isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
                    continue
                code = compile(ast.Module(body=[node], type_ignores=[]), str(notebook), "exec")
                try:
                    exec(code, ns)
                except Exception:
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
                        raise
    missing = names - ns.keys()
    if missing:
        raise RuntimeError(f"{notebook.name}: definitions not found: {sorted(missing)}")
    ns.update(preset)
    return ns
