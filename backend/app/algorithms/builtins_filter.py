"""Filtering & smoothing algorithms."""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from .registry import AlgorithmSpec, register_builtin


def _pick_numeric_columns(df: pd.DataFrame, columns: Optional[List[str]]) -> List[str]:
    if columns:
        for c in columns:
            if c not in df.columns:
                raise ValueError(f"column not found: {c}")
        return columns
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


# ---------------------------------------------------------------- moving average
def _moving_average(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    window: int = 5,
    center: bool = True,
) -> pd.DataFrame:
    cols = _pick_numeric_columns(df, columns)
    out = df.copy()
    for c in cols:
        out[f"{c}_ma{window}"] = df[c].rolling(window=window, center=center, min_periods=1).mean()
    return out


register_builtin(
    AlgorithmSpec(
        slug="moving_average",
        name="Moving average",
        category="filter",
        description="Use to smooth out short-term fluctuations and see the overall trend — the simplest smoother (rolling mean of width N), but it blunts peaks.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "window": {"type": "integer", "default": 5, "minimum": 2},
            "center": {"type": "boolean", "default": True},
        },
        returns="dataframe",
        tags=["filter", "smoothing"],
    ),
    _moving_average,
)


# ---------------------------------------------------------------- median filter
def _median_filter(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    window: int = 5,
) -> pd.DataFrame:
    cols = _pick_numeric_columns(df, columns)
    out = df.copy()
    for c in cols:
        out[f"{c}_med{window}"] = df[c].rolling(window=window, center=True, min_periods=1).median()
    return out


register_builtin(
    AlgorithmSpec(
        slug="median_filter",
        name="Median filter",
        category="filter",
        description="Use to remove occasional spikes / glitches from a signal without disturbing the rest — a rolling median, robust to outlier spikes that would skew a mean.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "window": {"type": "integer", "default": 5, "minimum": 2},
        },
        returns="dataframe",
        tags=["filter", "robust"],
    ),
    _median_filter,
)


# ---------------------------------------------------------------- gaussian filter
def _gaussian_filter(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    sigma: float = 2.0,
) -> pd.DataFrame:
    from scipy.ndimage import gaussian_filter1d

    cols = _pick_numeric_columns(df, columns)
    out = df.copy()
    for c in cols:
        arr = df[c].astype(float).to_numpy()
        out[f"{c}_gauss"] = gaussian_filter1d(arr, sigma=sigma, mode="nearest")
    return out


register_builtin(
    AlgorithmSpec(
        slug="gaussian_filter",
        name="Gaussian filter",
        category="filter",
        description="Use to smooth a signal and suppress high-frequency noise while keeping the slow trend — 1-D Gaussian smoothing controlled by σ.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "sigma": {"type": "number", "default": 2.0, "minimum": 0.1},
        },
        returns="dataframe",
        tags=["filter", "smoothing"],
    ),
    _gaussian_filter,
)


# ---------------------------------------------------------------- savgol filter
def _savgol_filter(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    window_length: int = 11,
    polyorder: int = 3,
) -> pd.DataFrame:
    from scipy.signal import savgol_filter

    if window_length % 2 == 0:
        raise ValueError("window_length must be odd")
    if polyorder >= window_length:
        raise ValueError("polyorder must be < window_length")
    cols = _pick_numeric_columns(df, columns)
    out = df.copy()
    for c in cols:
        arr = df[c].astype(float).to_numpy()
        out[f"{c}_savgol"] = savgol_filter(arr, window_length=window_length, polyorder=polyorder, mode="interp")
    return out


register_builtin(
    AlgorithmSpec(
        slug="savgol_filter",
        name="Savitzky-Golay filter",
        category="filter",
        description="Use to smooth a noisy signal while preserving peak shape and inflection points (better than a moving average) — Savitzky-Golay polynomial least-squares smoothing.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "window_length": {"type": "integer", "default": 11, "minimum": 3, "description": "Must be odd"},
            "polyorder": {"type": "integer", "default": 3, "minimum": 1, "description": "Must be < window_length"},
        },
        returns="dataframe",
        tags=["filter", "smoothing", "savgol"],
    ),
    _savgol_filter,
)


# ---------------------------------------------------------------- butterworth filter
def _butter_filter(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    cutoff_hz: float = 1.0,
    fs_hz: float = 100.0,
    order: int = 4,
    kind: str = "lowpass",
) -> pd.DataFrame:
    from scipy.signal import butter, filtfilt

    if kind not in ("lowpass", "highpass"):
        raise ValueError("kind must be 'lowpass' or 'highpass'")
    nyq = 0.5 * fs_hz
    wn = cutoff_hz / nyq
    if not 0 < wn < 1:
        raise ValueError(f"cutoff/Nyquist ratio out of (0,1) — got {wn}")
    b, a = butter(order, wn, btype=kind)
    cols = _pick_numeric_columns(df, columns)
    out = df.copy()
    for c in cols:
        arr = df[c].astype(float).to_numpy()
        if len(arr) > 3 * max(len(b), len(a)):
            out[f"{c}_butter"] = filtfilt(b, a, arr)
        else:
            out[f"{c}_butter"] = arr  # too short to filter — pass through
    return out


register_builtin(
    AlgorithmSpec(
        slug="butterworth_filter",
        name="Butterworth filter",
        category="filter",
        description="Use to remove noise by frequency when you know the sampling rate — zero-phase Butterworth low-pass (kills high-freq noise) or high-pass (removes baseline drift).",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False},
            "cutoff_hz": {"type": "number", "default": 1.0, "minimum": 0.0001},
            "fs_hz": {"type": "number", "default": 100.0, "minimum": 0.001},
            "order": {"type": "integer", "default": 4, "minimum": 1, "maximum": 10},
            "kind": {"type": "string", "enum": ["lowpass", "highpass"], "default": "lowpass"},
        },
        returns="dataframe",
        tags=["filter", "signal", "butterworth"],
    ),
    _butter_filter,
)


# ---------------------------------------------------------------- FFT spectrum
def _fft_frequency_analysis(
    df: pd.DataFrame,
    *,
    columns: Optional[List[str]] = None,
    fs_hz: float = 1.0,
    window: str = "hann",
    detrend: bool = True,
) -> pd.DataFrame:
    """Single-sided amplitude spectrum via FFT. Returns frequency_hz + one
    <col>_amplitude column per input signal — used to find dominant
    frequencies / periodic components. `fs_hz` is the sampling rate."""
    cols = _pick_numeric_columns(df, columns)
    if not cols:
        raise ValueError("没有可做 FFT 的数值列")
    if fs_hz <= 0:
        raise ValueError("fs_hz(采样频率)必须 > 0")
    n = len(df)
    if n < 2:
        raise ValueError("做 FFT 至少需要 2 行数据")

    wname = (window or "none").lower()
    win = {
        "none": np.ones(n), "hann": np.hanning(n),
        "hamming": np.hamming(n), "blackman": np.blackman(n),
    }.get(wname)
    if win is None:
        raise ValueError("window 必须是 none / hann / hamming / blackman 之一")
    coherent_gain = float(win.mean()) or 1.0

    freqs = np.fft.rfftfreq(n, d=1.0 / fs_hz)
    out = {"frequency_hz": freqs}
    for c in cols:
        arr = df[c].astype(float).to_numpy()
        mean = np.nanmean(arr)
        arr = np.nan_to_num(arr, nan=(mean if np.isfinite(mean) else 0.0))
        if detrend:
            arr = arr - arr.mean()
        amp = (2.0 / n) * np.abs(np.fft.rfft(arr * win)) / coherent_gain
        if len(amp):
            amp[0] /= 2.0                      # DC bin is one-sided
            if n % 2 == 0:
                amp[-1] /= 2.0                 # Nyquist bin is one-sided
        out[f"{c}_amplitude"] = amp
    return pd.DataFrame(out)


register_builtin(
    AlgorithmSpec(
        slug="fft_frequency_analysis",
        name="FFT 频谱分析",
        category="filter",
        description="Use to find the dominant frequency / periodic components hidden in a time-domain signal — FFT to a single-sided amplitude spectrum (frequency_hz vs <col>_amplitude). Needs sampling rate fs_hz.",
        params_schema={
            "columns": {"type": "array", "items": "string", "required": False,
                        "description": "要做 FFT 的数值列;留空=全部数值列"},
            "fs_hz": {"type": "number", "default": 1.0, "minimum": 1e-9,
                      "description": "采样频率(Hz)。例如每 0.01s 一个点 → 100"},
            "window": {"type": "string", "enum": ["none", "hann", "hamming", "blackman"],
                       "default": "hann", "description": "窗函数,抑制频谱泄漏"},
            "detrend": {"type": "boolean", "default": True, "description": "先去均值(去掉直流分量)"},
        },
        returns="dataframe",
        tags=["filter", "signal", "fft", "frequency", "fourier", "傅里叶"],
    ),
    _fft_frequency_analysis,
)


# ---------------------------------------------------------------- peak detection
def _find_peaks(
    df: pd.DataFrame,
    *,
    column: str,
    prominence: Optional[float] = None,
    distance: Optional[int] = None,
    height: Optional[float] = None,
) -> pd.DataFrame:
    """Locate local maxima (peaks) in a 1-D signal. One row per peak: its index,
    value, and prominence."""
    from scipy.signal import find_peaks

    if column not in df.columns:
        raise ValueError(f"column not found: {column}. available: {list(df.columns)}")
    y = df[column].astype(float).to_numpy()
    kw = {}
    if prominence is not None:
        kw["prominence"] = prominence
    if distance is not None:
        kw["distance"] = max(1, int(distance))
    if height is not None:
        kw["height"] = height
    idx, props = find_peaks(y, **kw)
    return pd.DataFrame({
        "peak_index": idx.astype(int),
        f"{column}_value": y[idx] if len(idx) else np.array([], dtype=float),
        "prominence": props.get("prominences", np.full(len(idx), np.nan)),
    })


register_builtin(
    AlgorithmSpec(
        slug="find_peaks",
        name="Peak detection",
        category="filter",
        description="Use to locate the peaks / local maxima in a signal — count them, find their positions and heights (e.g. cycle counting, picking spectral peaks). Returns one row per peak.",
        params_schema={
            "column": {"type": "string", "required": True},
            "prominence": {"type": "number", "required": False, "description": "Min peak prominence — raise it to ignore small bumps"},
            "distance": {"type": "integer", "required": False, "description": "Min samples between adjacent peaks"},
            "height": {"type": "number", "required": False, "description": "Min peak height"},
        },
        returns="dataframe",
        tags=["filter", "signal", "peaks"],
        aliases=["peak_detector", "peak_detection", "peaks", "find_peak"],
    ),
    _find_peaks,
)
