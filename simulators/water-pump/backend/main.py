"""
FastAPI backend for the JBS water pump digital twin.

Run:  .venv\\Scripts\\uvicorn main:app --reload --port 8002
Docs: http://localhost:8002/docs
"""

import json
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from pump.notebook import PARALLEL_NB, PINN_NB, SERIAL_NB
from pump.twins import Twins

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
REQUIRED = ["serial.joblib", "parallel.joblib", "pinn.pt", "pinn_scaler.joblib", "metrics.json"]

missing = [f for f in REQUIRED if not (ARTIFACTS / f).exists()]
if missing:
    raise RuntimeError(f"Missing model files {missing} in {ARTIFACTS}. Run `python train.py` first.")

TWINS = Twins(ARTIFACTS)
INFO = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))

ModelKind = Literal["serial", "parallel", "pinn"]
MODEL_ORDER: list[ModelKind] = ["serial", "parallel", "pinn"]

MODEL_META = {
    "serial": ("Serial Hybrid", "Physics hydraulic power → ML efficiency → brake power = P_hyd / η", SERIAL_NB.name),
    "parallel": ("Parallel Hybrid", "First-principles brake power + ML residual correction", PARALLEL_NB.name),
    "pinn": ("PINN", "Physics-Informed Neural Network (brake power · η = P_hyd)", PINN_NB.name),
}

INPUT_LABELS = {
    "flow_kgh": "Water flow",
    "P_in_bar": "Inlet pressure",
    "P_out_bar": "Outlet pressure",
    "rho": "Water density",
}

CURVE_POINTS = 26


class TwinInputs(BaseModel):
    flow_kgh: float = Field(gt=0, le=200_000, description="Water mass flow (kg/h)")
    P_in_bar: float = Field(ge=0, le=1000, description="Suction (inlet) pressure (bar)")
    P_out_bar: float = Field(gt=0, le=1000, description="Discharge (outlet) pressure (bar)")
    rho: float = Field(gt=0, le=2000, description="Water density (kg/m³)")


class PredictRequest(BaseModel):
    model: ModelKind
    inputs: TwinInputs


class Outputs(BaseModel):
    brake_kW: float = Field(description="Pump brake (shaft) power (kW)")
    hydraulic_kW: float = Field(description="Hydraulic power Q·ΔP (kW)")
    efficiency: float = Field(description="Pump efficiency (fraction)")
    physics_brake_kW: Optional[float] = Field(None, description="Parallel: first-principles brake power")
    residual_kW: Optional[float] = Field(None, description="Parallel: ML residual correction")


class TwinOutput(BaseModel):
    model: ModelKind
    modelLabel: str
    approach: str
    source: str
    outputs: Optional[Outputs] = None
    error: Optional[str] = None
    warnings: list[str] = []


class CurvePoint(BaseModel):
    flow_kgh: float
    brake_kW: Optional[float]


class ModelCurve(BaseModel):
    model: ModelKind
    points: list[CurvePoint]


app = FastAPI(title="JBS Water Pump Digital Twin API", version="1.0.0")
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
    return {"service": "JBS water pump digital twin API"}


def validate(i: TwinInputs) -> None:
    if i.P_out_bar <= i.P_in_bar:
        raise HTTPException(422, "Outlet pressure must be greater than inlet pressure.")


def range_warnings(i: TwinInputs) -> list[str]:
    out = []
    for key, rng in INFO["training_ranges"].items():
        v = getattr(i, key)
        if v < rng["min"] - 1e-9 or v > rng["max"] + 1e-9:
            span = f"fixed at {rng['min']:g}" if rng["min"] == rng["max"] else f"{rng['min']:g} – {rng['max']:g}"
            out.append(
                f"{INPUT_LABELS[key]} {v:g} is outside the data ({span}); the output is an extrapolation."
            )
    return out


def run_model(model: ModelKind, i: TwinInputs) -> TwinOutput:
    label, approach, source = MODEL_META[model]
    base = {"model": model, "modelLabel": label, "approach": approach, "source": source}
    try:
        values = TWINS.predict(model, i.flow_kgh, i.P_in_bar, i.P_out_bar, i.rho)
    except Exception as exc:
        return TwinOutput(**base, error=f"{label} model could not solve these inputs ({exc}).")
    return TwinOutput(**base, outputs=Outputs(**values), warnings=range_warnings(i))


@app.get("/health")
def health():
    return {"status": "ok", "trained_at": INFO["trained_at"]}


@app.get("/info")
def info():
    return INFO


@app.post("/predict", response_model=TwinOutput)
def predict(req: PredictRequest):
    validate(req.inputs)
    out = run_model(req.model, req.inputs)
    if out.error:
        raise HTTPException(422, out.error)
    return out


@app.post("/compare", response_model=list[TwinOutput])
def compare(inputs: TwinInputs):
    validate(inputs)
    return [run_model(m, inputs) for m in MODEL_ORDER]


@app.post("/curve", response_model=list[ModelCurve])
def curve(inputs: TwinInputs):
    """Brake power of every model across the data's flow range, at the given pressures and density."""
    validate(inputs)
    rng = INFO["training_ranges"]["flow_kgh"]
    lo, hi = min(rng["min"], inputs.flow_kgh), max(rng["max"], inputs.flow_kgh)
    flows = [lo + (hi - lo) * k / (CURVE_POINTS - 1) for k in range(CURVE_POINTS)]
    out = []
    for m in MODEL_ORDER:
        points = []
        for f in flows:
            try:
                brake = TWINS.predict(m, f, inputs.P_in_bar, inputs.P_out_bar, inputs.rho)["brake_kW"]
            except Exception:
                brake = None
            points.append(CurvePoint(flow_kgh=f, brake_kW=brake))
        out.append(ModelCurve(model=m, points=points))
    return out
