#!/usr/bin/env python3
"""Compatibility shim — real implementation lives in backend.sample_request.cli."""
from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path so we can import backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.sample_request.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
