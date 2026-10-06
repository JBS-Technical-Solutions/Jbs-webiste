"""
Train the methanol reactor digital twins from DATA.xlsx and save them to backend/artifacts/.

The notebooks themselves are executed (Run All, minus the interactive input() cells), so data
cleaning, the train/test split, η calibration and model settings are exactly the notebooks':
  - Physics:  Physics Model_1.ipynb        (no training; test-set scores only)
  - Serial:   A1_Serial Digital Twin.ipynb  (calibrated physics + HistGradientBoosting residuals)
  - Parallel: Parallel Digital Twin.ipynb   (calibrated physics ‖ HistGradientBoosting, blend weights)
  - PINN:     PINN Digital Twin.ipynb       (same network and loss; trained on every training case
                                             for PINN_EPOCHS epochs instead of 40 cases × 120 epochs)

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
PINN_EPOCHS = 300


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


def check_same(name: str, notebook_ns: dict, website_ns: dict, df) -> None:
    """The website predictor must reproduce the notebook's own predict_outputs()."""
    sample = df.head(5)
    diff = np.nanmax(np.abs(predict_rows(notebook_ns, sample) - predict_rows(website_ns, sample)))
    print(f"  [{name}] website vs notebook predict_outputs: max |diff| = {diff:.2e}")
    if not diff < 1e-6:
        raise RuntimeError(f"{name}: website predictor does not match the notebook")


def train_serial():
    ns = run_notebook(SERIAL_NB)
    artifact = {"ETA": float(ns["ETA"]), "model": ns["multi_residual_model"]}
    joblib.dump(artifact, ARTIFACTS / "serial.joblib")
    check_same("serial", ns, serial_namespace(artifact), ns["test_df"])
    metrics = scores(ns["Y_excel_test"], ns["Y_hat_test"])
    return ns, {"selected": f"Calibrated physics (η = {artifact['ETA']:.3e}) + HistGradientBoosting residuals",
                "test": metrics}


def train_parallel():
    ns = run_notebook(PARALLEL_NB)
    artifact = {"ETA": float(ns["ETA"]), "ml_model": ns["ml_model"], "W": np.asarray(ns["W"], float)}
    joblib.dump(artifact, ARTIFACTS / "parallel.joblib")
    check_same("parallel", ns, parallel_namespace(artifact), ns["test_df"])
    metrics = scores(ns["Y_excel_test"], ns["Y_par_test"])
    weights = {c: round(float(w), 4) for c, w in zip(OUTPUT_COLS, artifact["W"])}
    return {"selected": f"w·physics(η) + (1−w)·HistGradientBoosting", "weights_physics": weights,
            "test": metrics}


def pinn_batch_loss(ns: dict, model, u, y, n_colloc: int, z_col=None):
    """The notebook's pinn_loss_for_case, evaluated for a batch of cases at once.

    Every case gets the same number of collocation and measurement points, so the batch-mean
    loss equals the mean of the per-case losses that the notebook's training loop averages.
    """
    L, F_REF, Q_REF, P_ATM = ns["L"], ns["F_REF"], ns["Q_REF"], ns["P_ATM_BAR"]
    B, n_m = u.shape[0], len(ns["MEASUREMENT_POSITIONS_M"])

    if z_col is None:
        z_col = torch.rand(B * n_colloc, 1) * L
    z_col.requires_grad_(True)
    states = model(z_col, u.repeat_interleave(n_colloc, dim=0))
    rhs = ns["ode_rhs"](states, model.eta(states["u_n"]))
    d = ns["autodiff_dz"](states, z_col)
    L_phys = (
        torch.mean(((d["F_CH3OH"] - rhs["dF_CH3OH"]) / F_REF) ** 2)
        + torch.mean(((d["F_CO"] - rhs["dF_CO"]) / F_REF) ** 2)
        + torch.mean(((d["F_H2"] - rhs["dF_H2"]) / F_REF) ** 2)
        + torch.mean(((d["T_C"] - rhs["dT_C"]) / 50.0) ** 2)
        + torch.mean(((d["P"] - rhs["dP"]) / 1e4) ** 2)
        + torch.mean(((d["Q_kW"] - rhs["dQ_kW"]) / Q_REF) ** 2)
    )

    z_m = torch.tensor(ns["MEASUREMENT_POSITIONS_M"], dtype=torch.float32).view(-1, 1).repeat(B, 1)
    z_m.requires_grad_(True)
    st_m = model(z_m, u.repeat_interleave(n_m, dim=0))
    L_T = torch.mean(((st_m["T_C"].view(B, n_m) - y[:, 0:5]) / 50.0) ** 2)

    st_L = model(torch.full((B, 1), float(L), requires_grad=True), u)
    P_out_bar_g = (st_L["P"] / 1.0e5 - P_ATM).view(-1)
    X_pct = ((st_L["F_in"] - st_L["F_CH3OH"]) / st_L["F_in"] * 100.0).view(-1)
    Q_kW = st_L["Q_kW"].view(-1)
    L_data = (
        L_T
        + torch.mean((P_out_bar_g - y[:, 5]) ** 2)
        + torch.mean((Q_kW - y[:, 6]) ** 2)
        + torch.mean((X_pct - y[:, 7]) ** 2)
    )

    st0 = model(torch.zeros(B, 1, requires_grad=True), u)
    L_bc = torch.mean(
        ((st0["T_C"].view(-1) - u[:, 0]) / 50.0) ** 2
        + (st0["F_CO"].view(-1) / F_REF) ** 2
        + (st0["Q_kW"].view(-1) / Q_REF) ** 2
    )
    return 1.0 * L_data + 0.05 * L_phys + 0.1 * L_bc


def train_pinn(test_df):
    # Definitions, data, scaling and the untrained network come from the notebook; its per-case
    # training cell is replaced by the batched loop below (same optimiser, batch size and clipping).
    ns = run_notebook(PINN_NB, skip=("input(", "optimizer = torch.optim", "train_cases", "N_TEST_EVAL"))
    model, train_df = ns["model"], ns["train_df"]
    batch_cases, n_colloc = 8, 16

    u_all = torch.tensor(train_df[INPUT_COLS].to_numpy(), dtype=torch.float32)
    y_all = torch.tensor(train_df[OUTPUT_COLS].to_numpy(), dtype=torch.float32)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    n = len(train_df)
    for epoch in range(1, PINN_EPOCHS + 1):
        model.train()
        idx = np.random.permutation(n)
        total, n_batches = 0.0, 0
        for s in range(0, n, batch_cases):
            b = idx[s:s + batch_cases]
            optimizer.zero_grad()
            loss = pinn_batch_loss(ns, model, u_all[b], y_all[b], n_colloc)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            total += float(loss.detach())
            n_batches += 1
        if epoch == 1 or epoch % 25 == 0:
            print(f"  [pinn] epoch {epoch:4d}  loss={total / n_batches:.4e}")

    model.eval()
    refs = {k: float(ns[k]) for k in ("T_REF", "P_REF_BAR", "F_REF", "Q_REF")}
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    torch.save(state, ARTIFACTS / "pinn.pt")
    (ARTIFACTS / "pinn_refs.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")

    website = pinn_namespace(state, refs)
    metrics = scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(website, test_df))
    return {"selected": f"ReactorPINN (4×64 tanh) on all {n} training cases × {PINN_EPOCHS} epochs",
            "test": metrics}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(exist_ok=True)
    np.random.seed(42)
    torch.manual_seed(42)
    t0 = time.time()

    print("Serial hybrid (runs the notebook: η calibration + physics on every row + residual ML)...")
    serial_ns, serial = train_serial()
    df, test_df = serial_ns["df"], serial_ns["test_df"]

    print("Physics model on the test set...")
    physics = {
        "selected": "Physics Model_1.ipynb (no ML)",
        "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(physics_namespace(), test_df)),
    }

    print("Parallel hybrid (runs the notebook)...")
    parallel = train_parallel()

    print(f"PINN ({PINN_EPOCHS} epochs on CPU)...")
    pinn = train_pinn(test_df)

    params = {k: float(serial_ns[k]) for k in ("D", "L", "h_heat", "T_heat_C", "epsilon", "dp")}
    info = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "test_rows": int(len(test_df)),
        "versions": {"sklearn": sklearn.__version__, "torch": torch.__version__},
        "reactor": {
            "reaction": "CH3OH → CO + 2H2",
            "D_m": params["D"], "L_m": params["L"], "h_heat_W_m2K": params["h_heat"],
            "T_heat_C": params["T_heat_C"], "epsilon": params["epsilon"], "dp_m": params["dp"],
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
