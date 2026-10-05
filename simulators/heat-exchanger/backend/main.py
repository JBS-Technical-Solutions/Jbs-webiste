"""
FastAPI backend for the JBS shell-and-tube heat exchanger digital twin.

Run:  .venv\\Scripts\\uvicorn main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import json
import os
from pathlib import Path
from typing import Literal, Optional

import joblib
import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from hx.a0 import NOTEBOOK as A0_NOTEBOOK
from hx.a0 import a0_physics
from hx.data import DATA_PATH, load_dataset
from hx.physics import (
    A_O_TOTAL, T_WATER_OUT_CAP, duty_ntu_eps, physics_outlets_from_U, rate_shell_and_tube_1_2,
)
from hx.pinn import HeatExchangerPINN

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
REQUIRED = ["serial_U.joblib", "parallel_residual.joblib", "pinn.pt", "pinn_scalers.joblib", "metrics.json"]

missing = [f for f in REQUIRED if not (ARTIFACTS / f).exists()]
if missing:
    raise RuntimeError(f"Missing model files {missing} in {ARTIFACTS}. Run `python train.py` first.")

torch.set_num_threads(1)
SERIAL_U = joblib.load(ARTIFACTS / "serial_U.joblib")
PARALLEL_RES = joblib.load(ARTIFACTS / "parallel_residual.joblib")
PINN_SCALERS = joblib.load(ARTIFACTS / "pinn_scalers.joblib")
PINN = HeatExchangerPINN()
PINN.load_state_dict(torch.load(ARTIFACTS / "pinn.pt", map_location="cpu"))
PINN.eval()
INFO = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))


def data_output_ranges() -> dict:
    if not DATA_PATH.exists():
        return {}
    df = load_dataset()
    duty = np.array([
        duty_ntu_eps(r.Udata, r.T_air_in, r.T_water_in, r.T_air_out, r.T_water_out, r.m_air, r.m_water)["Q_kW"]
        for r in df.itertuples()
    ])
    cols = {"U": df["Udata"].to_numpy(), "T_air_out": df["T_air_out"].to_numpy(),
            "T_water_out": df["T_water_out"].to_numpy(), "Q_kW": duty}
    return {k: {"min": round(float(v.min()), 4), "max": round(float(v.max()), 4)} for k, v in cols.items()}


INFO["output_ranges"] = data_output_ranges()

ModelKind = Literal["physics", "serial", "parallel", "pinn"]

MODEL_META = {
    "physics": (
        "Physics (E-NTU)",
        "Kern Method → HTCs → Overall U → NTU Method → Outlet Temps",
        A0_NOTEBOOK.name,
    ),
    "serial": (
        "Serial Hybrid",
        "ML predicts U (trained on Udata) → physics E-NTU outlets",
        "A2-SerialHybrid.ipynb",
    ),
    "parallel": (
        "Parallel Hybrid",
        "Physics outputs + ML residual corrections on U / Taout / Twout",
        "ParallelHybridModel.ipynb",
    ),
    "pinn": (
        "PINN Twin",
        "Physics-informed neural net → U, Taout, Twout directly",
        "PINN_TEMA_Udata.ipynb",
    ),
}


class TwinInputs(BaseModel):
    m_air_kgh: float = Field(gt=0, description="Hot Fluid, shell side (kg/h)")
    m_water_kgh: float = Field(gt=0, description="Cold Fluid, tube side (kg/h)")
    T_air_in: float = Field(description="Air inlet temperature (°C)")
    T_water_in: float = Field(ge=1, le=99, description="Water inlet temperature (°C)")


class PredictRequest(BaseModel):
    model: ModelKind
    inputs: TwinInputs


class PhysicsRef(BaseModel):
    U: float
    T_air_out: float
    T_water_out: float


class Hydraulics(BaseModel):
    h_i: float = Field(description="Tube-side (water) film coefficient, W/m²·K")
    h_o: float = Field(description="Shell-side (air) film coefficient, W/m²·K")
    Re_tube: float
    Re_shell: float
    dP_tube_kPa: float
    dP_shell_kPa: float
    P_air_in_kPa: float = Field(description="Shell-side (air) inlet pressure, kPa")
    P_water_in_kPa: float = Field(description="Tube-side (water) inlet pressure, kPa")


class TwinOutput(BaseModel):
    model: ModelKind
    modelLabel: str
    approach: str
    source: str
    U: float
    T_air_out: float
    T_water_out: float
    Q_kW: float
    NTU: float
    epsilon: float
    A_o_total: float
    iterations: Optional[int] = None
    physics_ref: Optional[PhysicsRef] = None
    hydraulics: Hydraulics
    extra: dict[str, float] = {}
    warnings: list[str] = []


app = FastAPI(title="JBS Heat Exchanger Digital Twin API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# When API_KEY is set (hosted deployments), only callers sending it in X-API-Key are served.
API_KEY = os.getenv("API_KEY")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if API_KEY and request.url.path != "/" and request.headers.get("x-api-key") != API_KEY:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/")
def root():
    return {"service": "JBS heat exchanger digital twin API"}


def range_warnings(i: TwinInputs) -> list[str]:
    labels = {
        "m_air_kgh": "Hot fluid flow",
        "m_water_kgh": "Cold fluid flow",
        "T_air_in": "Hot fluid inlet temperature",
        "T_water_in": "Cold fluid inlet temperature",
    }
    out = []
    for key, rng in INFO["training_ranges"].items():
        v = getattr(i, key)
        if v < rng["min"] or v > rng["max"]:
            out.append(
                f"{labels[key]} {v:g} is outside the training range "
                f"({rng['min']:g} – {rng['max']:g}); ML output is an extrapolation."
            )
    return out


def run_model(model: ModelKind, i: TwinInputs) -> TwinOutput:
    out = rate_model(model, i)
    if out.physics_ref:
        out.physics_ref.T_water_out = min(out.physics_ref.T_water_out, T_WATER_OUT_CAP)
    if out.T_water_out > T_WATER_OUT_CAP:
        out.warnings.append(
            f"Cold fluid outlet {out.T_water_out:.1f} °C capped at {T_WATER_OUT_CAP:g} °C, the highest "
            "value in the data — above it the cold fluid starts to boil."
        )
        out.T_water_out = T_WATER_OUT_CAP
    return out


def rate_model(model: ModelKind, i: TwinInputs) -> TwinOutput:
    if i.T_air_in <= i.T_water_in:
        raise HTTPException(400, "Hot fluid inlet temperature must be higher than cold fluid inlet temperature.")

    m_air, m_water = i.m_air_kgh / 3600.0, i.m_water_kgh / 3600.0
    x_kgs = np.array([[m_air, m_water, i.T_air_in, i.T_water_in]])
    a0 = a0_physics(i.T_air_in, m_air, i.T_water_in, m_water)
    label, approach, source = MODEL_META[model]
    base = {
        "model": model,
        "modelLabel": label,
        "approach": approach,
        "source": source,
        "A_o_total": A_O_TOTAL,
        "hydraulics": a0.pop("hydraulics"),
    }

    if model == "physics":
        return TwinOutput(**base, **a0)

    ref = PhysicsRef(U=a0["U"], T_air_out=a0["T_air_out"], T_water_out=a0["T_water_out"])
    warn = range_warnings(i)

    if model == "serial":
        U = float(SERIAL_U.predict(x_kgs)[0])
        out = physics_outlets_from_U(U, i.T_air_in, i.T_water_in, m_air, m_water)
        return TwinOutput(**base, **out, physics_ref=ref, warnings=warn)

    if model == "parallel":
        phys = rate_shell_and_tube_1_2(i.T_air_in, m_air, i.T_water_in, m_water)
        dU, dTa, dTw = (float(v) for v in PARALLEL_RES.predict(x_kgs)[0])
        U, Ta, Tw = phys["U"] + dU, phys["T_air_out"] + dTa, phys["T_water_out"] + dTw
        derived = duty_ntu_eps(U, i.T_air_in, i.T_water_in, Ta, Tw, m_air, m_water)
        return TwinOutput(
            **base, U=U, T_air_out=Ta, T_water_out=Tw, **derived,
            physics_ref=ref, extra={"dU": dU, "dT_air_out": dTa, "dT_water_out": dTw}, warnings=warn,
        )

    x_kgh = np.array([[i.m_air_kgh, i.m_water_kgh, i.T_air_in, i.T_water_in]])
    with torch.no_grad():
        y_s = PINN(torch.tensor(PINN_SCALERS["x"].transform(x_kgh), dtype=torch.float32)).numpy()
    U, Ta, Tw = (float(v) for v in PINN_SCALERS["y"].inverse_transform(y_s)[0])
    derived = duty_ntu_eps(U, i.T_air_in, i.T_water_in, Ta, Tw, m_air, m_water)
    return TwinOutput(**base, U=U, T_air_out=Ta, T_water_out=Tw, **derived, physics_ref=ref, warnings=warn)


@app.get("/health")
def health():
    return {"status": "ok", "trained_at": INFO["trained_at"], "physics_source": A0_NOTEBOOK.name}


@app.get("/info")
def info():
    return INFO


@app.post("/predict", response_model=TwinOutput)
def predict(req: PredictRequest):
    return run_model(req.model, req.inputs)


@app.post("/compare", response_model=list[TwinOutput])
def compare(inputs: TwinInputs):
    return [run_model(m, inputs) for m in ("physics", "serial", "parallel", "pinn")]
