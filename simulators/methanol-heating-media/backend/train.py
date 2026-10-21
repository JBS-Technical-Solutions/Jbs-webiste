"""Train heating-media twins when artifacts are missing (Docker fallback)."""

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
    INPUT_COLS,
    OUTPUT_COLS,
    parallel_namespace,
    physics_namespace,
    pinn_namespace,
    serial_namespace,
)

warnings.filterwarnings("ignore")
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def scores(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    out = {}
    for i, c in enumerate(OUTPUT_COLS):
        ok = np.isfinite(y_true[:, i]) & np.isfinite(y_pred[:, i])
        if int(ok.sum()) < 2:
            out[c] = {"r2": float("nan"), "mae": float("nan")}
        else:
            out[c] = {
                "r2": float(r2_score(y_true[ok, i], y_pred[ok, i])),
                "mae": float(mean_absolute_error(y_true[ok, i], y_pred[ok, i])),
            }
    return out


def predict_rows(ns: dict, df) -> np.ndarray:
    rows = []
    for r in df[INPUT_COLS].itertuples(index=False):
        try:
            out = ns["predict_outputs"](float(r[0]), float(r[1]), float(r[2]), float(r[3]))
            rows.append([float(out[c]) for c in OUTPUT_COLS])
        except Exception:
            rows.append([np.nan] * len(OUTPUT_COLS))
    return np.asarray(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(exist_ok=True)
    np.random.seed(42)
    torch.manual_seed(42)
    t0 = time.time()

    print("Serial hybrid...")
    serial_ns = run_notebook(SERIAL_NB)
    joblib.dump({"kinetics_model": serial_ns["kinetics_model"]}, ARTIFACTS / "serial.joblib")
    df, test_df = serial_ns["df"], serial_ns["test_df"]
    serial = {
        "selected": "MLP reaction rate inside the physics ODE",
        "test": scores(serial_ns["Y_excel"], serial_ns["Y_learn"]),
    }

    print("Physics...")
    physics = {
        "selected": "Physics_HeatingMedia.ipynb (no ML)",
        "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(physics_namespace(), test_df)),
    }

    print("Parallel hybrid...")
    parallel_ns = run_notebook(PARALLEL_NB)
    artifact = {"ETA": float(parallel_ns["ETA"]), "residual_model": parallel_ns["residual_model"]}
    joblib.dump(artifact, ARTIFACTS / "parallel.joblib")
    parallel = {
        "selected": f"Physics (η = {artifact['ETA']:.3e}) + HistGradientBoosting residual",
        "test": scores(parallel_ns["Y_excel_test"], parallel_ns["Y_hyb_test"]),
    }

    print("PINN...")
    pinn_ns = run_notebook(
        PINN_NB,
        skip=("input(", "MAE PINN"),
        patches={
            "optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)  # Adam optimizer with learning rate 0.001":
            "optimizer = torch.optim.Adam(model.parameters(), lr=3e-4)",
            "loss_batch.backward()  # backpropagate\n        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)  # gradient clipping\n        optimizer.step()  # update weights":
            "loss_batch.backward()\n        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)\n"
            "        if torch.isfinite(loss_batch).item():\n"
            "            optimizer.step()\n"
            "        else:\n"
            "            optimizer.zero_grad(set_to_none=True)",
        },
    )
    model = pinn_ns["model"]
    model.eval()
    refs = {k: float(pinn_ns[k]) for k in ("T_REF", "P_REF_BAR", "F_REF", "T_HEAT_REF", "Q_REF")}
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    if any(not torch.isfinite(v).all() for v in state.values()):
        raise RuntimeError("PINN training produced non-finite weights")
    torch.save(state, ARTIFACTS / "pinn.pt")
    (ARTIFACTS / "pinn_refs.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")
    website = pinn_namespace(state, refs)
    pinn = {
        "selected": f"ReactorPINN (4×64 tanh), {int(pinn_ns['N_TRAIN_CASES'])} cases × {int(pinn_ns['EPOCHS'])} epochs",
        "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(website, test_df)),
    }

    info = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "test_rows": int(len(test_df)),
        "versions": {"sklearn": sklearn.__version__, "torch": torch.__version__},
        "reactor": {
            "reaction": "CH3OH → CO + 2H2",
            "D_m": float(serial_ns["D"]),
            "L_m": float(serial_ns["L"]),
            "h_heat_W_m2K": float(serial_ns["h_o"]),
            "epsilon": float(serial_ns["epsilon"]),
            "dp_m": float(serial_ns["dp"]),
        },
        "training_ranges": {c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in INPUT_COLS},
        "output_ranges": {c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in OUTPUT_COLS},
        "models": {"physics": physics, "serial": serial, "parallel": parallel, "pinn": pinn},
    }
    (ARTIFACTS / "metrics.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved to {ARTIFACTS} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
