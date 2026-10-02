from pathlib import Path

import pandas as pd

from .physics import udata_from_lmtd

DATA_PATH = Path(__file__).resolve().parents[2] / "data.csv"

COLUMNS = {
    "Hot Air flow in Shell": "m_air_kgh",
    "Cooling water flow in Tubes": "m_water_kgh",
    "1 - Temperature": "T_air_in",
    "3 - Temperature": "T_water_in",
    "2 - Temperature": "T_air_out",
    "4 - Temperature": "T_water_out",
    "E-100 - Overall U": "U_actual",
}


def load_dataset(path: Path = DATA_PATH) -> pd.DataFrame:
    """data.csv -> clean frame with kg/s flows and LMTD-based Udata (same as the notebooks)."""
    df_raw = pd.read_csv(path, header=1)
    if "State" in df_raw.columns:
        df_raw = df_raw[df_raw["State"].astype(str).str.startswith("Case")].copy()

    df = df_raw[list(COLUMNS)].rename(columns=COLUMNS).copy()
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().reset_index(drop=True)

    df["m_air"] = df["m_air_kgh"] / 3600.0
    df["m_water"] = df["m_water_kgh"] / 3600.0
    df["Udata"] = [
        udata_from_lmtd(r.m_air, r.m_water, r.T_air_in, r.T_water_in, r.T_air_out, r.T_water_out)
        for r in df.itertuples()
    ]
    return df.dropna(subset=["Udata"]).reset_index(drop=True)
