"""
Train all digital-twin models from data.csv and save them to backend/artifacts/.
Same data prep, features, splits and hyper-parameters as the notebooks:
  - Physics:  A0-PhysicsModelOnly.ipynb  (no training; test-set scores only)
  - Serial:   A2-SerialHybrid.ipynb      (LinearRegression vs RandomForest on Udata)
  - Parallel: ParallelHybridModel.ipynb  (multi-output residuals vs physics)
  - PINN:     PINN_TEMA_Udata.ipynb      (MLP + TEMA physics loss)
Test scores use the water outlet capped at T_WATER_OUT_CAP, like the notebooks' clip cell.

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
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputRegressor
from sklearn.preprocessing import StandardScaler

from hx.a0 import a0_physics
from hx.data import DATA_PATH, load_dataset
from hx.physics import GEOMETRY, T_WATER_OUT_CAP, physics_outlets_from_U, rate_shell_and_tube_1_2
from hx.pinn import HeatExchangerPINN, physics_residuals

warnings.filterwarnings("ignore")

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
FEATURES_KGS = ["m_air", "m_water", "T_air_in", "T_water_in"]
FEATURES_KGH = ["m_air_kgh", "m_water_kgh", "T_air_in", "T_water_in"]


def scores(y_true, y_pred):
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
    }


def output_scores(df_test, U, Ta, Tw):
    return {
        "U": scores(df_test["Udata"], U),
        "T_air_out": scores(df_test["T_air_out"], Ta),
        "T_water_out": scores(df_test["T_water_out"], np.minimum(np.asarray(Tw, float), T_WATER_OUT_CAP)),
    }


def add_physics_columns(df):
    rows = [
        rate_shell_and_tube_1_2(r.T_air_in, r.m_air, r.T_water_in, r.m_water)
        for r in df.itertuples()
    ]
    df["U_phys"] = [r["U"] for r in rows]
    df["T_air_out_phys"] = [r["T_air_out"] for r in rows]
    df["T_water_out_phys"] = [r["T_water_out"] for r in rows]
    return df


def train_serial(df):
    X = df[FEATURES_KGS].values
    y = df["Udata"].values
    X_tr, X_te, y_tr, y_te, _, idx_te = train_test_split(
        X, y, df.index.values, test_size=0.2, random_state=42
    )

    candidates = {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=1),
    }
    results = {}
    for name, model in candidates.items():
        model.fit(X_tr, y_tr)
        results[name] = {"model": model, **scores(y_te, model.predict(X_te))}
        print(f"  [serial] {name:18s} test R²(U)={results[name]['r2']:.4f}")

    best_name = max(results, key=lambda n: (results[n]["r2"], -results[n]["rmse"]))
    best = results[best_name]["model"]

    test = df.loc[idx_te]
    U = best.predict(test[FEATURES_KGS].values)
    outs = [
        physics_outlets_from_U(u, r.T_air_in, r.T_water_in, r.m_air, r.m_water)
        for u, r in zip(U, test.itertuples())
    ]
    metrics = output_scores(test, U, [o["T_air_out"] for o in outs], [o["T_water_out"] for o in outs])
    joblib.dump(best, ARTIFACTS / "serial_U.joblib")
    return {"selected": best_name, "test": metrics}, idx_te


def train_parallel(df):
    df = df.copy()
    df["U_res"] = df["Udata"] - df["U_phys"]
    df["T_air_out_res"] = df["T_air_out"] - df["T_air_out_phys"]
    df["T_water_out_res"] = df["T_water_out"] - df["T_water_out_phys"]
    df = df.dropna(subset=["U_res"]).reset_index(drop=True)

    X = df[FEATURES_KGS].values
    y = df[["U_res", "T_air_out_res", "T_water_out_res"]].values
    X_tr, X_te, y_tr, y_te, _, idx_te = train_test_split(
        X, y, df.index.values, test_size=0.2, random_state=42
    )

    candidates = {
        "Linear Regression (multi-output)": MultiOutputRegressor(LinearRegression()),
        "Random Forest (multi-output)": MultiOutputRegressor(
            RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=1)
        ),
    }
    results = {}
    for name, model in candidates.items():
        model.fit(X_tr, y_tr)
        pred = model.predict(X_te)
        per = [scores(y_te[:, j], pred[:, j]) for j in range(3)]
        results[name] = {
            "model": model,
            "mean_r2": float(np.mean([p["r2"] for p in per])),
            "mean_rmse": float(np.mean([p["rmse"] for p in per])),
        }
        print(f"  [parallel] {name:34s} mean test R²(residuals)={results[name]['mean_r2']:.4f}")

    best_name = max(results, key=lambda n: (results[n]["mean_r2"], -results[n]["mean_rmse"]))
    best = results[best_name]["model"]

    test = df.loc[idx_te]
    res = best.predict(test[FEATURES_KGS].values)
    metrics = output_scores(
        test,
        test["U_phys"].values + res[:, 0],
        test["T_air_out_phys"].values + res[:, 1],
        test["T_water_out_phys"].values + res[:, 2],
    )
    joblib.dump(best, ARTIFACTS / "parallel_residual.joblib")
    return {"selected": best_name, "test": metrics}


def train_pinn(df):
    torch.manual_seed(42)
    np.random.seed(42)

    X = df[FEATURES_KGH].values.astype(np.float64)
    Y = df[["Udata", "T_air_out", "T_water_out"]].values.astype(np.float64)
    M = df[["m_air", "m_water"]].values.astype(np.float64)
    X_tr, X_te, Y_tr, Y_te, M_tr, M_te, _, idx_te = train_test_split(
        X, Y, M, np.arange(len(df)), test_size=0.2, random_state=42
    )

    x_scaler = StandardScaler().fit(X_tr)
    y_scaler = StandardScaler().fit(Y_tr)

    def t(a):
        return torch.tensor(a, dtype=torch.float32)

    Xtr, Ytr, Mtr, Tin_tr = t(x_scaler.transform(X_tr)), t(y_scaler.transform(Y_tr)), t(M_tr), t(X_tr[:, 2:4])
    Xte, Yte, Mte, Tin_te = t(x_scaler.transform(X_te)), t(y_scaler.transform(Y_te)), t(M_te), t(X_te[:, 2:4])

    model = HeatExchangerPINN()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-6)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=40)

    WARMUP_EPOCHS, PHYS_EPOCHS, BATCH = 250, 350, 256
    LAMBDA_PHYS, LAMBDA_BOUNDS = 0.2, 0.02
    y_mean, y_scale = t(y_scaler.mean_), t(y_scaler.scale_)

    def loss_fn(x_s, y_s_true, m_si, T_in, lam):
        y_s_pred = model(x_s)
        data_loss = torch.mean((y_s_pred - y_s_true) ** 2)
        if lam <= 0.0:
            return data_loss
        U, Taout, Twout = (y_s_pred * y_scale + y_mean).T
        r_U, r_Ta, r_Tw, p_c, p_h, p_d1, p_d2, p_U = physics_residuals(
            m_si[:, 0], m_si[:, 1], T_in[:, 0], T_in[:, 1], U, Taout, Twout
        )
        phys = torch.mean(r_U ** 2) + torch.mean(r_Ta ** 2) + torch.mean(r_Tw ** 2)
        bnd = sum(torch.mean(p ** 2) for p in (p_c, p_h, p_d1, p_d2, p_U))
        return data_loss + lam * phys + LAMBDA_BOUNDS * bnd

    n = Xtr.shape[0]
    for epoch in range(1, WARMUP_EPOCHS + PHYS_EPOCHS + 1):
        model.train()
        lam = 0.0 if epoch <= WARMUP_EPOCHS else LAMBDA_PHYS
        perm = torch.randperm(n)
        for i in range(0, n, BATCH):
            idx = perm[i : i + BATCH]
            optimizer.zero_grad()
            loss = loss_fn(Xtr[idx], Ytr[idx], Mtr[idx], Tin_tr[idx], lam)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            val = loss_fn(Xte, Yte, Mte, Tin_te, lam)
        scheduler.step(val)
        if epoch == 1 or epoch % 100 == 0:
            print(f"  [pinn] epoch {epoch:4d}  val loss={val.item():.5f}  lambda_phys={lam}")

    model.eval()
    with torch.no_grad():
        pred = y_scaler.inverse_transform(model(Xte).numpy())
    test = df.iloc[idx_te]
    metrics = output_scores(test, pred[:, 0], pred[:, 1], pred[:, 2])

    torch.save(model.state_dict(), ARTIFACTS / "pinn.pt")
    joblib.dump({"x": x_scaler, "y": y_scaler}, ARTIFACTS / "pinn_scalers.joblib")
    return {"selected": "MLP 4→128→128→64→3 (SiLU), λ_phys=0.2", "test": metrics}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(exist_ok=True)
    t0 = time.time()

    print(f"Loading {DATA_PATH}")
    df = load_dataset()
    print(f"  rows with valid Udata: {len(df)}")

    print("Physics branch on every row...")
    df = add_physics_columns(df)

    print("Serial hybrid...")
    serial, idx_te = train_serial(df)
    test = df.loc[idx_te]
    a0 = [a0_physics(r.T_air_in, r.m_air, r.T_water_in, r.m_water) for r in test.itertuples()]
    physics = {
        "selected": "A0-PhysicsModelOnly.ipynb (no ML)",
        "test": output_scores(
            test, [o["U"] for o in a0], [o["T_air_out"] for o in a0], [o["T_water_out"] for o in a0]
        ),
    }

    print("Parallel hybrid...")
    parallel = train_parallel(df)

    print("PINN (600 epochs, takes a few minutes on CPU)...")
    pinn = train_pinn(df)

    ranges = {
        c: {"min": float(df[c].min()), "max": float(df[c].max())}
        for c in ["m_air_kgh", "m_water_kgh", "T_air_in", "T_water_in"]
    }
    info = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "versions": {"sklearn": sklearn.__version__, "torch": torch.__version__},
        "geometry": GEOMETRY,
        "training_ranges": ranges,
        "models": {"physics": physics, "serial": serial, "parallel": parallel, "pinn": pinn},
    }
    (ARTIFACTS / "metrics.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    print("\nTest-set R² (U vs Udata | Taout | Twout):")
    for k, v in info["models"].items():
        m = v["test"]
        print(f"  {k:9s} {m['U']['r2']:.4f} | {m['T_air_out']['r2']:.4f} | {m['T_water_out']['r2']:.4f}   ({v['selected']})")
    print(f"\nSaved to {ARTIFACTS}  in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
