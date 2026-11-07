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


def _finite_or_none(value: float) -> float | None:
    value = float(value)
    return value if np.isfinite(value) else None


def scores(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    out = {}
    for i, c in enumerate(OUTPUT_COLS):
        ok = np.isfinite(y_true[:, i]) & np.isfinite(y_pred[:, i])
        if int(ok.sum()) < 2:
            out[c] = {"r2": None, "mae": None}
        else:
            out[c] = {
                "r2": _finite_or_none(r2_score(y_true[ok, i], y_pred[ok, i])),
                "mae": _finite_or_none(mean_absolute_error(y_true[ok, i], y_pred[ok, i])),
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
    if "residual_model" not in serial_ns:
        raise RuntimeError("Serial notebook did not produce residual_model")
    joblib.dump(
        {
            "kinetics_model": serial_ns["kinetics_model"],
            "residual_model": serial_ns["residual_model"],
        },
        ARTIFACTS / "serial.joblib",
    )
    df, test_df = serial_ns["df"], serial_ns["test_df"]
    y_serial = serial_ns["Y_hyb"] if "Y_hyb" in serial_ns else serial_ns["Y_learn"]
    serial = {
        "selected": "Learned kinetics ODE + HistGradientBoosting residual",
        "test": scores(serial_ns["Y_excel"], y_serial),
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
    # New PINN notebook already uses clip_grad_norm=1.0, finite-loss skip, and EPOCHS=200.
    # Do not skip the eval cell (it mentions "MAE PINN only") — we need Y_true / Y_hyb for R².
    pinn_ns = run_notebook(PINN_NB, skip=("input(", "run_digital_twin_interactive"))
    if "residual_model" not in pinn_ns:
        raise RuntimeError("PINN notebook did not produce residual_model")
    model = pinn_ns["model"]
    model.eval()
    refs = {}
    for k in (
        "T_REF",
        "P_REF_BAR",
        "F_REF",
        "T_HEAT_REF",
        "Q_REF",
        "T_BED_HI",
        "T_BED_LO",
        "T_DATA_SCALE",
        "Q_MAX",
        "P_ATM_BAR",
        "L",
        "D",
        "epsilon",
        "dp",
        "DP_MAX_PA",
        "R",
        "OUTPUT_COLS",
        "INPUT_COLS",
        "TEMP_COLS",
        "MEASUREMENT_POSITIONS_M",
        "MW_CH3OH",
        "MW_CO",
        "MW_H2",
        "KCAL_PER_KGMOLE_TO_J_PER_MOL",
        "A_CO",
        "E_CO",
        "T_ref_C",
    ):
        if k not in pinn_ns:
            continue
        v = pinn_ns[k]
        if isinstance(v, (float, int, np.floating, np.integer)):
            refs[k] = float(v) if not isinstance(v, (int, np.integer)) else int(v)
        elif isinstance(v, (list, tuple)):
            refs[k] = list(v)
        elif isinstance(v, np.ndarray):
            refs[k] = v.tolist()
        else:
            refs[k] = v
    for required in ("T_REF", "P_REF_BAR", "F_REF", "T_HEAT_REF", "Q_REF", "T_BED_HI", "Q_MAX"):
        if required not in refs:
            raise RuntimeError(f"PINN notebook missing required constant {required}")
    state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    if any(not torch.isfinite(v).all() for v in state.values()):
        raise RuntimeError("PINN training produced non-finite weights")
    torch.save(state, ARTIFACTS / "pinn.pt")
    (ARTIFACTS / "pinn_refs.json").write_text(json.dumps(refs, indent=2), encoding="utf-8")
    joblib.dump({"residual_model": pinn_ns["residual_model"]}, ARTIFACTS / "pinn_residual.joblib")
    website = pinn_namespace(state, refs, pinn_ns["residual_model"])
    # Prefer hybrid scores from the notebook eval when present.
    if "Y_hyb" in pinn_ns and "Y_true" in pinn_ns:
        y_true = np.asarray(pinn_ns["Y_true"], float)
        y_hyb = np.asarray(pinn_ns["Y_hyb"], float)
        if y_true.ndim == 1 or len(y_true) < 2:
            raise RuntimeError("PINN notebook eval produced too few scored rows")
        pinn_test = scores(y_true, y_hyb)
    else:
        # Fallback: score the served twin on a held-out slice.
        eval_df = test_df.head(min(120, len(test_df)))
        pinn_test = scores(eval_df[OUTPUT_COLS].to_numpy(), predict_rows(website, eval_df))
    if all(v["r2"] is None for v in pinn_test.values()):
        raise RuntimeError("PINN R² scores are all missing — eval failed")
    pinn = {
        "selected": (
            f"ReactorPINN + residual, {int(pinn_ns['N_TRAIN_CASES'])} cases × "
            f"{int(pinn_ns['EPOCHS'])} epochs"
        ),
        "test": pinn_test,
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
    (ARTIFACTS / "metrics.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Saved to {ARTIFACTS} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
