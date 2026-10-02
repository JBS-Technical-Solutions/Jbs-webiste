"""
TEMA Type A shell, 2-pass tubes (triangular pitch) — physics shared by all models.
Ported from A0-PhysicsModelOnly / A2-SerialHybrid / ParallelHybridModel / PINN_TEMA_Udata.
"""

import math

N_TUBES = 160
N_PASSES = 2
L_TUBE = 6.0
D_O = 0.020
WALL_THICKNESS = 0.002
PITCH = 0.050
D_S = 0.387
B_BAFFLE = 0.8
K_WALL = 45.0
R_FI = 0.00015
R_FO = 0.00035

D_I = D_O - 2.0 * WALL_THICKNESS
A_O_TOTAL = N_TUBES * (math.pi * D_O * L_TUBE)
N_TUBES_PER_PASS = N_TUBES / N_PASSES
A_FLOW_TUBE = N_TUBES_PER_PASS * (math.pi * D_I ** 2 / 4)
C_PRIME = PITCH - D_O
A_S = (D_S * C_PRIME * B_BAFFLE) / PITCH
D_E = 4.0 * (0.86 * PITCH ** 2 - (math.pi * D_O ** 2 / 4.0)) / (math.pi * D_O)

GEOMETRY = {
    "type": "TEMA Type A, 1 shell / 2 tube passes, triangular pitch",
    "N_tubes": N_TUBES,
    "N_passes": N_PASSES,
    "L_m": L_TUBE,
    "d_o_m": D_O,
    "d_i_m": D_I,
    "pitch_m": PITCH,
    "D_s_m": D_S,
    "baffle_m": B_BAFFLE,
    "A_o_m2": A_O_TOTAL,
    "D_e_m": D_E,
}


def get_water_properties(T_c):
    T = max(1.0, min(float(T_c), 100.0))
    rho = 1000.0 - 0.0178 * abs(T - 4.0) ** 1.7
    mu = 0.00179 * math.exp(-0.0247 * T)
    cp = 4182.0 - 0.25 * T
    k = 0.57 + 0.0017 * T
    Pr = (cp * mu) / k
    return rho, mu, cp, k, Pr


def get_air_properties(T_c, P_atm=101325.0):
    T_k = T_c + 273.15
    rho = P_atm / (287.05 * T_k)
    mu_ref, T_ref, S = 1.716e-5, 273.15, 110.4
    mu = mu_ref * ((T_k / T_ref) ** 1.5) * ((T_ref + S) / (T_k + S))
    cp = 1005.0 + 0.05 * T_c
    k = 0.0241 + 7.5e-5 * T_c
    Pr = (cp * mu) / k
    return rho, mu, cp, k, Pr


def rate_shell_and_tube_1_2(T_air_in, m_dot_air, T_water_in, m_dot_water, tol=1e-5, max_iter=100, omega=0.5):
    """Film coefficients (Dittus–Boelter / Kern) -> U -> 1-2 pass E-NTU. Mass flows in kg/s."""
    T_h_out = T_air_in - 30.0
    T_c_out = T_water_in + 10.0

    for iteration in range(1, max_iter + 1):
        T_h_avg = 0.5 * (T_air_in + T_h_out)
        T_c_avg = 0.5 * (T_water_in + T_c_out)

        rho_w, mu_w, cp_w, k_w, Pr_w = get_water_properties(T_c_avg)
        _, mu_a, cp_a, k_a, Pr_a = get_air_properties(T_h_avg)

        u_i = m_dot_water / (rho_w * A_FLOW_TUBE)
        Re_i = (rho_w * u_i * D_I) / mu_w
        h_i = (0.023 * (Re_i ** 0.8) * (Pr_w ** 0.4) * k_w) / D_I

        G_s = m_dot_air / A_S
        Re_s = (G_s * D_E) / mu_a
        h_o = (0.36 * (Re_s ** 0.55) * (Pr_a ** (1.0 / 3.0)) * k_a) / D_E

        R_conv_i = (1.0 / h_i) * (D_O / D_I)
        R_foul_i = R_FI * (D_O / D_I)
        R_cond = (D_O * math.log(D_O / D_I)) / (2.0 * K_WALL)
        U_o = 1.0 / (R_conv_i + R_foul_i + R_cond + R_FO + 1.0 / h_o)

        C_h = m_dot_air * cp_a
        C_c = m_dot_water * cp_w
        C_min, C_max = min(C_h, C_c), max(C_h, C_c)
        C_r = C_min / C_max

        NTU = (U_o * A_O_TOTAL) / C_min
        E = math.sqrt(1.0 + C_r ** 2)
        exp_term = math.exp(-NTU * E)
        epsilon = 2.0 / (1.0 + C_r + E * ((1.0 + exp_term) / (1.0 - exp_term)))

        Q = epsilon * C_min * (T_air_in - T_water_in)
        T_h_out_new = T_air_in - Q / C_h
        T_c_out_new = T_water_in + Q / C_c

        if max(abs(T_h_out_new - T_h_out), abs(T_c_out_new - T_c_out)) < tol:
            T_h_out, T_c_out = T_h_out_new, T_c_out_new
            break

        T_h_out = omega * T_h_out_new + (1.0 - omega) * T_h_out
        T_c_out = omega * T_c_out_new + (1.0 - omega) * T_c_out

    return {
        "U": float(U_o),
        "T_air_out": float(T_h_out),
        "T_water_out": float(T_c_out),
        "Q_kW": float(Q / 1000.0),
        "NTU": float(NTU),
        "epsilon": float(epsilon),
        "iterations": iteration,
    }


def physics_outlets_from_U(U_o, T_air_in, T_water_in, m_dot_air, m_dot_water, tol=1e-5, max_iter=100, omega=0.5):
    """1-2 pass E-NTU outlets for a supplied U (serial hybrid). Mass flows in kg/s."""
    T_h_out = T_air_in - 30.0
    T_c_out = T_water_in + 10.0

    for iteration in range(1, max_iter + 1):
        T_h_avg = 0.5 * (T_air_in + T_h_out)
        T_c_avg = 0.5 * (T_water_in + T_c_out)

        _, _, cp_w, _, _ = get_water_properties(T_c_avg)
        _, _, cp_a, _, _ = get_air_properties(T_h_avg)

        C_h = m_dot_air * cp_a
        C_c = m_dot_water * cp_w
        C_min, C_max = min(C_h, C_c), max(C_h, C_c)
        C_r = C_min / C_max

        NTU = (U_o * A_O_TOTAL) / C_min
        E = math.sqrt(1.0 + C_r ** 2)
        exp_term = math.exp(-NTU * E)
        denom = 1.0 - exp_term
        epsilon = 1.0 if abs(denom) < 1e-15 else 2.0 / (1.0 + C_r + E * ((1.0 + exp_term) / denom))

        Q = epsilon * C_min * (T_air_in - T_water_in)
        T_h_out_new = T_air_in - Q / C_h
        T_c_out_new = T_water_in + Q / C_c

        if max(abs(T_h_out_new - T_h_out), abs(T_c_out_new - T_c_out)) < tol:
            T_h_out, T_c_out = T_h_out_new, T_c_out_new
            break

        T_h_out = omega * T_h_out_new + (1.0 - omega) * T_h_out
        T_c_out = omega * T_c_out_new + (1.0 - omega) * T_c_out

    return {
        "U": float(U_o),
        "T_air_out": float(T_h_out),
        "T_water_out": float(T_c_out),
        "Q_kW": float(Q / 1000.0),
        "NTU": float(NTU),
        "epsilon": float(epsilon),
        "iterations": iteration,
    }


def duty_ntu_eps(U, T_air_in, T_water_in, T_air_out, T_water_out, m_dot_air, m_dot_water):
    """Air-side duty plus NTU / effectiveness implied by a predicted (U, Taout, Twout)."""
    _, _, cp_a, _, _ = get_air_properties(0.5 * (T_air_in + T_air_out))
    _, _, cp_w, _, _ = get_water_properties(0.5 * (T_water_in + T_water_out))
    C_h = m_dot_air * cp_a
    C_c = m_dot_water * cp_w
    C_min = min(C_h, C_c)
    Q = C_h * (T_air_in - T_air_out)
    Q_max = C_min * (T_air_in - T_water_in)
    epsilon = Q / Q_max if Q_max > 0 else 0.0
    return {
        "Q_kW": float(Q / 1000.0),
        "NTU": float(U * A_O_TOTAL / C_min),
        "epsilon": float(min(max(epsilon, 0.0), 1.0)),
    }


def lmtd_counterflow(T_air_in, T_water_in, T_air_out, T_water_out, eps=1e-8):
    dT1 = T_air_in - T_water_out
    dT2 = T_air_out - T_water_in
    if dT1 <= eps or dT2 <= eps:
        return float("nan")
    if abs(dT1 - dT2) < eps:
        return 0.5 * (dT1 + dT2)
    return (dT1 - dT2) / math.log(dT1 / dT2)


def udata_from_lmtd(m_air, m_water, T_air_in, T_water_in, T_air_out, T_water_out):
    """Udata = Qavg / (A · LMTD) from dataset temperatures. Mass flows in kg/s."""
    LMTD = lmtd_counterflow(T_air_in, T_water_in, T_air_out, T_water_out)
    if not math.isfinite(LMTD) or LMTD <= 0.0:
        return float("nan")
    _, _, Cp_h, _, _ = get_air_properties(0.5 * (T_air_out + T_air_in))
    _, _, Cp_c, _, _ = get_water_properties(0.5 * (T_water_in + T_water_out))
    Qh = m_air * Cp_h * (T_air_in - T_air_out)
    Qc = m_water * Cp_c * (T_water_out - T_water_in)
    return 0.5 * (Qh + Qc) / (A_O_TOTAL * LMTD)
