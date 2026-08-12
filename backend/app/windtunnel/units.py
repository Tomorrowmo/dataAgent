"""Unit constants and conversions for wind-tunnel data.

WHY THIS FILE EXISTS
--------------------
The single most dangerous defect in the customer's existing demo is a unit
mismatch: raw ``ca`` files store pressures in **MPa**, while every diagnostic
threshold in the rule book is written in **mmH2O**. The legacy scripts compared
a raw MPa number (e.g. 0.0005) against a threshold of 150 and reported
"normal" — a verdict that happens to be right for the wrong reason and would be
silently wrong the moment a real fault appeared.

Every conversion here is a defined (exact) relation, not an empirical fit:

* ``1 mmH2O = 9.806 65 Pa`` — conventional millimetre of water, fixed by the
  standard gravity ``g_n = 9.806 65 m/s^2`` (CGPM 3rd conference, 1901) and a
  water density of 1000 kg/m^3.  ISO 80000-4 / NIST SP 811 Appendix B.8.
* ``1 kgf/m^2 = 9.806 65 Pa`` — hence **1 kgf/m^2 == 1 mmH2O exactly**.  This is
  why the ``pa`` process report, which prints pressures in kgf/m^2, can be
  compared directly against the mmH2O thresholds in the rule book.
* Isentropic total-to-static pressure ratio for a calorically perfect gas with
  ``gamma = 1.4``:  ``p0/p = (1 + 0.2 M^2)^3.5``  →  ``M = sqrt(5*((p0/p)^(1/3.5) - 1))``.
  NACA Report 1135, "Equations, Tables, and Charts for Compressible Flow"
  (Ames Research Staff, 1953), eq. (44).
"""

from __future__ import annotations

import math

#: Standard gravity (m/s^2), CGPM 1901 — the definition behind both mmH2O and kgf.
G_N = 9.80665

#: Pascals in one conventional millimetre of water column.
PA_PER_MMH2O = G_N

#: mmH2O in one MPa.  1e6 / 9.80665 = 101 971.62…
MMH2O_PER_MPA = 1.0e6 / G_N

#: Ratio of specific heats for air at wind-tunnel conditions.
GAMMA = 1.4


def mpa_to_mmh2o(value: float) -> float:
    """MPa → mmH2O (== kgf/m^2). Used for every ``ca``-file pressure."""
    return value * MMH2O_PER_MPA


def pa_to_mmh2o(value: float) -> float:
    """Pa → mmH2O."""
    return value / PA_PER_MMH2O


def mach_from_pressure_ratio(p0: float, p_static: float) -> float:
    """Isentropic Mach number from a total/static pressure pair.

    NACA TR-1135 eq. (44) with gamma = 1.4::

        p0/p = (1 + (gamma-1)/2 * M^2) ** (gamma/(gamma-1))
             = (1 + 0.2 M^2) ** 3.5

    Returns 0.0 for a non-physical ratio (p0 <= p) rather than raising, so a
    single bad row in a sweep does not abort the whole check.
    """
    if p_static <= 0 or p0 <= 0:
        return 0.0
    ratio = p0 / p_static
    if ratio < 1.0:
        return 0.0
    exponent = (GAMMA - 1.0) / GAMMA  # 1/3.5
    inner = ratio ** exponent - 1.0
    if inner <= 0:
        return 0.0
    return math.sqrt(inner * 2.0 / (GAMMA - 1.0))  # * 5 for gamma=1.4
