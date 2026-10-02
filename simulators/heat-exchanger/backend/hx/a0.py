"""
Physics-only model loaded directly from A0-PhysicsModelOnly.ipynb.

The notebook cell that defines `rate_shell_and_tube_1_2` is executed as-is, so the
website always runs the notebook's own physics (restart the backend after editing it).
"""

import contextlib
import io
import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[2] / "A0-PhysicsModelOnly.ipynb"


def _load_rate_function():
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for cell in cells:
        src = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        if cell["cell_type"] == "code" and "def rate_shell_and_tube_1_2(" in src:
            namespace: dict = {}
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(src, str(NOTEBOOK), "exec"), namespace)
            return namespace["rate_shell_and_tube_1_2"]
    raise RuntimeError(f"rate_shell_and_tube_1_2 not found in {NOTEBOOK.name}")


_a0_rate = _load_rate_function()


def a0_physics(T_air_in, m_dot_air, T_water_in, m_dot_water):
    """Run A0's rating (mass flows in kg/s) and map its output to the API field names."""
    r = _a0_rate(T_air_in=T_air_in, m_dot_air=m_dot_air, T_water_in=T_water_in, m_dot_water=m_dot_water)
    return {
        "U": r["Overall_U (W/m²·K)"],
        "T_air_out": r["Air_Outlet_Temp (°C)"],
        "T_water_out": r["Water_Outlet_Temp (°C)"],
        "Q_kW": r["Calculated_Duty (kW)"],
        "NTU": r["NTU"],
        "epsilon": r["Exchanger_Effectiveness (ε)"],
        "iterations": r["Iterations_to_Converge"],
        "hydraulics": {
            "h_i": r["h_inside_water (W/m²·K)"],
            "h_o": r["h_outside_air (W/m²·K)"],
            "Re_tube": r["Re_Tube (Water)"],
            "Re_shell": r["Re_Shell (Air)"],
            "dP_tube_kPa": r["dP_Tube_Water (kPa)"],
            "dP_shell_kPa": r["dP_Shell_Air (kPa)"],
        },
    }
