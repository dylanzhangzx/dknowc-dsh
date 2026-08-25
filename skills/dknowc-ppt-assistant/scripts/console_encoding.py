#!/usr/bin/env python3
"""Console encoding helpers for dknowc PPT assistant CLI scripts.

Adapted from ppt-master (MIT, Copyright (c) 2025-2026 Hugo He):
UTF-8 stdio configuration only. The upstream official-distribution identity
gates are intentionally removed for this extracted subset; MIT attribution is
preserved in THIRD_PARTY_NOTICES.md at the skill root.
"""

from __future__ import annotations

import io
import sys
from typing import TextIO


def _reconfigure_stream(stream: TextIO) -> TextIO:
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
        return stream
    except AttributeError:
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            return stream
        return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return stream


def configure_utf8_stdio() -> None:
    """Configure CLI streams to UTF-8 for reliable CJK output on all platforms."""
    sys.stdout = _reconfigure_stream(sys.stdout)
    sys.stderr = _reconfigure_stream(sys.stderr)
