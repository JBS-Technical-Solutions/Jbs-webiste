"""
FastAPI backend for the JBS methanol heating-media digital twin
(CH3OH → CO + 2H2 with variable jacket / heating-media temperature).

Run:  uvicorn main:app --reload --port 8003
Docs: http://localhost:8003/docs
"""

import json
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from meoh.notebook import PARALLEL_NB, PHYSICS_NB, PINN_NB, SERIAL_NB
from meoh.twins import OUTPUT_COLS, Twins

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
REQUIRED = ["serial.joblib", "parallel.joblib", "pinn.pt", "pinn_refs.json", "metrics.json"]

missing = [f for f in REQUIRED if not (ARTIFACTS / f).exists()]
if missing:
    raise RuntimeError(f"Missing model files {missing} in {ARTIFACTS}. Run `python train.py` first.")

TWINS = Twins(ARTIFACTS)
INFO = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))

ModelKind = Literal["physics", "serial", "parallel", "pinn"]
MODEL_ORDER: list[ModelKind] = ["physics", "serial", "parallel", "pinn"]

MODEL_META = {
    "physics": ("Physics", "LHHW kinetics → plug-flow ODEs (mass, energy, Ergun) → axial profile", PHYSICS_NB.name),
    "serial": ("Serial Hybrid", "Physics ODEs with a learned reaction rate inside", SERIAL_NB.name),
    "parallel": ("Parallel Hybrid", "Physics baseline plus an ML correction of its error", PARALLEL_NB.name),
    "pinn": ("PINN", "Physics-Informed Neural Network", PINN_NB.name),
}

INPUT_LABELS = {
    "T_in_C": "Inlet temperature",
    "P_in_bar_g": "Inlet pressure",
    "T_heat_C": "Heating media temperature",
    "F_in_kgmole_h": "Methanol flow",
}


class TwinInputs(BaseModel):
    T_in_C: float = Field(ge=0, le=1000, description="Inlet temperature (°C)")
    P_in_bar_g: float = Field(ge=0, le=50, description="Inlet pressure (bar_g)")
    T_heat_C: float = Field(ge=0, le=1000, description="Heating media temperature (°C)")
    F_in_kgmole_h: float = Field(ge=0, le=50, description="Methanol molar flow (kgmole/h)")


class PredictRequest(BaseModel):
    model: ModelKind
    inputs: TwinInputs


class Outputs(BaseModel):
    T_02: float = Field(description="Temperature at 0.2 m (°C)")
    T_04: float
    T_06: float
    T_08: float
    T_10: float = Field(description="Outlet temperature at 1.0 m (°C)")
    P_out_bar_g: float
    Q_kW: float = Field(description="Total heat input (kW); negative = heat lost")
    X_pct: float = Field(description="Overall methanol conversion (%)")


class TwinOutput(BaseModel):
    model: ModelKind
    modelLabel: str
    approach: str
    source: str
    outputs: Optional[Outputs] = None
    physics_ref: Optional[Outputs] = Field(None, description="The model's own calibrated-physics branch")
    eta: Optional[float] = None
    error: Optional[str] = None
    warnings: list[str] = []


app = FastAPI(title="JBS Methanol Heating Media Digital Twin API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if API_KEY and request.url.path != "/" and request.headers.get("x-api-key") != API_KEY:
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/")
def root():
    return {"service": "JBS methanol heating-media digital twin API"}


def to_outputs(values: dict) -> Outputs:
    keys = ["T_02", "T_04", "T_06", "T_08", "T_10", "P_out_bar_g", "Q_kW", "X_pct"]
    return Outputs(**{k: values[c] for k, c in zip(keys, OUTPUT_COLS)})


def range_warnings(i: TwinInputs) -> list[str]:
    out = []
    for key, rng in INFO["training_ranges"].items():
        v = getattr(i, key)
        if v < rng["min"] or v > rng["max"]:
            out.append(
                f"{INPUT_LABELS[key]} {v:g} is outside the data range "
                f"({rng['min']:g} – {rng['max']:g}); the output is an extrapolation."
            )
    return out


P_ATM_BAR = 1.01325


def output_warnings(label: str, o: Outputs) -> list[str]:
    out = []
    if o.P_out_bar_g < -P_ATM_BAR:
        out.append(
            f"{label}: outlet pressure {o.P_out_bar_g:,.1f} bar_g is below absolute vacuum, "
            "so its pressure-drop result is not physical at these inputs."
        )
    return out


def run_model(model: ModelKind, i: TwinInputs) -> TwinOutput:
    label, approach, source = MODEL_META[model]
    base = {"model": model, "modelLabel": label, "approach": approach, "source": source}
    try:
        values = TWINS.predict(model, i.T_in_C, i.P_in_bar_g, i.T_heat_C, i.F_in_kgmole_h)
    except Exception as exc:
        return TwinOutput(**base, error=f"{label} model could not solve these inputs ({exc}).")
    outputs = to_outputs(values)
    return TwinOutput(
        **base,
        outputs=outputs,
        physics_ref=to_outputs(values["physics_ref"]) if "physics_ref" in values else None,
        eta=values.get("eta"),
        warnings=range_warnings(i) + output_warnings(label, outputs),
    )


@app.get("/health")
def health():
    return {"status": "ok", "trained_at": INFO["trained_at"], "physics_source": PHYSICS_NB.name}


@app.get("/info")
def info():
    return INFO


@app.post("/predict", response_model=TwinOutput)
def predict(req: PredictRequest):
    out = run_model(req.model, req.inputs)
    if out.error:
        raise HTTPException(422, out.error)
    return out


@app.post("/compare", response_model=list[TwinOutput])
def compare(inputs: TwinInputs):
    return [run_model(m, inputs) for m in MODEL_ORDER]
