"""
Train the methanol reactor digital twins from DATA_clean.csv and save them to backend/artifacts/.

The revised notebooks are executed (Run All, minus the interactive input() cells), so data
cleaning, the train/test split and model settings are exactly the notebooks':
  - Physics:  revised_Physics Model_1.ipynb                 (no training; test-set scores only)
  - Serial:   Revised_A2_Serial Digital Twin.ipynb          (learned LHHW rate inside the ODE)
  - Parallel: Parallel_Residual_Hybrid_Digital_Twin.ipynb   (physics baseline + ML residual)
  - PINN:     Revised_PINN Digital Twin.ipynb               (notebook settings: 40 cases × 120 epochs)

Run:  .venv\\Scripts\\python train.py
"""

import json
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import sklearn
import torch
from sklearn.metrics import mean_absolute_error, r2_score

from meoh.notebook import PARALLEL_NB, PINN_NB, SERIAL_NB, run_notebook
from meoh.twins import (
    INPUT_COLS, OUTPUT_COLS, parallel_namespace, physics_namespace, pinn_namespace, serial_namespace,
)

warnings.filterwarnings("ignore")

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def scores(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    ok = np.isfinite(y_true).all(axis=1) & np.isfinite(y_pred).all(axis=1)
    return {
        c: {
            "r2": float(r2_score(y_true[ok, i], y_pred[ok, i])),
            "mae": float(mean_absolute_error(y_true[ok, i], y_pred[ok, i])),
        }
        for i, c in enumerate(OUTPUT_COLS)
    }


def predict_rows(ns: dict, df) -> np.ndarray:
    rows = []
    for r in df[INPUT_COLS].itertuples(index=False):
        try:
            out = ns["predict_outputs"](float(r[0]), float(r[1]), float(r[2]))
            rows.append([float(out[c]) for c in OUTPUT_COLS])
        except Exception:
            rows.append([np.nan] * len(OUTPUT_COLS))
    return np.asarray(rows)


def check_same(name: str, notebook_ns: dict, website_ns: dict, df, tol: float = 1e-6) -> None:
    """The website predictor must reproduce the notebook's own predict_outputs()."""
    sample = df.head(5)
    diff = np.nanmax(np.abs(predict_rows(notebook_ns, sample) - predict_rows(website_ns, sample)))
    print(f"  [{name}] website vs notebook predict_outputs: max |diff| = {diff:.2e}")
    if not np.isfinite(diff) or diff > tol:
        raise RuntimeError(f"{name}: website predictor does not match the notebook")


def train_serial():
    ns = run_notebook(SERIAL_NB)
    artifact = {"kinetics_model": ns["kinetics_model"]}
    joblib.dump(artifact, ARTIFACTS / "serial.joblib")
    check_same("serial", ns, serial_namespace(artifact), ns["test_df"])
    metrics = scores(ns["Y_excel"], ns["Y_learn"])
    return ns, {"selected": "MLP reaction rate inside the physics ODE", "test": metrics}


def train_parallel():
    ns = run_notebook(PARALLEL_NB)
    artifact = {"ETA": float(ns["ETA"]), "residual_model": ns["residual_model"]}
    joblib.dump(artifact, ARTIFACTS / "parallel.joblib")
    check_same("parallel", ns, parallel_namespace(artifact), ns["test_df"])
    metrics = scores(ns["Y_excel_test"], ns["Y_hyb_test"])
    return {"selected": f"Physics (η = {artifact['ETA']:.3e}) + HistGradientBoosting residual",
            "test": metrics}


def train_pinn(test_df):
    ns = run_notebook(PINN_NB)
    model = ns["model"]
    model.eval()
    refs = {k: float(ns[k]) for k in ("T_REF", "P_REF_BAR", "F_REF", "Q_REF")}
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    torch.save(state, ARTIFACTS / "pinn.pt")
    (ARTIFACTS / "pinn_refs.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")

    website = pinn_namespace(state, refs)
    check_same("pinn", ns, website, test_df.head(5), tol=1e-3)
    metrics = scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(website, test_df))
    n_cases, epochs = int(ns["N_TRAIN_CASES"]), int(ns["EPOCHS"])
    return {"selected": f"ReactorPINN (4×64 tanh), {n_cases} cases × {epochs} epochs",
            "test": metrics}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(exist_ok=True)
    np.random.seed(42)
    torch.manual_seed(42)
    t0 = time.time()

    print("Serial hybrid (runs the notebook: rate labels + learned kinetics)...")
    serial_ns, serial = train_serial()
    df, test_df = serial_ns["df"], serial_ns["test_df"]

    print("Physics model on the test set...")
    physics = {
        "selected": "Physics Model_1.ipynb (no ML)",
        "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(physics_namespace(), test_df)),
    }

    print("Parallel hybrid (runs the notebook)...")
    parallel = train_parallel()

    print("PINN (notebook settings, on CPU)...")
    pinn = train_pinn(test_df)

    info = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "test_rows": int(len(test_df)),
        "versions": {"sklearn": sklearn.__version__, "torch": torch.__version__},
        "reactor": {
            "reaction": "CH3OH → CO + 2H2",
            "D_m": float(serial_ns["D"]), "L_m": float(serial_ns["L"]),
            "h_heat_W_m2K": float(serial_ns["h_o"]),
            "T_heat_C": float(serial_ns["T_heat_C"]),
            "epsilon": float(serial_ns["epsilon"]), "dp_m": float(serial_ns["dp"]),
        },
        "training_ranges": {c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in INPUT_COLS},
        "output_ranges": {c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in OUTPUT_COLS},
        "models": {"physics": physics, "serial": serial, "parallel": parallel, "pinn": pinn},
    }
    (ARTIFACTS / "metrics.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nTest-set R² per output:")
    print("  " + " ".join(f"{c:>13s}" for c in ["model"] + OUTPUT_COLS))
    for k, v in info["models"].items():
        print("  " + f"{k:>13s} " + " ".join(f"{v['test'][c]['r2']:13.4f}" for c in OUTPUT_COLS))
    print(f"\nSaved to {ARTIFACTS}  in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
