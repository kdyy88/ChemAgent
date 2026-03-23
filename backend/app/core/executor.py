"""
Global bounded thread-pool executor for I/O-bound work.

A single process-wide pool replaces the previous pattern of creating a new
``ThreadPoolExecutor(max_workers=len(phase2_items))`` per agent turn, which
allowed unbounded thread growth under high concurrency.

max_workers=16 rationale:
  - RDKit / Babel C++ code releases the GIL during computation, so threads
    give true parallelism without ProcessPoolExecutor's per-process overhead.
  - 16 threads can saturate 4 CPU cores with 4× over-subscription, which is
    appropriate for mixed I/O-wait (PubChem, Serper) + CPU (rdkit, babel) work.
  - Thread stack size is ~8 MB each → 16 threads ≈ 128 MB static overhead.
"""

from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor

IO_POOL = ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="chem-io",
)

# Ensure the pool is cleanly shut down when the process exits.
atexit.register(IO_POOL.shutdown, wait=False)
