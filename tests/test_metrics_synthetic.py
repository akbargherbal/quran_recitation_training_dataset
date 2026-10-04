"""Synthetic sanity tests for the classical and learned metrics (acceptance #4)."""

import numpy as np
from scipy.signal import butter, sosfilt

from aqfilter.audio_io import clamp
from aqfilter.dnsmos_wrap import run_dnsmos, set_thread_env
from aqfilter.metrics import bandwidth_hz, clipping_ratio, level_metrics

set_thread_env()

SR = 16000


def _burst_signal(duration: float = 4.0, freq: float = 180.0) -> np.ndarray:
    """Amplitude-modulated tone with silence gaps, so a noise floor exists."""
    t = np.arange(int(duration * SR)) / SR
    tone = 0.3 * np.sin(2 * np.pi * freq * t)
    env = np.zeros_like(t)
    period = int(0.8 * SR)
    on = int(0.5 * SR)
    for start in range(0, len(t), period):
        env[start:start + on] = 1.0
    return clamp((tone * env).astype(np.float32))


def _add_noise(x: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    rms = np.sqrt(np.mean(x.astype(np.float64) ** 2))
    noise_rms = rms / (10.0 ** (snr_db / 20.0))
    rng = np.random.default_rng(seed)
    return clamp(x + rng.normal(0.0, noise_rms, x.shape).astype(np.float32))


def test_snr_and_bakmos_decrease_with_noise():
    clean = _burst_signal()
    snrs = [40.0, 15.0, 0.0]
    est = []
    bak = []
    for snr in snrs:
        y = _add_noise(clean, snr)
        est.append(level_metrics(y)["snr_est_db"])
        bak.append(run_dnsmos(y)["bak_mos"])

    assert est[0] > est[1] > est[2], f"snr_est_db not decreasing: {est}"
    assert bak[0] > bak[1] > bak[2], f"bak_mos not decreasing: {bak}"


def test_lowpass_reduces_bandwidth():
    rng = np.random.default_rng(1)
    white = clamp(rng.normal(0.0, 0.2, SR * 3).astype(np.float32))
    sos = butter(8, 2000.0, btype="low", fs=SR, output="sos")
    filtered = clamp(sosfilt(sos, white).astype(np.float32))

    bw_white = bandwidth_hz(white, SR)
    bw_low = bandwidth_hz(filtered, SR)
    assert bw_low < bw_white - 1000, f"{bw_low} !< {bw_white}"
    assert bw_low < 6000, f"low-passed bandwidth too high: {bw_low}"


def test_clipping_increases_ratio():
    t = np.arange(SR * 2) / SR
    clean = clamp((0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32))
    clipped = clamp((clean * 8.0).astype(np.float32))
    assert clipping_ratio(clipped) > clipping_ratio(clean)
    assert clipping_ratio(clipped) > 0.5
