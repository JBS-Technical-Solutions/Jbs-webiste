"""
Train the methanol heating-media digital twins from Methanol Reforming Data.xlsx.

Notebooks (Run All, minus interactive input() cells):
  - Physics:  Physics_HeatingMedia.ipynb
  - Serial:   Serial_HeatingMedia.ipynb
  - Parallel: Parallel_HeatingMedia.ipynb
  - PINN:     PINN_HeatingMedia.ipynb

Run:  python train.py
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


def check_same(name: str, notebook_ns: dict, website_ns: dict, df, tol: float = 1e-6) -> None:
    sample = df.head(5)
    a = predict_rows(notebook_ns, sample)
    b = predict_rows(website_ns, sample)
    ok = np.isfinite(a) & np.isfinite(b)
    if not ok.any():
        print(f"  [{name}] website vs notebook: no finite rows to compare (skipped)")
        return
    diff = float(np.max(np.abs(a[ok] - b[ok])))
    print(f"  [{name}] website vs notebook predict_outputs: max |diff| = {diff:.2e} on {int(ok.sum())} finite values")
    if diff > tol:
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
    return {
        "selected": f"Physics (η = {artifact['ETA']:.3e}) + HistGradientBoosting residual",
        "test": metrics,
    }


def train_pinn(test_df):
    # Skip the notebook's sklearn scoring cell. Also stabilize Adam so weights stay finite
    # (the stock notebook can diverge to NaN on this Excel set).
    ns = run_notebook(
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
    model = ns["model"]
    model.eval()
    refs = {
        k: float(ns[k])
        for k in ("T_REF", "P_REF_BAR", "F_REF", "T_HEAT_REF", "Q_REF")
    }
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    if any(not torch.isfinite(v).all() for v in state.values()):
        raise RuntimeError("PINN training produced non-finite weights")
    torch.save(state, ARTIFACTS / "pinn.pt")
    (ARTIFACTS / "pinn_refs.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")

    website = pinn_namespace(state, refs)
    check_same("pinn", ns, website, test_df.head(5), tol=1e-3)
    metrics = scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(website, test_df))
    n_cases, epochs = int(ns["N_TRAIN_CASES"]), int(ns["EPOCHS"])
    return {
        "selected": f"ReactorPINN (4×64 tanh), {n_cases} cases × {epochs} epochs",
        "test": metrics,
    }


def reactor_meta(ns: dict) -> dict:
    return {
        "reaction": "CH3OH → CO + 2H2",
        "D_m": float(ns["D"]),
        "L_m": float(ns["L"]),
        "h_heat_W_m2K": float(ns["h_o"]),
        "epsilon": float(ns["epsilon"]),
        "dp_m": float(ns["dp"]),
    }


def main():
    from sklearn.model_selection import train_test_split

    from meoh.notebook import PHYSICS_NB

    sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(exist_ok=True)
    np.random.seed(42)
    torch.manual_seed(42)
    t0 = time.time()

    serial_path = ARTIFACTS / "serial.joblib"
    parallel_path = ARTIFACTS / "parallel.joblib"
    reuse = serial_path.exists() and parallel_path.exists()

    if reuse:
        print("Reusing serial.joblib + parallel.joblib; loading cleaned Excel via physics notebook...")
        phys_ns = run_notebook(
            PHYSICS_NB,
            skip=("input(", "Run physics model on every", "Compare with Methanol"),
        )
        df = phys_ns["df"]
        _, test_df = train_test_split(df, test_size=0.2, random_state=42)
        test_df = test_df.reset_index(drop=True)
        reactor = reactor_meta(phys_ns)

        print("Scoring serial on the test set...")
        serial_ns = serial_namespace(joblib.load(serial_path))
        serial = {
            "selected": "MLP reaction rate inside the physics ODE",
            "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(serial_ns, test_df)),
        }

        print("Scoring parallel on the test set...")
        parallel_ns = parallel_namespace(joblib.load(parallel_path))
        parallel = {
            "selected": f"Physics (η = {float(joblib.load(parallel_path)['ETA']):.3e}) + HistGradientBoosting residual",
            "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(parallel_ns, test_df)),
        }
    else:
        print("Serial hybrid (runs the notebook: rate labels + learned kinetics)...")
        serial_ns_full, serial = train_serial()
        df, test_df = serial_ns_full["df"], serial_ns_full["test_df"]
        reactor = reactor_meta(serial_ns_full)

        print("Parallel hybrid (runs the notebook)...")
        parallel = train_parallel()

    print("Physics model on the test set...")
    physics = {
        "selected": "Physics_HeatingMedia.ipynb (no ML)",
        "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(physics_namespace(), test_df)),
    }

    pinn_path = ARTIFACTS / "pinn.pt"
    refs_path = ARTIFACTS / "pinn_refs.json"
    reuse_pinn = False
    if pinn_path.exists() and refs_path.exists():
        state = torch.load(pinn_path, map_location="cpu")
        reuse_pinn = all(torch.isfinite(v).all() for v in state.values())
        if not reuse_pinn:
            print("Existing pinn.pt has non-finite weights; retraining...")
            pinn_path.unlink(missing_ok=True)
            refs_path.unlink(missing_ok=True)

    if reuse_pinn:
        print("Reusing pinn.pt; scoring on the test set...")
        refs = json.loads(refs_path.read_text(encoding="utf-8"))
        website = pinn_namespace(state, refs)
        pinn = {
            "selected": "ReactorPINN (4×64 tanh), 40 cases × 120 epochs",
            "test": scores(test_df[OUTPUT_COLS].to_numpy(), predict_rows(website, test_df)),
        }
    else:
        print("PINN (notebook settings, on CPU)...")
        pinn = train_pinn(test_df)

    info = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "test_rows": int(len(test_df)),
        "versions": {"sklearn": sklearn.__version__, "torch": torch.__version__},
        "reactor": reactor,
        "training_ranges": {
            c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in INPUT_COLS
        },
        "output_ranges": {
            c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in OUTPUT_COLS
        },
        "models": {"physics": physics, "serial": serial, "parallel": parallel, "pinn": pinn},
    }
    (ARTIFACTS / "metrics.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    print("\nTest-set R² per output:")
    print("  " + " ".join(f"{c:>13s}" for c in ["model"] + OUTPUT_COLS))
    for k, v in info["models"].items():
        print("  " + f"{k:>13s} " + " ".join(f"{v['test'][c]['r2']:13.4f}" for c in OUTPUT_COLS))
    print(f"\nSaved to {ARTIFACTS}  in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
