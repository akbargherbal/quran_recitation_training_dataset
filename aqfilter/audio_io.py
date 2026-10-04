"""Audio decoding, downmixing, resampling and clamping.

Decoding tries ``soundfile`` first (libsndfile >= 1.1 supports MP3) and falls
back to an ``ffmpeg`` subprocess. The native sample rate is preserved for the
spectral metrics; a 16 kHz mono copy is produced for DNSMOS and frame metrics.
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from aqfilter.config import TARGET_SR

log = logging.getLogger("aqfilter")


class DecodeError(RuntimeError):
    """Raised when a file cannot be decoded by any available backend."""


def _downmix(data: np.ndarray) -> np.ndarray:
    if data.ndim == 2:
        return data.mean(axis=1)
    return data


def _decode_soundfile(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = _downmix(np.asarray(data, dtype=np.float32))
    if mono.size == 0:
        raise DecodeError("decoded zero samples")
    return mono, int(sr)


def _decode_ffmpeg(path: Path) -> tuple[np.ndarray, int]:
    if shutil.which("ffmpeg") is None:
        raise DecodeError("ffmpeg not on PATH")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
             str(tmp_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise DecodeError(f"ffmpeg failed: {proc.stderr.strip()[:300]}")
        return _decode_soundfile(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def decode(path: str | Path) -> tuple[np.ndarray, int]:
    """Decode to mono float32 at the native sample rate.

    Returns ``(mono, sample_rate)``. Raises :class:`DecodeError` if both
    backends fail.
    """
    path = Path(path)
    errors = []
    for backend, fn in (("soundfile", _decode_soundfile), ("ffmpeg", _decode_ffmpeg)):
        try:
            mono, sr = fn(path)
            if not np.isfinite(mono).all():
                raise DecodeError("non-finite samples")
            return mono, sr
        except Exception as exc:  # noqa: BLE001 - we want to try the next backend
            errors.append(f"{backend}: {exc}")
    raise DecodeError("; ".join(errors) or "unknown decode failure")


def resample_to_16k(mono: np.ndarray, sr: int) -> np.ndarray:
    """Resample to 16 kHz with polyphase filtering (no-op at 16 kHz)."""
    if sr == TARGET_SR:
        return np.asarray(mono, dtype=np.float32)
    g = math.gcd(int(TARGET_SR), int(sr))
    up = TARGET_SR // g
    down = int(sr) // g
    return resample_poly(mono, up, down).astype(np.float32)


def clamp(x: np.ndarray) -> np.ndarray:
    """Clamp to [-1, 1] float32 (DNSMOS raises outside this range)."""
    return np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
