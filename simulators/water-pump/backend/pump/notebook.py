"""
Runs code straight from the water pump notebooks, so the website uses the notebooks' own
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
SERIAL_NB = ROOT / "WaterPump_Serial_Hybrid_0.005.ipynb"
PARALLEL_NB = ROOT / "WaterPump_Parallel_Hybrid_Residual_Correction_0.005.ipynb"
PINN_NB = ROOT / "PINN Model(0.005).ipynb"


def code_cells(notebook: Path) -> list[str]:
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    return [
        "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        for c in cells
        if c["cell_type"] == "code"
    ]


@contextlib.contextmanager
def _in_notebook_dir():
    # The notebooks open PumpData_0.005.xlsx by relative path.
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(cwd)


def _namespace() -> dict:
    return {"__name__": "__notebook__", "display": lambda *a, **k: None}


def run_notebook(notebook: Path, skip=(), patches: dict[str, str] | None = None, quiet=True) -> dict:
    """Execute every code cell in order, like Run All, and return the resulting namespace.

    Cells containing any `skip` text are left out, and `patches` replaces exact source snippets
    (used to change training settings).
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
    """Run the notebook's imports and define the named functions/classes, without loading data or training.

    `preset` (the trained objects) is applied first, so default arguments such as
    `model=efficiency_model` bind to the trained model.
    """
    ns = _namespace()
    ns.update(preset)
    with contextlib.redirect_stdout(io.StringIO()):
        for src in code_cells(notebook):
            for node in ast.parse(src).body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name not in names:
                        continue
                elif not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(notebook), "exec"), ns)
    missing = names - ns.keys()
    if missing:
        raise RuntimeError(f"{notebook.name}: definitions not found: {sorted(missing)}")
    return ns
