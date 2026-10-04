"""Thin wrapper around ``speechmos`` DNSMOS with per-process thread limiting.

``speechmos`` builds its ONNX sessions lazily and caches them in a module-level
global. It calls ``onnxruntime.InferenceSession`` with default options (all
cores), so with several worker processes we would oversubscribe the CPU. We
monkeypatch ``onnxruntime.InferenceSession`` *before the first call* to force a
single intra/inter-op thread. This must be done once per worker process.
"""

from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger("aqfilter")

DNSMOS_KEYS = ("ovrl_mos", "sig_mos", "bak_mos", "p808_mos")


def set_thread_env() -> None:
    """Best-effort env vars limiting native math thread pools."""
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, "1")


def limit_onnx_threads() -> None:
    """Patch onnxruntime so every session uses a single thread."""
    import onnxruntime as ort

    if getattr(ort, "_aqfilter_threads_limited", False):
        return
    original = ort.InferenceSession

    def limited_inference_session(*args, **kwargs):
        options = kwargs.get("sess_options")
        if options is None:
            options = ort.SessionOptions()
            kwargs["sess_options"] = options
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        return original(*args, **kwargs)

    ort.InferenceSession = limited_inference_session
    ort._aqfilter_threads_limited = True


def worker_init() -> None:
    """Multiprocessing Pool initializer: limit threads and warm up the model."""
    set_thread_env()
    limit_onnx_threads()
    warmup()


def warmup() -> None:
    """Load the ONNX sessions once per process with a valid 9.01 s clip."""
    try:
        n = int(9.01 * 16000)
        t = np.arange(n, dtype=np.float32) / 16000.0
        tone = (0.1 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
        run_dnsmos(tone)
    except Exception as exc:  # noqa: BLE001 - warmup must never kill a worker
        log.warning("DNSMOS warmup failed: %s", exc)


def run_dnsmos(x16: np.ndarray) -> dict:
    """Run DNSMOS on a 1-D float32 signal at 16 kHz; return MOS dict.

    Raises on failure so the caller can record the error.
    """
    import numpy as np
    from speechmos import dnsmos as sm_dnsmos

    x = np.asarray(x16, dtype=np.float32).reshape(-1)
    if x.size == 0:
        # speechmos would loop forever padding an empty array.
        raise ValueError("empty audio passed to DNSMOS")
    if not np.isfinite(x).all():
        raise ValueError("non-finite audio passed to DNSMOS")
    x = np.clip(x, -1.0, 1.0)
    result = sm_dnsmos.run(x, 16000)
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected DNSMOS result type: {type(result)!r}")
    return {k: float(result[k]) for k in DNSMOS_KEYS}
