"""Tunable constants for the bulk scan (#218)."""

from __future__ import annotations

# --- Selection (Stage 0) ---
DEFAULT_TARGET_REPO_COUNT = 7500
MIN_STARS = 100
MAX_STARS = 10000
PUSHED_WITHIN_DAYS = 365

# --- Inventory (Stage 1) ---
DOC_FILE_EXTENSIONS = (".md", ".rst", ".txt", ".adoc")
MAX_DOC_FILES_PER_REPO = 200  # circuit-breaker for monorepos
MAX_URLS_PER_REPO = 1000  # circuit-breaker for huge docs

# --- Liveness (Stage 2) ---
LIVENESS_WORKER_COUNT = 20
URL_CACHE_TTL_HOURS = 24  # re-check URLs older than this

# --- Investigation (Stage 3) ---
INVESTIGATION_WORKER_COUNT = 8
INVESTIGATE_TIMEOUT_S = 30

# --- Scoring (Stage 4) ---
SURFACE_CONFIDENCE_THRESHOLD = 0.7
TOP_N_PER_REPO = 3
TIER1_ONLY_MODE = True  # bulk run mode — tier-2 candidates stored but never surfaced

# --- Quality stop-loss ---
QUALITY_SAMPLE_AFTER_N_CANDIDATES = 100
QUALITY_MEDIAN_THRESHOLD = 0.7  # abort if first-100 median confidence drops below this

# --- Safety caps ---
RAM_WARN_MB = 1024
RAM_ABORT_MB = 2048
DISK_REFUSE_GB = 4.5  # refuse new writes if data dir exceeds this
HEARTBEAT_INTERVAL_S = 300  # 5 min
BATCH_SIZE = 100  # checkpoint frequency
REPO_ERROR_BACKOFF_S = 60  # after 3 consecutive errors
RATE_LIMIT_BACKOFF_MAX_S = 900  # 15 min cap

# --- Files ---
HEARTBEAT_FILE = "data/bulk-scan-heartbeat.txt"
SAMPLE_FILE = "data/bulk-scan-sample.md"
REPORT_FILE = "data/bulk-scan-report.md"
ABORT_FILE = "data/bulk-scan-abort"  # touch this to gracefully stop
