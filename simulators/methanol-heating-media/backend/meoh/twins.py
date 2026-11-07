"""Four methanol heating-media twins (4 inputs including T_heat_C)."""

import json
from pathlib import Path

import joblib
import numpy as np
import torch

from .notebook import PARALLEL_NB, PHYSICS_NB, PINN_NB, SERIAL_NB, load_definitions

OUTPUT_COLS = [
    "T_0.2m_C", "T_0.4m_C", "T_0.6m_C", "T_0.8m_C", "T_1m_C",
    "P_out_bar_g", "Q_total_kW", "X_overall_pct",
]
INPUT_COLS = ["T_in_C", "P_in_bar_g", "T_heat_C", "F_in_kgmole_h"]

SHARED = {
    "bar_g_to_Pa", "Pa_to_bar_g", "kgmole_h_to_mol_s",
    "bed_side_htc", "overall_U", "reaction_enthalpy",
}


def featurize(U: np.ndarray) -> np.ndarray:
    """Expanded plant inputs for enriched residual models."""
    U = np.asarray(U, dtype=float)
    if U.ndim == 1:
        U = U.reshape(1, -1)
    T, P, Th, F = U[:, 0], U[:, 1], U[:, 2], U[:, 3]
    return np.column_stack(
        [
            T,
            P,
            Th,
            F,
            Th - T,
            T * F,
            P * F,
            Th * F,
            np.log1p(np.maximum(F, 0.0)),
            P / (T + 273.15),
            (Th + 273.15) / (T + 273.15),
            F / (P + 1.01325),
        ]
    )


def soft_clip_hybrid(y, P_in_bar_g: float) -> np.ndarray:
    out = np.asarray(y, dtype=float).copy()
    out[0:5] = np.clip(out[0:5], 0.0, 800.0)
    out[5] = float(np.clip(out[5], -0.5, float(P_in_bar_g) - 1e-6))
    out[7] = np.clip(out[7], 0.0, 100.0)
    return out


def physics_namespace() -> dict:
    return load_definitions(PHYSICS_NB, SHARED | {"reaction_rate", "reactor_model", "predict_outputs"})


def serial_namespace(artifact: dict) -> dict:
    # Newer Serial notebook: learned kinetics ODE + residual ML (ŷ = clip(y_ode + r̂)).
    ns = load_definitions(
        SERIAL_NB,
        SHARED
        | {
            "concentrations",
            "reactor_model",
            "simulate",
            "rate_learned",
            "outputs_vector",
            "predict_ode_only",
            "clip_hybrid",
            "predict_outputs",
        },
        kinetics_model=artifact["kinetics_model"],
        residual_model=artifact["residual_model"],
    )
    ns["kinetics_model"] = artifact["kinetics_model"]
    ns["residual_model"] = artifact["residual_model"]

    if artifact.get("featurize"):
        residual_model = artifact["residual_model"]

        def predict_outputs(T_in_C, P_in_bar_g, T_heat_C, F_in_kgmole_h):
            y_ode, pred = ns["predict_ode_only"](
                float(T_in_C), float(P_in_bar_g), float(T_heat_C), float(F_in_kgmole_h), n_points=80
            )
            y_ode = np.asarray(y_ode, float)
            u = np.array([[T_in_C, P_in_bar_g, T_heat_C, F_in_kgmole_h]], dtype=float)
            r_hat = residual_model.predict(featurize(u))[0]
            y_hat = soft_clip_hybrid(y_ode + r_hat, P_in_bar_g=float(P_in_bar_g))
            out = {c: float(y_hat[i]) for i, c in enumerate(OUTPUT_COLS)}
            out["z_m"] = pred["z_m"]
            out["T_profile_C"] = pred["T_profile_C"]
            out["y_ode"] = {c: float(y_ode[i]) for i, c in enumerate(OUTPUT_COLS)}
            out["r_hat"] = {c: float(r_hat[i]) for i, c in enumerate(OUTPUT_COLS)}
            return out

        ns["predict_outputs"] = predict_outputs
    return ns


def parallel_namespace(artifact: dict) -> dict:
    ns = load_definitions(
        PARALLEL_NB,
        SHARED
        | {
            "reaction_rate",
            "reactor_model",
            "predict_physics",
            "physics_vector",
            "clip_hybrid",
            "predict_outputs",
        },
        ETA=artifact["ETA"],
        residual_model=artifact["residual_model"],
    )
    ns["ETA"] = artifact["ETA"]
    ns["residual_model"] = artifact["residual_model"]

    if artifact.get("featurize"):
        residual_model = artifact["residual_model"]

        def predict_outputs(T_in_C, P_in_bar_g, T_heat_C, F_in_kgmole_h):
            phys = ns["predict_physics"](
                float(T_in_C), float(P_in_bar_g), float(T_heat_C), float(F_in_kgmole_h), eta=artifact["ETA"]
            )
            y_phys = np.array([phys[c] for c in OUTPUT_COLS], dtype=float)
            u = np.array([[T_in_C, P_in_bar_g, T_heat_C, F_in_kgmole_h]], dtype=float)
            r_hat = residual_model.predict(featurize(u))[0]
            y_hat = soft_clip_hybrid(y_phys + r_hat, P_in_bar_g=float(P_in_bar_g))
            out = {c: float(y_hat[i]) for i, c in enumerate(OUTPUT_COLS)}
            out["y_phys"] = {c: float(y_phys[i]) for i, c in enumerate(OUTPUT_COLS)}
            out["r_hat"] = {c: float(r_hat[i]) for i, c in enumerate(OUTPUT_COLS)}
            out["z_m"] = phys["z_m"]
            out["T_profile_C"] = phys["T_profile_C"]
            return out

        ns["predict_outputs"] = predict_outputs
    return ns


def pinn_namespace(state_dict: dict, refs: dict, residual_model) -> dict:
    # Newer PINN notebook: network + residual ML (ŷ = clip(y_pinn + r̂)).
    ns = load_definitions(
        PINN_NB,
        {
            "ReactorPINN",
            "predict_pinn_only",
            "clip_hybrid",
            "_isotonic_rising",
            "predict_outputs",
        },
        residual_model=residual_model,
        **refs,
    )
    model = ns["ReactorPINN"]()
    model.load_state_dict(state_dict)
    model.eval()
    ns["model"] = model
    ns["residual_model"] = residual_model
    return ns


class Twins:
    def __init__(self, artifacts: Path):
        torch.set_num_threads(1)
        self.physics = physics_namespace()
        self.serial = serial_namespace(joblib.load(artifacts / "serial.joblib"))
        self.parallel = parallel_namespace(joblib.load(artifacts / "parallel.joblib"))
        refs = json.loads((artifacts / "pinn_refs.json").read_text(encoding="utf-8"))
        residual = joblib.load(artifacts / "pinn_residual.joblib")
        if isinstance(residual, dict):
            residual = residual["residual_model"]
        try:
            state = torch.load(artifacts / "pinn.pt", map_location="cpu", weights_only=True)
        except TypeError:
            state = torch.load(artifacts / "pinn.pt", map_location="cpu")
        self.pinn = pinn_namespace(state, refs, residual)

    def predict(self, model: str, T_in_C: float, P_in_bar_g: float, T_heat_C: float, F_in_kgmole_h: float) -> dict:
        ns = getattr(self, model)
        out = ns["predict_outputs"](float(T_in_C), float(P_in_bar_g), float(T_heat_C), float(F_in_kgmole_h))
        values = {c: float(out[c]) for c in OUTPUT_COLS}
        if not all(np.isfinite(v) for v in values.values()):
            raise ValueError("the model returned a non-finite value")
        extra = {}
        if "y_phys" in out:
            extra["physics_ref"] = {c: float(out["y_phys"][c]) for c in OUTPUT_COLS}
        if "eta" in out:
            extra["eta"] = float(out["eta"])
        return {**values, **extra}
