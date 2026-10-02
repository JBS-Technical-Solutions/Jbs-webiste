"""PINN network + differentiable TEMA physics residuals (from PINN_TEMA_Udata.ipynb)."""

import math

import torch
import torch.nn as nn

from .physics import A_FLOW_TUBE, A_O_TOTAL, A_S, D_E, D_I, D_O, K_WALL, R_FI, R_FO


class HeatExchangerPINN(nn.Module):
    def __init__(self, in_dim=4, out_dim=3, hidden=(128, 128, 64)):
        super().__init__()
        layers, prev = [], in_dim
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.SiLU()]
            prev = h
        layers.append(nn.Linear(prev, out_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def _water_props(T_c):
    T = torch.clamp(T_c, 1.0, 100.0)
    rho = 1000.0 - 0.0178 * torch.abs(T - 4.0) ** 1.7
    mu = 0.00179 * torch.exp(-0.0247 * T)
    cp = 4182.0 - 0.25 * T
    k = 0.57 + 0.0017 * T
    return rho, mu, cp, k, (cp * mu) / k


def _air_props(T_c, P_atm=101325.0):
    T_k = T_c + 273.15
    rho = P_atm / (287.05 * T_k)
    mu_ref, T_ref, S = 1.716e-5, 273.15, 110.4
    mu = mu_ref * ((T_k / T_ref) ** 1.5) * ((T_ref + S) / (T_k + S))
    cp = 1005.0 + 0.05 * T_c
    k = 0.0241 + 7.5e-5 * T_c
    return rho, mu, cp, k, (cp * mu) / k


_R_COND = (D_O * math.log(D_O / D_I)) / (2.0 * K_WALL)


def tema_U_and_outlets_torch(m_air, m_water, T_air_in, T_water_in, T_air_out, T_water_out):
    rho_w, mu_w, cp_w, k_w, Pr_w = _water_props(0.5 * (T_water_in + T_water_out))
    _, mu_a, cp_a, k_a, Pr_a = _air_props(0.5 * (T_air_in + T_air_out))

    u_i = m_water / (rho_w * A_FLOW_TUBE)
    Re_i = (rho_w * u_i * D_I) / mu_w
    h_i = (0.023 * (Re_i ** 0.8) * (Pr_w ** 0.4) * k_w) / D_I

    G_s = m_air / A_S
    Re_s = (G_s * D_E) / mu_a
    h_o = (0.36 * (Re_s ** 0.55) * (Pr_a ** (1.0 / 3.0)) * k_a) / D_E

    U_phys = 1.0 / ((1.0 / h_i) * (D_O / D_I) + R_FI * (D_O / D_I) + _R_COND + R_FO + 1.0 / h_o)

    C_h = m_air * cp_a
    C_c = m_water * cp_w
    C_min = torch.minimum(C_h, C_c)
    C_max = torch.maximum(C_h, C_c)
    C_r = C_min / C_max
    NTU = (U_phys * A_O_TOTAL) / C_min
    E = torch.sqrt(1.0 + C_r ** 2)
    exp_term = torch.exp(-NTU * E)
    denom = torch.clamp(1.0 - exp_term, min=1e-12)
    epsilon = 2.0 / (1.0 + C_r + E * ((1.0 + exp_term) / denom))
    Q = epsilon * C_min * (T_air_in - T_water_in)
    return U_phys, T_air_in - Q / C_h, T_water_in + Q / C_c


def physics_residuals(m_air, m_water, T_air_in, T_water_in, U, T_air_out, T_water_out):
    U_phys, Ta_phys, Tw_phys = tema_U_and_outlets_torch(
        m_air, m_water, T_air_in, T_water_in, T_air_out, T_water_out
    )
    u_scale = torch.clamp(torch.abs(U_phys), min=1.0)
    t_scale = torch.clamp(torch.abs(T_air_in - T_water_in), min=1.0)
    r_U = (U - U_phys) / u_scale
    r_Ta = (T_air_out - Ta_phys) / t_scale
    r_Tw = (T_water_out - Tw_phys) / t_scale

    pen_cool = torch.relu(T_air_out - T_air_in + 0.5)
    pen_heat = torch.relu(T_water_in - T_water_out + 0.5)
    pen_dt1 = torch.relu(1.0 - (T_air_in - T_water_out))
    pen_dt2 = torch.relu(1.0 - (T_air_out - T_water_in))
    pen_U = torch.relu(1.0 - U)
    return r_U, r_Ta, r_Tw, pen_cool, pen_heat, pen_dt1, pen_dt2, pen_U
