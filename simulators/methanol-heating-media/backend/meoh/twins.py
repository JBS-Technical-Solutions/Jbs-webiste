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
    return ns


def parallel_namespace(artifact: dict) -> dict:
    return load_definitions(
        PARALLEL_NB,
        SHARED | {"reaction_rate", "reactor_model", "predict_physics", "physics_vector", "clip_hybrid", "predict_outputs"},
        ETA=artifact["ETA"], residual_model=artifact["residual_model"],
    )


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
