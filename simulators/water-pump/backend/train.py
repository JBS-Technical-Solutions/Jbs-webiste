"""
Train the water pump digital twins from PumpData_0.005.xlsx and save them to backend/artifacts/.

The notebooks themselves are executed (Run All), so data cleaning, the train/test split and model
settings are exactly the notebooks':
  - Serial:   WaterPump_Serial_Hybrid_0.005.ipynb  (P_hyd → LinearRegression efficiency → P_hyd / η)
  - Parallel: WaterPump_Parallel_Hybrid_Residual_Correction_0.005.ipynb  (P_hyd / η̄ + residual ML)
  - PINN:     PINN Model(0.005).ipynb  (same network, loss and optimiser; PINN_EPOCHS instead of 5000)

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

from pump.notebook import PARALLEL_NB, PINN_NB, SERIAL_NB, run_notebook
from pump.twins import INPUT_COLS, TARGET_COL, Twins, parallel_namespace, pinn_namespace, pinn_predict, serial_namespace

warnings.filterwarnings("ignore")

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
PINN_EPOCHS = 20000


def score(y_true, y_pred) -> dict:
    return {"r2": float(r2_score(y_true, y_pred)), "mae": float(mean_absolute_error(y_true, y_pred))}


def check_same(name: str, notebook_pred, website_pred, df, tol=1e-6) -> None:
    """The website predictor must reproduce the notebook's own prediction."""
    rows = [tuple(float(v) for v in r) for r in df[INPUT_COLS].head(5).itertuples(index=False)]
    diff = max(abs(notebook_pred(*r) - website_pred(*r)) for r in rows)
    print(f"  [{name}] website vs notebook brake power: max |diff| = {diff:.2e} kW")
    if not diff < tol:
        raise RuntimeError(f"{name}: website predictor does not match the notebook")


def train_serial():
    # The notebook's last cell saves its own .pkl next to the notebook; the artifact below replaces it.
    ns = run_notebook(SERIAL_NB, skip=("joblib.dump(",))
    artifact = {"efficiency_model": ns["efficiency_model"]}
    joblib.dump(artifact, ARTIFACTS / "serial.joblib")
    website = serial_namespace(artifact)
    check_same(
        "serial",
        lambda *a: ns["serial_hybrid_predict"](*a)["Predicted Brake Power (kW)"],
        lambda *a: website["serial_hybrid_predict"](*a)["Predicted Brake Power (kW)"],
        ns["df_test"],
    )
    test = ns["df_test"]
    return ns, {
        "selected": "P_hyd (physics) → LinearRegression efficiency → P_hyd / η",
        "test": score(test[TARGET_COL], test["Hybrid Brake Power"]),
    }


def train_parallel():
    ns = run_notebook(PARALLEL_NB)
    artifact = {"residual_model": ns["residual_model"], "physics_efficiency": float(ns["physics_efficiency"])}
    joblib.dump(artifact, ARTIFACTS / "parallel.joblib")
    website = parallel_namespace(artifact)
    check_same(
        "parallel",
        lambda *a: ns["residual_hybrid_predict"](*a)["Hybrid Brake Power (kW)"],
        lambda *a: website["residual_hybrid_predict"](*a)["Hybrid Brake Power (kW)"],
        ns["test_df"],
    )
    test = ns["test_df"]
    return {
        "selected": f"P_hyd / η̄ (η̄ = {artifact['physics_efficiency']:.6f}) + LinearRegression residual",
        "physics_efficiency": artifact["physics_efficiency"],
        "test": score(test[TARGET_COL], test["Hybrid Brake Power"]),
    }


def train_pinn():
    torch.manual_seed(42)
    ns = run_notebook(PINN_NB, skip=("perm_scores",), patches={"epochs = 5000": f"epochs = {PINN_EPOCHS}"})
    model = ns["model"]
    model.eval()
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    torch.save(state, ARTIFACTS / "pinn.pt")
    scaler = {"scaler": ns["scaler_X"], "features": list(ns["features"])}
    joblib.dump(scaler, ARTIFACTS / "pinn_scaler.joblib")

    website = pinn_namespace(state, scaler["scaler"], scaler["features"])
    test_df = ns["test_df"]
    notebook_pred = dict(zip(map(tuple, test_df[INPUT_COLS].to_numpy(float)), ns["y_test_predicted"]))
    # float32 network: batched (notebook) vs single-row (website) inference differ in the last bits.
    check_same("pinn", lambda *a: float(notebook_pred[a]), lambda *a: pinn_predict(website, *a)[0], test_df, tol=1e-3)
    return {
        "selected": f"PumpPINN (4→32→32→16 tanh, brake + efficiency heads) × {PINN_EPOCHS} epochs",
        "test": score(ns["y_test_actual"], ns["y_test_predicted"]),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(exist_ok=True)
    np.random.seed(42)
    t0 = time.time()

    print("Serial hybrid (runs the notebook)...")
    serial_ns, serial = train_serial()
    df = serial_ns["df"]

    print("Parallel hybrid (runs the notebook)...")
    parallel = train_parallel()

    print(f"PINN ({PINN_EPOCHS} epochs on CPU)...")
    pinn = train_pinn()

    keys = {"Water Flow": "flow_kgh", "Water inlet Pressure": "P_in_bar",
            "Water outlet pressure": "P_out_bar", "Water Density": "rho"}
    outputs = {"brake_kW": TARGET_COL, "hydraulic_kW": "Hydraulic Power (kW)", "efficiency": "Observed Efficiency"}
    info = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "test_rows": int(len(serial_ns["df_test"])),
        "versions": {"sklearn": sklearn.__version__, "torch": torch.__version__},
        "training_ranges": {k: {"min": float(df[c].min()), "max": float(df[c].max())} for c, k in keys.items()},
        "output_ranges": {k: {"min": float(df[c].min()), "max": float(df[c].max())} for k, c in outputs.items()},
        "models": {"serial": serial, "parallel": parallel, "pinn": pinn},
    }
    (ARTIFACTS / "metrics.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    Twins(ARTIFACTS).predict("pinn", 13000, 6.013, 175, 999.9)

    print("\nTest-set brake power:")
    for k, v in info["models"].items():
        print(f"  {k:>9s}  R² {v['test']['r2']:.6f}   MAE {v['test']['mae']:.4f} kW")
    print(f"\nSaved to {ARTIFACTS}  in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
