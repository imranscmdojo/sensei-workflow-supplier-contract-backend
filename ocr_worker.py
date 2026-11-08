"""Subprocess worker module for OCR of scanned PDF pages.

Kept OUT of main.py on purpose: under the "spawn" start method each
ProcessPoolExecutor worker re-imports the module that owns its task function.
A worker importing the whole FastAPI app (firebase, bigquery, secretmanager,
...) would be slow to start and fragile. This module only pulls in
rapidocr_onnxruntime (+ its numpy/opencv/onnxruntime deps), builds one OCR
engine per worker, and OCRs pages passed in as (page_index, PIL.Image) tuples.
"""

import os
from typing import Any, Tuple

os.environ.setdefault("GLOG_minloglevel", "3")

from rapidocr_onnxruntime import RapidOCR  # noqa: E402

_ENGINE = None


def _ocr_worker_init():
    """One-time per-worker initializer: build the single engine this worker reuses.

    96 DPI renders with a 960px det cap is the measured sweet spot (~2x faster
    than 150 DPI full-res with equal/slightly better text extraction). A pool
    of these single-threaded engines across processes uses every core without
    GIL contention.
    """
    global _ENGINE
    _ENGINE = RapidOCR(
        max_side_len=960,
        intra_op_num_threads=1,
        print_verbose=False,
    )


def _ocr_worker_page(item: Tuple[int, Any]) -> Tuple[int, str]:
    """OCR one rendered page (runs inside an OCR subprocess)."""
    idx, img = item
    if img is None:
        return idx, ""
    try:
        result, _ = _ENGINE(img)
        return idx, "\n".join(line[1] for line in result) if result else ""
    except Exception as exc:  # noqa: BLE001 - never fail the whole upload for one page
        print(f"[ocr] page {idx} failed: {exc}")
        return idx, ""