"""The three water pump twins, each using its notebook's own functions and network."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch

from .notebook import PARALLEL_NB, PINN_NB, SERIAL_NB, load_definitions

INPUT_COLS = ["Water Flow", "Water inlet Pressure", "Water outlet pressure", "Water Density"]
TARGET_COL = "Pump Brake power"


def serial_namespace(artifact: dict) -> dict:
    return load_definitions(
        SERIAL_NB, {"compute_hydraulic_power", "serial_hybrid_predict"},
        efficiency_model=artifact["efficiency_model"],
    )


def parallel_namespace(artifact: dict) -> dict:
    return load_definitions(
        PARALLEL_NB, {"compute_hydraulic_power", "residual_hybrid_predict"},
        residual_model=artifact["residual_model"], physics_efficiency=artifact["physics_efficiency"],
    )


def pinn_namespace(state_dict: dict, scaler, features: list[str]) -> dict:
    ns = load_definitions(PINN_NB, {"PumpPINN"})
    model = ns["PumpPINN"]()
    model.load_state_dict(state_dict)
    model.eval()
    ns.update(model=model, scaler_X=scaler, features=features)
    return ns


def pinn_predict(ns: dict, flow: float, p_in: float, p_out: float, rho: float) -> tuple[float, float]:
    """Brake power (kW) and efficiency from the notebook's PumpPINN, with its own input scaling."""
    x = ns["scaler_X"].transform(pd.DataFrame([[flow, p_in, p_out, rho]], columns=ns["features"]))
    with torch.no_grad():
        brake, eff = ns["model"](torch.tensor(x, dtype=torch.float32))
    return float(brake[0, 0]), float(eff[0, 0])


class Twins:
    """Loads trained artifacts and serves brake power, hydraulic power and efficiency for every model."""

    def __init__(self, artifacts: Path):
        torch.set_num_threads(1)
        self.serial = serial_namespace(joblib.load(artifacts / "serial.joblib"))
        self.parallel = parallel_namespace(joblib.load(artifacts / "parallel.joblib"))
        pinn = joblib.load(artifacts / "pinn_scaler.joblib")
        self.pinn = pinn_namespace(
            torch.load(artifacts / "pinn.pt", map_location="cpu"), pinn["scaler"], pinn["features"]
        )

    def predict(self, model: str, flow: float, p_in: float, p_out: float, rho: float) -> dict:
        args = (float(flow), float(p_in), float(p_out), float(rho))
        if model == "serial":
            out = self.serial["serial_hybrid_predict"](*args)
            values = {
                "brake_kW": out["Predicted Brake Power (kW)"],
                "hydraulic_kW": out["Hydraulic Power (kW)"],
                "efficiency": out["Predicted Efficiency"],
            }
        elif model == "parallel":
            out = self.parallel["residual_hybrid_predict"](*args)
            values = {
                "brake_kW": out["Hybrid Brake Power (kW)"],
                "hydraulic_kW": out["Hydraulic Power (kW)"],
                "efficiency": out["Physics Efficiency"],
                "physics_brake_kW": out["Physics Brake Power (kW)"],
                "residual_kW": out["Predicted Residual (kW)"],
            }
        elif model == "pinn":
            brake, eff = pinn_predict(self.pinn, *args)
            values = {
                "brake_kW": brake,
                "hydraulic_kW": self.serial["compute_hydraulic_power"](*args),
                "efficiency": eff,
            }
        else:
            raise ValueError(f"unknown model {model}")
        values = {k: float(v) for k, v in values.items()}
        if not all(np.isfinite(v) for v in values.values()):
            raise ValueError("the model returned a non-finite value")
        return values
