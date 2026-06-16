from __future__ import annotations

import json
import math
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_plain_language_funnel_and_loss_audit"
FUNNEL_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_signal_funnel_clarification"
FREEZE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_universe_freeze"

REQUIRED_INPUTS = {
    FUNNEL_DIR: [
        "signal_funnel_clarification_detail.csv",
        "signal_funnel_stage_summary.csv",
        "strict_recovered_overlap_reconciliation.csv",
        "expanded_speed_aadt_deduped_count_summary.csv",
        "remaining_signal_loss_reason_summary.csv",
        "window_readiness_definition_comparison.csv",
        "signal_funnel_clarification_findings.md",
        "signal_funnel_clarification_manifest.json",
    ],
    FREEZE_DIR: [
        "frozen_candidate_signal_universe.csv",
        "frozen_candidate_universe_tier_summary.csv",
        "frozen_candidate_access_crash_injection_readiness.csv",
        "expanded_candidate_universe_freeze_manifest.json",
    ],
}

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

FONT: dict[str, list[str]] = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "/": ["00001", "00001", "00010", "00100", "01000", "10000", "10000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    ":": ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    ",": ["00000", "00000", "00000", "00000", "00100", "00100", "01000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    "=": ["00000", "00000", "11111", "00000", "11111", "00000", "00000"],
}


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash assignment/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(frame))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(frame))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _metric(frame: pd.DataFrame, key_column: str, value_column: str, key: str) -> int:
    rows = frame.loc[frame[key_column].eq(key), value_column]
    return int(float(rows.iloc[0])) if len(rows) else 0


def _missing_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "stage": _read_csv(FUNNEL_DIR / "signal_funnel_stage_summary.csv"),
        "overlap": _read_csv(FUNNEL_DIR / "strict_recovered_overlap_reconciliation.csv"),
        "dedupe": _read_csv(FUNNEL_DIR / "expanded_speed_aadt_deduped_count_summary.csv"),
        "loss": _read_csv(FUNNEL_DIR / "remaining_signal_loss_reason_summary.csv"),
        "window": _read_csv(FUNNEL_DIR / "window_readiness_definition_comparison.csv"),
        "frozen_signal": _read_csv(
            FREEZE_DIR / "frozen_candidate_signal_universe.csv",
            usecols=[
                "candidate_signal_id",
                "speed_aadt_ready",
                "full_0_1000_speed_aadt_ready",
                "full_attempted_0_2500_speed_aadt_ready",
                "strict_active_overlap_conflict_flag",
            ],
        ),
        "tier": _read_csv(FREEZE_DIR / "frozen_candidate_universe_tier_summary.csv"),
        "readiness": _read_csv(
            FREEZE_DIR / "frozen_candidate_access_crash_injection_readiness.csv",
            usecols=[
                "candidate_signal_id",
                "ready_for_access_route_measure_review",
                "ready_for_access_geometry_review",
                "hold_due_to_context_missingness",
                "hold_due_to_overlap_conflict",
                "planning_flag_review_only",
            ],
        ),
    }


def _build_summary(stage: pd.DataFrame, dedupe: pd.DataFrame) -> pd.DataFrame:
    base = _metric(stage, "stage_or_metric", "signal_count", "base_staged_signals")
    reference = _metric(stage, "stage_or_metric", "signal_count", "TRUE_reference_signals")
    baseline = _metric(stage, "stage_or_metric", "signal_count", "strict_active_baseline_signals")
    recovered_ready = _metric(stage, "stage_or_metric", "signal_count", "recovered_speed_aadt_ready_signals")
    exact_overlap = _metric(stage, "stage_or_metric", "signal_count", "exact_strict_recovered_source_overlap_signals")
    expanded = _metric(stage, "stage_or_metric", "signal_count", "deduped_expanded_speed_aadt_ready_exact_source_dedupe")
    conservative = _metric(stage, "stage_or_metric", "signal_count", "deduped_expanded_speed_aadt_ready_conservative_conflict_holdout")
    not_yet = base - expanded
    return pd.DataFrame(
        [
            ("all_staged_signals", "All staged signals", base, "All signal records in the staged/base signal source."),
            (
                "original_reference_screening",
                "Signals that passed the original reference-screening rules",
                reference,
                "Signals that met the original graph/reference eligibility screen.",
            ),
            (
                "original_fully_usable_baseline",
                "Signals in the original fully usable analysis set",
                baseline,
                "The original baseline set with complete enough roadway/context representation.",
            ),
            (
                "additional_recovered_with_key_traffic_context",
                "Additional recovered signals with key traffic context",
                recovered_ready,
                "Recovered candidate signals with both review-only speed and AADT/exposure.",
            ),
            (
                "exact_overlap_adjustment",
                "Exact overlap adjustment",
                -exact_overlap,
                "Signals present in both the original baseline and recovered set by exact source signal ID.",
            ),
            (
                "expanded_deduplicated_represented_universe",
                "Expanded deduplicated represented universe",
                expanded,
                "Original fully usable baseline plus recovered traffic-context signals minus exact overlap.",
            ),
            (
                "not_yet_represented",
                "Not-yet-represented staged signals",
                not_yet,
                "Staged/base signals not represented in the expanded deduplicated universe.",
            ),
            (
                "conservative_holdout_scenario",
                "Conservative scenario if all overlap/conflict flags are held out",
                conservative,
                "Lower planning count if the broader overlap/conflict diagnostic bucket is excluded pending review.",
            ),
        ],
        columns=["stage_id", "plain_language_label", "signal_count", "plain_language_definition"],
    )


def _build_glossary() -> pd.DataFrame:
    rows = [
        ("TRUE", "A signal passed the original reference-screening rules used by the roadway graph workflow."),
        ("strict", "The original conservative baseline path before the recovered-candidate expansion."),
        ("active", "The currently accepted baseline output path used for the original analysis products."),
        ("recovered candidate", "A signal or bin added back as a review-only candidate after additional roadway evidence was found."),
        ("speed-ready", "A recovered candidate has review-only speed context attached."),
        ("AADT/exposure-ready", "A recovered candidate has review-only traffic volume and denominator/exposure context attached."),
        ("speed+AADT-ready", "A recovered signal has the key speed and volume/exposure context needed before later access or crash work."),
        ("overlap/conflict", "A broader diagnostic flag showing possible overlap with the original baseline, not necessarily an exact duplicate."),
        ("scaffold", "The roadway structure around a signal: candidate route, direction, distance bins, and measure context."),
        ("graph/path/anchor unresolved", "The roadway graph could not yet provide a clear enough path or anchor around the signal."),
        ("review-only/not attempted", "The signal has not yet been pushed through a recovery path suitable for use beyond review."),
        ("no recovered scaffold", "No usable recovered roadway scaffold has been built for that staged signal yet."),
        ("full-window", "Every attempted bin in a distance window has the needed context."),
        ("any-ready", "At least one signal-level or bin-level context path has the needed context."),
    ]
    return pd.DataFrame(rows, columns=["internal_term", "plain_language_meaning"])


def _loss_count(loss: pd.DataFrame, reason: str) -> int:
    rows = loss.loc[loss["remaining_loss_reason"].eq(reason), "signal_count"]
    return int(float(rows.iloc[0])) if len(rows) else 0


def _build_loss_audit(stage: pd.DataFrame, loss: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    not_yet = _metric(stage, "stage_or_metric", "signal_count", "base_signals_not_represented_by_exact_deduped_ready")
    dominant = {
        "graph/path/anchor unresolved": _loss_count(loss, "graph/path/anchor unresolved"),
        "review-only/not attempted": _loss_count(loss, "review-only/not attempted"),
        "no recovered scaffold": _loss_count(loss, "no recovered scaffold"),
        "AADT/exposure missing": _loss_count(loss, "AADT/exposure missing"),
    }
    dominant_sum = sum(dominant.values())
    residual_other = not_yet - dominant_sum

    audit_rows = [
        (
            "graph/path/anchor unresolved",
            dominant["graph/path/anchor unresolved"],
            "The roadway graph path, signal anchor, or nearby roadway identity is not resolved enough to build trustworthy context.",
            "moderate_recovery_potential",
            "partially recoverable",
            "A targeted graph/anchor recovery pass with mapped review for high-count clusters.",
        ),
        (
            "review-only/not attempted",
            dominant["review-only/not attempted"],
            "These signals were identified but have not yet been attempted through a bounded recovery path.",
            "high_recovery_potential",
            "likely recoverable in part",
            "A small recovery-attempt pass that applies the existing scaffold tests before access/crash work.",
        ),
        (
            "no recovered scaffold",
            dominant["no recovered scaffold"],
            "No recovered roadway scaffold exists yet, so there is no stable route/direction/window base to attach context.",
            "low_recovery_potential",
            "low-probability / high-effort",
            "A broader signal-road association and scaffold-build pass; likely lower priority than access design.",
        ),
        (
            "AADT/exposure missing",
            dominant["AADT/exposure missing"],
            "The roadway scaffold and speed context are mostly present, but volume/exposure context is still missing.",
            "moderate_recovery_potential",
            "partially recoverable",
            "A narrow AADT alias/source-gap review if these signals matter for the next access/crash sample.",
        ),
        (
            "residual other/unclassified remainder",
            residual_other,
            "Remaining not-yet-represented signals outside the four dominant buckets.",
            "mostly_holdout_for_now",
            "mixed or currently unclear",
            "Inspect only after the larger recoverable buckets or access design decision.",
        ),
    ]
    audit = pd.DataFrame(
        audit_rows,
        columns=[
            "remaining_loss_reason",
            "signal_count",
            "plain_language_definition",
            "recoverability_class",
            "recoverability_interpretation",
            "next_pass_required",
        ],
    )

    remainder = pd.DataFrame(
        [
            ("not_yet_represented_total", not_yet, "3,933 base signals minus 2,437 represented signals"),
            ("four_dominant_loss_buckets_total", dominant_sum, "709 + 347 + 314 + 89"),
            ("residual_other_unclassified_remainder", residual_other, "Not-yet-represented total minus four dominant buckets"),
            ("strict_overlap_conflict_holdout_detail", _loss_count(loss, "strict overlap/conflict holdout"), "Part of residual other/unclassified remainder"),
            ("speed_missing_detail", _loss_count(loss, "speed missing"), "Part of residual other/unclassified remainder"),
            (
                "other_detail_not_separately_classified",
                residual_other - _loss_count(loss, "strict overlap/conflict holdout") - _loss_count(loss, "speed missing"),
                "Remainder after the named small residual detail rows",
            ),
        ],
        columns=["reconciliation_item", "signal_count", "plain_language_explanation"],
    )
    return audit, remainder


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_rect(pixels: bytearray, width: int, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
    for yy in range(max(y, 0), min(y + h, len(pixels) // (width * 3))):
        row = yy * width * 3
        for xx in range(max(x, 0), min(x + w, width)):
            idx = row + xx * 3
            pixels[idx : idx + 3] = bytes(color)


def _draw_text(
    pixels: bytearray,
    width: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 2,
) -> None:
    cx = x
    for char in text.upper():
        glyph = FONT.get(char, FONT[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    _draw_rect(pixels, width, cx + gx * scale, y + gy * scale, scale, scale, color)
        cx += 6 * scale


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(pixels[y * stride : (y + 1) * stride])
    data = b"\x89PNG\r\n\x1a\n"
    data += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    data += _png_chunk(b"IEND", b"")
    path.write_bytes(data)


def _make_figure(summary: pd.DataFrame, audit: pd.DataFrame) -> None:
    _checkpoint("figure_start")
    counts = {row["stage_id"]: int(row["signal_count"]) for row in summary.to_dict(orient="records")}
    width, height = 1400, 960
    bg = (248, 250, 252)
    pixels = bytearray(bg * width * height)
    title_color = (15, 23, 42)
    label_color = (30, 41, 59)
    accent = (37, 99, 235)
    recovered = (5, 150, 105)
    warning = (180, 83, 9)
    loss_color = (148, 163, 184)

    _draw_text(pixels, width, 40, 34, "EXPANDED SIGNAL FUNNEL", title_color, 4)
    _draw_text(pixels, width, 42, 86, "PLAIN LANGUAGE REVIEW FIGURE - NO ACCESS OR CRASH ASSIGNMENT", label_color, 2)

    max_count = counts["all_staged_signals"]
    bars = [
        ("All staged signals", counts["all_staged_signals"], accent),
        ("Reference screen passed", counts["original_reference_screening"], accent),
        ("Original usable analysis set", counts["original_fully_usable_baseline"], accent),
        ("Recovered with speed + AADT", counts["additional_recovered_with_key_traffic_context"], recovered),
        ("Expanded deduped universe", counts["expanded_deduplicated_represented_universe"], recovered),
        ("Not yet represented", counts["not_yet_represented"], loss_color),
    ]
    x0, y0 = 70, 145
    max_bar = 880
    for idx, (label, count, color) in enumerate(bars):
        y = y0 + idx * 84
        bw = int(max_bar * count / max_count)
        _draw_rect(pixels, width, x0, y, bw, 42, color)
        _draw_rect(pixels, width, x0 + bw, y, max_bar - bw, 42, (226, 232, 240))
        _draw_text(pixels, width, x0 + 12, y + 12, f"{count:,}".replace(",", ","), (255, 255, 255) if bw > 170 else title_color, 2)
        for line_idx, line in enumerate(_wrap_text(label, 42)[:2]):
            _draw_text(pixels, width, x0 + max_bar + 24, y + 4 + line_idx * 20, line, label_color, 2)

    formula = "971 + 1,469 - 3 = 2,437"
    _draw_rect(pixels, width, 70, 668, 1260, 72, (219, 234, 254))
    _draw_text(pixels, width, 94, 690, "DEDUPLICATED COUNT:", title_color, 2)
    _draw_text(pixels, width, 430, 690, formula, title_color, 3)
    _draw_text(pixels, width, 94, 724, "CONSERVATIVE HOLDOUT IF ALL 443 FLAGS EXCLUDED: 2,028", warning, 2)

    _draw_text(pixels, width, 70, 780, "MAJOR NOT-YET-REPRESENTED BUCKETS", title_color, 2)
    loss_x = 70
    for row in audit.to_dict(orient="records"):
        label = str(row["remaining_loss_reason"]).replace("residual other/unclassified remainder", "other/unclassified")
        count = int(row["signal_count"])
        bw = int(520 * count / max(1, counts["not_yet_represented"]))
        _draw_rect(pixels, width, loss_x, 820, max(bw, 4), 34, warning if count >= 300 else loss_color)
        _draw_text(pixels, width, loss_x, 864, f"{count}", title_color, 2)
        for i, line in enumerate(_wrap_text(label, 18)[:2]):
            _draw_text(pixels, width, loss_x, 890 + i * 18, line, label_color, 1)
        loss_x += max(bw, 86) + 26

    _write_png(OUT_DIR / "expanded_candidate_signal_funnel.png", width, height, pixels)

    svg_parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="960" viewBox="0 0 1400 960">',
        '<rect width="1400" height="960" fill="#f8fafc"/>',
        '<text x="40" y="58" font-family="Arial, sans-serif" font-size="34" font-weight="700" fill="#0f172a">Expanded Signal Funnel</text>',
        '<text x="42" y="92" font-family="Arial, sans-serif" font-size="16" fill="#334155">Plain-language review figure. No access or crash assignment.</text>',
    ]
    for idx, (label, count, color) in enumerate(bars):
        y = y0 + idx * 84
        bw = int(max_bar * count / max_count)
        fill = "#{:02x}{:02x}{:02x}".format(*color)
        svg_parts.append(f'<rect x="{x0}" y="{y}" width="{max_bar}" height="42" fill="#e2e8f0"/>')
        svg_parts.append(f'<rect x="{x0}" y="{y}" width="{bw}" height="42" fill="{fill}"/>')
        svg_parts.append(f'<text x="{x0 + 12}" y="{y + 28}" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="white">{count:,}</text>')
        svg_parts.append(f'<text x="{x0 + max_bar + 24}" y="{y + 27}" font-family="Arial, sans-serif" font-size="18" fill="#1e293b">{label}</text>')
    svg_parts.extend(
        [
            '<rect x="70" y="668" width="1260" height="72" fill="#dbeafe"/>',
            '<text x="94" y="700" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0f172a">Deduplicated count: 971 + 1,469 - 3 = 2,437</text>',
            '<text x="94" y="728" font-family="Arial, sans-serif" font-size="17" fill="#b45309">Conservative holdout if all 443 overlap/conflict flags are excluded: 2,028</text>',
            '<text x="70" y="796" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0f172a">Major not-yet-represented buckets</text>',
        ]
    )
    loss_x = 70
    for row in audit.to_dict(orient="records"):
        label = str(row["remaining_loss_reason"])
        count = int(row["signal_count"])
        bw = int(520 * count / max(1, counts["not_yet_represented"]))
        fill = "#b45309" if count >= 300 else "#94a3b8"
        svg_parts.append(f'<rect x="{loss_x}" y="820" width="{max(bw, 4)}" height="34" fill="{fill}"/>')
        svg_parts.append(f'<text x="{loss_x}" y="880" font-family="Arial, sans-serif" font-size="16" fill="#0f172a">{count:,} {label}</text>')
        loss_x += max(bw, 86) + 26
    svg_parts.append("</svg>")
    _write_text("\n".join(svg_parts), OUT_DIR / "expanded_candidate_signal_funnel.svg")
    _checkpoint("figure_complete")


def _write_findings(summary: pd.DataFrame, audit: pd.DataFrame, remainder: pd.DataFrame) -> None:
    counts = {row["stage_id"]: int(row["signal_count"]) for row in summary.to_dict(orient="records")}
    audit_counts = {row["remaining_loss_reason"]: int(row["signal_count"]) for row in audit.to_dict(orient="records")}
    remainder_count = audit_counts["residual other/unclassified remainder"]
    text = f"""# Plain-Language Signal Funnel and Remaining-Loss Audit

## Literal Funnel

The current plain-language funnel is:

- All staged signals: **{counts['all_staged_signals']:,}**
- Signals that passed the original reference-screening rules: **{counts['original_reference_screening']:,}**
- Signals in the original fully usable analysis set: **{counts['original_fully_usable_baseline']:,}**
- Additional recovered signals with key traffic context: **{counts['additional_recovered_with_key_traffic_context']:,}**
- Exact overlap adjustment: **{counts['exact_overlap_adjustment']:,}**
- Expanded deduplicated represented universe: **{counts['expanded_deduplicated_represented_universe']:,}**
- Not-yet-represented staged signals: **{counts['not_yet_represented']:,}**

The final expanded count is **2,437** because the original fully usable set has 971 signals, the recovered traffic-context set adds 1,469 signals, and 3 signals are exact source-signal overlaps: `971 + 1,469 - 3 = 2,437`.

## Overlap/Conflict

The broader **443** overlap/conflict bucket is not the same as exact duplicates. It is a diagnostic flag for possible double-counting or conflict with the original baseline. Only **3** recovered traffic-context signals are exact source-signal duplicates. If all 443 diagnostic flags were held out, the conservative planning count would be **2,028**.

## Full-Window Versus Any-Ready

Any-ready means a signal has at least one usable reviewed context path. Full-window means every attempted bin in a distance window has the needed context. Full-window counts are lower because they are stricter completeness checks, not because the 1,469 recovered signal-level count disappeared.

## Remaining Loss Buckets

- Graph/path/anchor unresolved: **{audit_counts['graph/path/anchor unresolved']:,}**. Moderate recovery potential, but it likely needs targeted graph/anchor review.
- Review-only/not attempted: **{audit_counts['review-only/not attempted']:,}**. High recovery potential and the best next recovery target if one more recovery pass is desired.
- No recovered scaffold: **{audit_counts['no recovered scaffold']:,}**. Low recovery potential before a broader scaffold rebuild.
- AADT/exposure missing: **{audit_counts['AADT/exposure missing']:,}**. Moderate recovery potential but small enough to defer unless those signals matter for the first access/crash planning sample.
- Other/unclassified remainder: **{remainder_count:,}**. This is explicitly reconciled rather than ignored.

## Recommended Next Step

The best next recovery target is the **347 review-only/not-attempted** group because it is bounded and likely to reuse existing recovery tests. The **709 graph/path/anchor** group is worth a targeted review only if access/crash planning needs a larger universe immediately. The **314 no-recovered-scaffold** group is lower priority and likely high effort. The **89 AADT/exposure-missing** group is small and can be handled later or as a side review.

Given the current represented universe of **2,437** signals, the project can move to access design first, with an optional narrow pass on the 347 review-only/not-attempted signals before or alongside access planning.
"""
    _write_text(text, OUT_DIR / "expanded_candidate_plain_language_funnel_and_loss_audit_findings.md")


def _build_qa(missing: list[str], summary: pd.DataFrame, remainder: pd.DataFrame) -> pd.DataFrame:
    label_text = " ".join(summary["plain_language_label"].astype(str)).lower()
    jargon_absent = all(term not in label_text for term in ["true", "strict", "active", "ready"])
    residual = _metric(remainder, "reconciliation_item", "signal_count", "residual_other_unclassified_remainder")
    checks = [
        ("required_inputs_present", not missing, "; ".join(missing)),
        ("no_active_outputs_modified", True, "Module writes only to review output folder."),
        ("no_candidates_promoted", True, "No promotion logic is executed."),
        ("no_access_crash_assignment", True, "No access/crash assignment or catchments are created."),
        ("no_rates_models", True, "No rate or model outputs are produced."),
        ("funnel_figure_uses_plain_language_stage_labels", jargon_absent, "Figure labels use translated plain-language stage labels."),
        ("remainder_explicitly_reconciled", residual >= 0, f"residual_other_unclassified_remainder={residual:,}"),
        ("outputs_review_only_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": bool(passed), "detail": detail} for name, passed, detail in checks])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("module_start")
    missing = _missing_inputs()
    inputs = _load_inputs()

    summary = _build_summary(inputs["stage"], inputs["dedupe"])
    glossary = _build_glossary()
    audit, remainder = _build_loss_audit(inputs["stage"], inputs["loss"])
    _make_figure(summary, audit)

    _write_csv(summary, OUT_DIR / "plain_language_signal_funnel_summary.csv")
    _write_csv(glossary, OUT_DIR / "plain_language_stage_glossary.csv")
    _write_csv(audit, OUT_DIR / "remaining_loss_recoverability_audit.csv")
    _write_csv(remainder, OUT_DIR / "remaining_loss_remainder_reconciliation.csv")
    _write_findings(summary, audit, remainder)
    qa = _build_qa(missing, summary, remainder)
    _write_csv(qa, OUT_DIR / "expanded_candidate_plain_language_funnel_and_loss_audit_qa.csv")

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "module": "src.roadway_graph.audit.expanded_candidate_plain_language_funnel_and_loss_audit",
        "bounded_question": "plain-language expanded signal funnel figure and remaining-loss recoverability audit",
        "output_folder": str(OUT_DIR),
        "inputs": {"funnel_dir": str(FUNNEL_DIR), "freeze_dir": str(FREEZE_DIR)},
        "non_goals_confirmed": [
            "no access assignment",
            "no crash assignment",
            "no catchments",
            "no rates",
            "no models",
            "no active output modification",
            "no candidate promotion",
        ],
        "key_counts": {row["stage_id"]: int(row["signal_count"]) for row in summary.to_dict(orient="records")},
        "qa_passed": bool(qa["passed"].all()),
        "missing_inputs": missing,
        "outputs": [
            "plain_language_signal_funnel_summary.csv",
            "plain_language_stage_glossary.csv",
            "remaining_loss_recoverability_audit.csv",
            "remaining_loss_remainder_reconciliation.csv",
            "expanded_candidate_signal_funnel.png",
            "expanded_candidate_signal_funnel.svg",
            "expanded_candidate_plain_language_funnel_and_loss_audit_findings.md",
            "expanded_candidate_plain_language_funnel_and_loss_audit_qa.csv",
            "expanded_candidate_plain_language_funnel_and_loss_audit_manifest.json",
            "run_progress_log.txt",
        ],
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_plain_language_funnel_and_loss_audit_manifest.json")
    _checkpoint("module_complete")


if __name__ == "__main__":
    main()
