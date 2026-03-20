# -*- coding: utf-8 -*-
"""
Logging helpers for thirdstep.
"""

import time
import arcpy


def msg(s: str):
    try:
        arcpy.AddMessage(s)
    except Exception:
        pass
    print(s)


def log_counts(label, fc):
    try:
        n = int(arcpy.management.GetCount(fc)[0])
        msg(f"    -> {label}: {n:,}")
        return n
    except Exception:
        msg(f"    -> {label}: (count unavailable)")
        return None


def log_phase_time(label, start_time):
    elapsed = time.time() - start_time
    msg(f"    -> {label} completed in {elapsed:.2f}s")
    return elapsed
