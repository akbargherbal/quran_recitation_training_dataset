"""Classical (non-learned) audio quality metrics.

All constants come from :mod:`aqfilter.config`; definitions are documented in
README.md (SPEC section 5.2).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import welch

from aqfilter.config import (
    BANDWIDTH_DROP_DB,
    BANDWIDTH_MAX_GAP_BINS,
    BANDWIDTH_NPERSEG,
    BANDWIDTH_SMOOTH_BINS,
    CLIP_ABS_THRESHOLD,
    EPS,
    FRAME_MS,
    HOP_MS,
    NOISE_PERCENTILE,
    SILENCE_DROP_DB,
    SPECTRAL_EPS,
    SPEECH_PERCENTILE,
    TARGET_SR,
)


def frame_rms_db(
    x: np.ndarray,
    sr: int = TARGET_SR,
    frame_ms: float = FRAME_MS,
    hop_ms: float = HOP_MS,
) -> np.ndarray:
    """Per-frame RMS in dBFS (25 ms frames, 10 ms hop by default)."""
    x = np.asarray(x, dtype=np.float64)
    frame = max(1, int(round(frame_ms * sr / 1000.0)))
    hop = max(1, int(round(hop_ms * sr / 1000.0)))
    if x.size < frame:
        x = np.pad(x, (0, frame - x.size))
    n_frames = 1 + (x.size - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = x[idx]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return 20.0 * np.log10(rms + EPS)


def level_metrics(x16: np.ndarray) -> dict:
    """noise floor, speech level, estimated SNR and silence ratio."""
    db = frame_rms_db(x16)
    noise_floor = float(np.percentile(db, NOISE_PERCENTILE))
    speech = float(np.percentile(db, SPEECH_PERCENTILE))
    return {
        "noise_floor_db": noise_floor,
        "speech_db": speech,
        "snr_est_db": speech - noise_floor,
        "silence_ratio": float(np.mean(db < speech - SILENCE_DROP_DB)),
    }


def clipping_ratio(x_native: np.ndarray) -> float:
    """Fraction of native-rate samples at or beyond the clip threshold."""
    x = np.asarray(x_native)
    if x.size == 0:
        return 0.0
    return float(np.mean(np.abs(x) >= CLIP_ABS_THRESHOLD))


def bandwidth_hz(x_native: np.ndarray, sr: int) -> float:
    """Upper edge of the main spectral band, relative to the spectrum peak.

    Uses a lightly-smoothed Welch PSD on the native-rate signal. The bandwidth
    is the highest frequency of the *contiguous* band (from the first bin that
    rises above ``peak - BANDWIDTH_DROP_DB``) allowing only short gaps. Taking a
    contiguous band rather than a single stray bin avoids the synthetic
    Nyquist-bin artifact and isolated spikes. Returns 0.0 when nothing reaches
    the peak-relative threshold.
    """
    x = np.asarray(x_native, dtype=np.float64)
    if x.size < 8:
        return 0.0
    nperseg = int(min(BANDWIDTH_NPERSEG, x.size))
    f, pxx = welch(x, fs=sr, nperseg=nperseg)
    pdb = 10.0 * np.log10(pxx + SPECTRAL_EPS)

    if BANDWIDTH_SMOOTH_BINS > 1 and pdb.size >= BANDWIDTH_SMOOTH_BINS:
        kernel = np.ones(BANDWIDTH_SMOOTH_BINS) / BANDWIDTH_SMOOTH_BINS
        pad = BANDWIDTH_SMOOTH_BINS // 2
        pdb = np.convolve(np.pad(pdb, pad, mode="edge"), kernel, mode="valid")

    peak = float(np.max(pdb))
    above = pdb >= peak - BANDWIDTH_DROP_DB

    edge = None
    misses = 0
    started = False
    for i, is_above in enumerate(above):
        if is_above:
            edge = i
            misses = 0
            started = True
        elif started:
            misses += 1
            if misses > BANDWIDTH_MAX_GAP_BINS:
                break
    if edge is None:
        return 0.0
    return float(f[edge])


def classical_metrics(
    mono_native: np.ndarray, sr: int, x16: np.ndarray
) -> dict:
    """Compute every classical metric for one clip."""
    out = level_metrics(x16)
    out["clipping_ratio"] = clipping_ratio(mono_native)
    out["bandwidth_hz"] = bandwidth_hz(mono_native, sr)
    return out
