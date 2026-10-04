"""Module-level tunable constants.

Every heuristic constant in the metrics lives here so it can be adjusted without
touching the algorithms (see SPEC section 5.2).
"""

# --- Frame-level analysis (applied to the 16 kHz downsampled signal) ---------
FRAME_MS = 25.0          # frame length in milliseconds
HOP_MS = 10.0            # frame hop in milliseconds
TARGET_SR = 16000        # target sample rate for DNSMOS + frame metrics

NOISE_PERCENTILE = 10.0  # percentile of frame RMS used as the noise floor
SPEECH_PERCENTILE = 95.0  # percentile of frame RMS used as the speech level
SILENCE_DROP_DB = 35.0   # frames this far below speech level are "silence"

# --- Clipping ----------------------------------------------------------------
CLIP_ABS_THRESHOLD = 0.999

# --- Bandwidth ---------------------------------------------------------------
BANDWIDTH_DROP_DB = 60.0     # peak-relative drop defining the bandwidth edge
BANDWIDTH_SMOOTH_BINS = 5    # moving-average window along the frequency axis
BANDWIDTH_MAX_GAP_BINS = 5   # tolerate this many below-threshold bins inside the band
BANDWIDTH_NPERSEG = 4096     # Welch segment length (capped at signal length)

# --- General -----------------------------------------------------------------
EPS = 1e-10
SPECTRAL_EPS = 1e-20       # floor for Welch PSD in log space (-200 dBFS)
DNSMOS_SR = 16000
DNSMOS_WINDOW_S = 9.01       # informational; speechmos pads to this

# --- Multiprocessing / I/O ---------------------------------------------------
CHUNKSIZE = 8
FLUSH_EVERY = 500
DEFAULT_BENCHMARK_N = 20

# --- Score table schema (column order of scores.csv) -------------------------
IDENTITY_COLUMNS = [
    "filename",
    "path",
    "reciter",
    "kbps_label",
    "surah",
    "ayah",
    "decode_ok",
    "error",
    "duration_s",
    "native_sr",
    "actual_kbps",
]
DNSMOS_COLUMNS = ["ovrl_mos", "sig_mos", "bak_mos", "p808_mos"]
CLASSICAL_COLUMNS = [
    "noise_floor_db",
    "speech_db",
    "snr_est_db",
    "silence_ratio",
    "clipping_ratio",
    "bandwidth_hz",
]
SCORE_COLUMNS = IDENTITY_COLUMNS + DNSMOS_COLUMNS + CLASSICAL_COLUMNS

# --- Threshold metrics (SPEC section 6.1) ------------------------------------
# (metric, direction, floor on margin)
# direction "higher" -> value >= threshold passes; "lower" -> value <= threshold.
THRESHOLD_METRICS = [
    ("ovrl_mos", "higher", 0.05),
    ("sig_mos", "higher", 0.05),
    ("bak_mos", "higher", 0.05),
    ("snr_est_db", "higher", 1.0),
    ("bandwidth_hz", "higher", 250.0),
    ("noise_floor_db", "lower", 1.0),
]

DEFAULT_K = 0.25

# --- Global hard gates (SPEC section 6.3) ------------------------------------
GLOBAL_GATES = {
    "decode_ok": True,
    "duration_s_min": 3.0,
    "duration_s_max": 150.0,
    "speech_db_min": -45.0,
    "clipping_ratio_max": 0.001,
}

# Metrics plotted per reciter (SPEC section 7).
PLOT_METRICS = ["ovrl_mos", "bak_mos", "noise_floor_db", "bandwidth_hz"]

# Fixed RNG seed for the random_rejects review group (SPEC section 8.3).
REVIEW_SEED = 42
