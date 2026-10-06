"""
Runs code straight from the methanol reactor notebooks, so the website uses the notebooks' own
physics, data cleaning and model definitions (restart the backend / retrain after editing them).
"""

import ast
import contextlib
import io
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "DATA.xlsx"
PHYSICS_NB = ROOT / "Physics Model_1.ipynb"
SERIAL_NB = ROOT / "A1_Serial Digital Twin.ipynb"
PARALLEL_NB = ROOT / "Parallel Digital Twin.ipynb"
PINN_NB = ROOT / "PINN Digital Twin.ipynb"


def code_cells(notebook: Path) -> list[str]:
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    return [
        "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        for c in cells
        if c["cell_type"] == "code"
    ]


@contextlib.contextmanager
def _in_notebook_dir():
    # The notebooks open DATA.xlsx by relative path.
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(cwd)


def _namespace() -> dict:
    return {"__name__": "__notebook__", "display": lambda *a, **k: None}


def run_notebook(notebook: Path, skip=("input(",), patches: dict[str, str] | None = None, quiet=True) -> dict:
    """Execute every code cell in order, like Run All, and return the resulting namespace.

    Cells containing any `skip` text (the interactive input() loops) are left out, and `patches`
    replaces exact source snippets (used to change training settings).
    """
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
    """Import the notebook's modules, constants and the named functions/classes, without training.

    Top-level imports and assignments run in order; an assignment that depends on training-time
    variables (data frames, fitted models, ...) raises and is skipped. Functions and
    classes are only defined when listed in `names`. `preset` values are applied last.
    """
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
