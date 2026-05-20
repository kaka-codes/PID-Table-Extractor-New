
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import fitz
import numpy as np

from processing.adjacent_table_extractor import (
    extract_raw_tables_for_adjacent_lookup,
    extract_required_data_from_next_source_table,
)

DEFAULT_RENDER_SCALE = 3
DEFAULT_CLIP_WIDTH = 1000
DEFAULT_CLIP_HEIGHT = 400
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

# ============================================
# STREAMLIT CLOUD STABILITY SETTINGS
# ============================================

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

# ============================================
# IMAGE HELPERS
# ============================================

def _pixmap_to_bgr(pixmap):
    image = np.frombuffer(
        pixmap.samples,
        dtype=np.uint8
    ).reshape(
        pixmap.height,
        pixmap.width,
        pixmap.n
    )

    if pixmap.n == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)

    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def _render_pdf_region(pdf_bytes: bytes, page_index: int, rect, scale: int):
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = document[page_index]

    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        clip=rect
    )

    return _pixmap_to_bgr(pixmap)

# ============================================
# TABLE LINE DETECTION
# ============================================

def _merge_line_segments(segments, position_tol=6, gap_tol=12):
    merged = []

    for segment in sorted(
        segments,
        key=lambda item: (item["pos"], item["start"], item["end"])
    ):
        if not merged:
            merged.append(segment.copy())
            continue

        previous = merged[-1]

        same_track = abs(segment["pos"] - previous["pos"]) <= position_tol
        touching = segment["start"] <= previous["end"] + gap_tol

        if same_track and touching:
            previous["start"] = min(previous["start"], segment["start"])
            previous["end"] = max(previous["end"], segment["end"])
            previous["pos"] = (previous["pos"] + segment["pos"]) / 2
        else:
            merged.append(segment.copy())

    for segment in merged:
        segment["pos"] = int(round(segment["pos"]))
        segment["start"] = int(round(segment["start"]))
        segment["end"] = int(round(segment["end"]))
        segment["length"] = segment["end"] - segment["start"]

    return merged


def _extract_line_segments(mask, orientation, min_length):
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    segments = []

    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)

        if orientation == "horizontal" and width >= min_length:
            segments.append({
                "pos": y + (height / 2),
                "start": x,
                "end": x + width,
            })

        elif orientation == "vertical" and height >= min_length:
            segments.append({
                "pos": x + (width / 2),
                "start": y,
                "end": y + height,
            })

    return _merge_line_segments(segments)


def _detect_table_lines(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    _, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(image.shape[1] // 30, 40), 1)
    )

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, max(image.shape[0] // 18, 40))
    )

    horizontal_mask = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        horizontal_kernel
    )

    vertical_mask = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        vertical_kernel
    )

    horizontal_lines = _extract_line_segments(
        horizontal_mask,
        "horizontal",
        min_length=max(image.shape[1] // 5, 120)
    )

    vertical_lines = _extract_line_segments(
        vertical_mask,
        "vertical",
        min_length=max(image.shape[0] // 6, 120)
    )

    return horizontal_lines, vertical_lines

# ============================================
# TABLE STRUCTURE
# ============================================

def _overlap_length(start_a, end_a, start_b, end_b):
    return max(
        0,
        min(end_a, end_b) - max(start_a, start_b)
    )


def _find_table_structure(horizontal_lines, vertical_lines, image_shape):
    image_height, image_width = image_shape[:2]

    long_verticals = [
        line for line in vertical_lines
        if line["length"] >= int(image_height * 0.5)
    ]

    if len(long_verticals) < 2:
        raise RuntimeError("Could not detect enough vertical table lines.")

    best_candidate = None

    sorted_verticals = sorted(
        long_verticals,
        key=lambda item: item["pos"]
    )

    for index, left_line in enumerate(sorted_verticals):

        for right_line in sorted_verticals[index + 1:]:

            table_width = right_line["pos"] - left_line["pos"]

            overlap_top = max(
                left_line["start"],
                right_line["start"]
            )

            overlap_bottom = min(
                left_line["end"],
                right_line["end"]
            )

            if table_width < image_width * 0.15:
                continue

            spanning_horizontals = [
                line
                for line in horizontal_lines
                if line["start"] <= left_line["pos"] + 12
                and line["end"] >= right_line["pos"] - 12
                and overlap_top - 8 <= line["pos"] <= overlap_bottom + 8
            ]

            if len(spanning_horizontals) < 4:
                continue

            score = len(spanning_horizontals) * table_width

            if not best_candidate or score > best_candidate["score"]:
                best_candidate = {
                    "score": score,
                    "left": left_line["pos"],
                    "right": right_line["pos"],
                    "top": min(line["pos"] for line in spanning_horizontals),
                    "bottom": max(line["pos"] for line in spanning_horizontals),
                }

    if not best_candidate:
        raise RuntimeError("Could not isolate the main table.")

    table_left = best_candidate["left"]
    table_right = best_candidate["right"]
    table_top = best_candidate["top"]
    table_bottom = best_candidate["bottom"]

    table_width = table_right - table_left
    table_height = table_bottom - table_top
    
    table_horizontals = [
        line
        for line in horizontal_lines
        if table_top - 8 <= line["pos"] <= table_bottom + 8
        and _overlap_length(
            line["start"],
            line["end"],
            table_left,
            table_right
        ) >= table_width * 0.2
    ]
    
    table_verticals = [
        line
        for line in vertical_lines
        if table_left - 8 <= line["pos"] <= table_right + 8
        and _overlap_length(
            line["start"],
            line["end"],
            table_top,
            table_bottom
        ) >= table_height * 0.2
    ]
    
    return {
        "bbox": {
            "x0": int(table_left),
            "y0": int(table_top),
            "x1": int(table_right),
            "y1": int(table_bottom),
        },
    
        "horizontal_lines": [
            {
                "y": line["pos"],
                "x0": line["start"],
                "x1": line["end"]
            }
            for line in sorted(
                table_horizontals,
                key=lambda item: (
                    item["pos"],
                    item["start"]
                )
            )
        ],
    
        "vertical_lines": [
            {
                "x": line["pos"],
                "y0": line["start"],
                "y1": line["end"]
            }
            for line in sorted(
                table_verticals,
                key=lambda item: (
                    item["pos"],
                    item["start"]
                )
            )
        ],
    }

# ============================================
# EASYOCR
# ============================================

@lru_cache(maxsize=1)
def _get_ocr_engine():
    try:
        import easyocr
    except ImportError as exc:
        raise ImportError(
            "The 'easyocr' package is not installed in the current Python environment. "
            f"Current Python: {sys.executable}."
        ) from exc

    return easyocr.Reader(
        ['en'],
        gpu=False,
        verbose=False
    )


@lru_cache(maxsize=1)
def _get_bundled_ocr_python() -> Optional[Path]:
    bundled_python = Path(__file__).resolve().parents[1] / "venv" / "Scripts" / "python.exe"
    if bundled_python.exists():
        return bundled_python
    return None


def _extract_ocr_items_with_bundled_python(image):
    bundled_python = _get_bundled_ocr_python()
    if bundled_python is None:
        raise ImportError(
            "The 'easyocr' package is not installed in the current Python environment, "
            "and no bundled OCR Python executable was found."
        )

    worker_script = Path(__file__).resolve().with_name("easyocr_worker.py")
    success, encoded_image = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("Could not encode the page image for OCR fallback.")

    temp_image_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_image:
            temp_image.write(encoded_image.tobytes())
            temp_image_path = Path(temp_image.name)

        completed = subprocess.run(
            [str(bundled_python), str(worker_script), str(temp_image_path)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

        if completed.returncode != 0:
            stderr_text = (completed.stderr or "").strip()
            raise RuntimeError(
                "Bundled OCR fallback failed."
                + (f" {stderr_text}" if stderr_text else "")
            )

        try:
            return json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Bundled OCR fallback returned invalid JSON.") from exc
    finally:
        if temp_image_path is not None and temp_image_path.exists():
            temp_image_path.unlink()


def _extract_ocr_items(image):
    try:
        ocr = _get_ocr_engine()
    except ImportError:
        return _extract_ocr_items_with_bundled_python(image)
    
    results = ocr.readtext(
        image,
        detail=1,
        paragraph=False,
        batch_size=1,
    )
    
    items = []
    
    for result in results:
    
        try:
            box, text, confidence = result
        except Exception:
            continue
    
        if text is None:
            continue
    
        text = str(text).strip()
    
        if not text:
            continue
    
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0.0
    
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
    
        items.append(
            {
                "text": text,
    
                "confidence": round(
                    confidence_value,
                    4
                ),
    
                "bbox": [
                    float(min(xs)),
                    float(min(ys)),
                    float(max(xs)),
                    float(max(ys)),
                ],
    
                "center": (
                    float(sum(xs) / len(xs)),
                    float(sum(ys) / len(ys)),
                ),
            }
        )
    
    return items
    
def _is_inside_bbox(point, bbox, pad=2):
    x, y = point
    return (
        bbox["x0"] - pad <= x <= bbox["x1"] + pad
        and bbox["y0"] - pad <= y <= bbox["y1"] + pad
    )


def _line_covers_coordinate(line_start, line_end, coordinate, tolerance=6):
    return line_start - tolerance <= coordinate <= line_end + tolerance


def _find_local_bounds(center_x, center_y, horizontals, verticals):
    left_candidates = [
        line["x"]
        for line in verticals
        if line["x"] <= center_x and _line_covers_coordinate(line["y0"], line["y1"], center_y)
    ]
    right_candidates = [
        line["x"]
        for line in verticals
        if line["x"] >= center_x and _line_covers_coordinate(line["y0"], line["y1"], center_y)
    ]
    top_candidates = [
        line["y"]
        for line in horizontals
        if line["y"] <= center_y and _line_covers_coordinate(line["x0"], line["x1"], center_x)
    ]
    bottom_candidates = [
        line["y"]
        for line in horizontals
        if line["y"] >= center_y and _line_covers_coordinate(line["x0"], line["x1"], center_x)
    ]

    if not (left_candidates and right_candidates and top_candidates and bottom_candidates):
        return None

    left = max(left_candidates)
    right = min(right_candidates)
    top = max(top_candidates)
    bottom = min(bottom_candidates)

    if left >= right or top >= bottom:
        return None

    return (left, top, right, bottom)


def _deduplicate_text(parts):
    seen = set()
    cleaned = []

    for part in parts:
        text = " ".join(str(part).split())

        if not text:
            continue

        token = text.casefold()

        if token in seen:
            continue

        seen.add(token)
        cleaned.append(text)

    return cleaned


def _normalize_lookup_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _extract_lookup_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(text or "")
        if len(token) > 1
    }


def _ocr_rows_to_lookup_text(matched_rows: list[dict[str, Any]]) -> str:
    lines = []

    for row in matched_rows:
        for key, value in row.items():
            lines.append(f"{key}: {value}")

    return "\n".join(lines)


def _score_text_overlap(reference_text: str, candidate_text: str) -> float:
    reference_tokens = _extract_lookup_tokens(reference_text)
    candidate_tokens = _extract_lookup_tokens(candidate_text)

    if not reference_tokens or not candidate_tokens:
        return 0.0

    matched_tokens = reference_tokens & candidate_tokens
    if not matched_tokens:
        return 0.0

    matched_weight = sum(max(len(token) - 1, 1) for token in matched_tokens)
    reference_weight = sum(max(len(token) - 1, 1) for token in reference_tokens)
    return matched_weight / max(reference_weight, 1)


def _bbox_overlap_ratio(bbox_a: dict[str, float], bbox_b: dict[str, float]) -> float:
    overlap_x0 = max(float(bbox_a["x0"]), float(bbox_b["x0"]))
    overlap_top = max(float(bbox_a["top"]), float(bbox_b["top"]))
    overlap_x1 = min(float(bbox_a["x1"]), float(bbox_b["x1"]))
    overlap_bottom = min(float(bbox_a["bottom"]), float(bbox_b["bottom"]))

    overlap_width = max(0.0, overlap_x1 - overlap_x0)
    overlap_height = max(0.0, overlap_bottom - overlap_top)
    overlap_area = overlap_width * overlap_height
    if overlap_area <= 0:
        return 0.0

    area_a = max(0.0, float(bbox_a["x1"]) - float(bbox_a["x0"])) * max(
        0.0, float(bbox_a["bottom"]) - float(bbox_a["top"])
    )
    area_b = max(0.0, float(bbox_b["x1"]) - float(bbox_b["x0"])) * max(
        0.0, float(bbox_b["bottom"]) - float(bbox_b["top"])
    )
    smaller_area = max(min(area_a, area_b), 1.0)
    return overlap_area / smaller_area


def _image_bbox_to_pdf_bbox(image_bbox: dict[str, int], clip_rect) -> dict[str, float]:
    return {
        "x0": float(clip_rect.x0 + (image_bbox["x0"] / DEFAULT_RENDER_SCALE)),
        "top": float(clip_rect.y0 + (image_bbox["y0"] / DEFAULT_RENDER_SCALE)),
        "x1": float(clip_rect.x0 + (image_bbox["x1"] / DEFAULT_RENDER_SCALE)),
        "bottom": float(clip_rect.y0 + (image_bbox["y1"] / DEFAULT_RENDER_SCALE)),
    }


def _match_ocr_result_to_pdfplumber_table(
    raw_tables: list[dict[str, Any]],
    page_number: int,
    ocr_table_bbox: Optional[dict[str, int]],
    clip_rect,
    matched_rows: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    page_tables = [table for table in raw_tables if table["page_number"] == page_number]
    if not page_tables:
        return None

    reference_text = _normalize_lookup_text(_ocr_rows_to_lookup_text(matched_rows))
    reference_bbox = (
        _image_bbox_to_pdf_bbox(ocr_table_bbox, clip_rect) if ocr_table_bbox is not None else None
    )

    best_candidate = None
    best_score = (-1.0, -1.0, -1.0)

    for table in page_tables:
        bbox_score = 0.0
        table_bbox = table.get("bbox")
        if reference_bbox is not None and table_bbox:
            bbox_score = _bbox_overlap_ratio(reference_bbox, table_bbox)

        candidate_text = _normalize_lookup_text(
            "\n".join(
                " | ".join(str(cell).strip() for cell in row)
                for _, row in table["dataframe"].iterrows()
            )
        )
        text_score = _score_text_overlap(reference_text, candidate_text)
        substring_bonus = 1.0 if reference_text and reference_text in candidate_text else 0.0
        score_tuple = (bbox_score, text_score, substring_bonus)

        if score_tuple > best_score:
            best_score = score_tuple
            best_candidate = table

    if best_candidate is None:
        return None

    if best_score[0] <= 0 and best_score[1] <= 0:
        return None

    return {
        "page_number": best_candidate["page_number"],
        "table_number": best_candidate["table_number"],
        "bbox_score": round(best_score[0], 4),
        "text_score": round(best_score[1], 4),
    }


def _build_semantic_rows(table_items, table_cells, key_split_x):
    row_groups = defaultdict(list)

    for item in table_items:
        row_groups[item["row_band"]].append(item)

    structured_rows = []

    for row_band in sorted(row_groups.keys(), key=lambda band: (band[1], band[0])):
        row_top, row_bottom = row_band
        row_height = row_bottom - row_top
        row_center = (row_top + row_bottom) / 2
        row_cells = sorted(
            [
                cell
                for cell in table_cells
                if cell["bbox"][1] == row_top and cell["bbox"][3] == row_bottom
            ],
            key=lambda cell: cell["center"][0],
        )

        direct_key_parts = [
            cell["text"] for cell in row_cells if cell["center"][0] < key_split_x
        ]
        value_parts = [
            cell["text"] for cell in row_cells if cell["center"][0] >= key_split_x
        ]

        inherited_key_parts = [
            cell["text"]
            for cell in table_cells
            if cell["center"][0] < key_split_x
            and cell["bbox"][1] <= row_center <= cell["bbox"][3]
            and (cell["bbox"][3] - cell["bbox"][1]) > row_height + 5
        ]

        key_parts = _deduplicate_text(inherited_key_parts + direct_key_parts)
        value_parts = _deduplicate_text(value_parts)

        if not key_parts or not value_parts:
            continue

        structured_rows.append({" ".join(key_parts): " ".join(value_parts)})

    return structured_rows


def _build_ocr_json(
    source_file: str,
    matched_rows: Optional[List[Dict[str, Any]]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        "source_file": os.path.basename(source_file),
        "matched_rows": matched_rows or [],
    }

    if error is not None:
        payload["error"] = error
    return payload


def _ocr_page_result(pdf_bytes: bytes, filename: str, page_index: int) -> Dict[str, Any]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = document[page_index]
    rect = page.rect
    clip_rect = fitz.Rect(
        0,
        0,
        min(rect.width, DEFAULT_CLIP_WIDTH),
        min(rect.height, DEFAULT_CLIP_HEIGHT),
    )

    image = _render_pdf_region(pdf_bytes, page_index, clip_rect, DEFAULT_RENDER_SCALE)
    horizontal_lines, vertical_lines = _detect_table_lines(image)
    table_structure = _find_table_structure(horizontal_lines, vertical_lines, image.shape)
    ocr_items = _extract_ocr_items(image)

    table_bbox = table_structure["bbox"]
    table_horizontals = table_structure["horizontal_lines"]
    table_verticals = table_structure["vertical_lines"]

    table_items = []
    grouped_cells = defaultdict(list)

    for item in ocr_items:
        if not _is_inside_bbox(item["center"], table_bbox):
            continue

        local_bounds = _find_local_bounds(
            item["center"][0],
            item["center"][1],
            table_horizontals,
            table_verticals,
        )

        if not local_bounds:
            continue

        left, top, right, bottom = local_bounds

        item["cell_bbox"] = [left, top, right, bottom]
        item["row_band"] = (top, bottom)
        table_items.append(item)
        grouped_cells[(left, top, right, bottom)].append(item)

    table_cells = []

    for bbox, items in sorted(grouped_cells.items(), key=lambda entry: (entry[0][1], entry[0][0])):
        ordered_items = sorted(items, key=lambda item: item["center"][0])
        text_parts = [item["text"] for item in ordered_items]

        table_cells.append(
            {
                "bbox": list(bbox),
                "center": [
                    round((bbox[0] + bbox[2]) / 2, 1),
                    round((bbox[1] + bbox[3]) / 2, 1),
                ],
                "text": " ".join(_deduplicate_text(text_parts)),
            }
        )

    major_verticals = sorted(
        [
            line["x"]
            for line in table_verticals
            if (line["y1"] - line["y0"]) >= (table_bbox["y1"] - table_bbox["y0"]) * 0.8
        ]
    )

    if len(major_verticals) >= 3:
        key_split_x = major_verticals[1]
    else:
        key_split_x = table_bbox["x0"] + int((table_bbox["x1"] - table_bbox["x0"]) * 0.35)

    matched_rows = _build_semantic_rows(table_items, table_cells, key_split_x)

    return {
        "page_number": page_index + 1,
        "clip_rect": {
            "x0": float(clip_rect.x0),
            "y0": float(clip_rect.y0),
            "x1": float(clip_rect.x1),
            "y1": float(clip_rect.y1),
        },
        "ocr_table_bbox": dict(table_bbox),
        "ocr_json": _build_ocr_json(
            source_file=filename,
            matched_rows=matched_rows,
        ),
    }


def extract_ocr_document(pdf_bytes: bytes, filename: str) -> Dict[str, Any]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    ocr_results = []

    for page_index in range(len(document)):
        try:
            page_result = _ocr_page_result(pdf_bytes, filename, page_index)
        except Exception as exc:
            page_result = {
                "page_number": page_index + 1,
                "ocr_json": _build_ocr_json(
                    source_file=filename,
                    matched_rows=[],
                    error=str(exc),
                ),
            }

        ocr_results.append(page_result)

    raw_pdfplumber_tables = extract_raw_tables_for_adjacent_lookup(pdf_bytes)

    for page_result in ocr_results:
        ocr_json = page_result.get("ocr_json") or {}
        matched_rows = ocr_json.get("matched_rows", [])
        if not matched_rows:
            continue

        clip_rect_payload = page_result.get("clip_rect") or {}
        clip_rect = fitz.Rect(
            float(clip_rect_payload.get("x0", 0.0)),
            float(clip_rect_payload.get("y0", 0.0)),
            float(clip_rect_payload.get("x1", 0.0)),
            float(clip_rect_payload.get("y1", 0.0)),
        )

        matched_source_table = _match_ocr_result_to_pdfplumber_table(
            raw_tables=raw_pdfplumber_tables,
            page_number=page_result["page_number"],
            ocr_table_bbox=page_result.get("ocr_table_bbox"),
            clip_rect=clip_rect,
            matched_rows=matched_rows,
        )

        if matched_source_table is None:
            ocr_json["source_table_match_status"] = "pdfplumber_table_not_found"
            continue

        ocr_json["page_number"] = page_result["page_number"]
        ocr_json["table_number"] = matched_source_table["table_number"]
        ocr_json["source_table_match_status"] = "matched"
        ocr_json["source_table_match_bbox_score"] = matched_source_table["bbox_score"]
        ocr_json["source_table_match_text_score"] = matched_source_table["text_score"]

        adjacent_table_result = extract_required_data_from_next_source_table(
            pdf_bytes=pdf_bytes,
            source_page_number=page_result["page_number"],
            source_table_number=matched_source_table["table_number"],
        )

        adjacent_table_data = adjacent_table_result.get("data") or {}
        if adjacent_table_data:
            ocr_json.update(adjacent_table_data)

        ocr_json["adjacent_table_extraction_status"] = adjacent_table_result.get(
            "status", "not_run"
        )
        if adjacent_table_result.get("message"):
            ocr_json["adjacent_table_extraction_message"] = adjacent_table_result.get("message")
        if adjacent_table_result.get("adjacent_table_page_number") is not None:
            ocr_json["adjacent_table_page_number"] = adjacent_table_result.get(
                "adjacent_table_page_number"
            )
        if adjacent_table_result.get("adjacent_table_table_number") is not None:
            ocr_json["adjacent_table_table_number"] = adjacent_table_result.get(
                "adjacent_table_table_number"
            )

    chunks = []
    chunk_number = 1

    for page_result in ocr_results:
        ocr_json = page_result["ocr_json"]
        matched_rows = ocr_json.get("matched_rows", [])
        if not matched_rows:
            continue

        chunk_lines = []
        for row in matched_rows:
            for key, value in row.items():
                chunk_lines.append(f"{key}: {value}")

        for field_name in ("revision_number", "document_title", "document_numbers"):
            field_value = ocr_json.get(field_name)
            if isinstance(field_value, list):
                field_value = ", ".join(str(item).strip() for item in field_value if str(item).strip())
            if str(field_value or "").strip():
                chunk_lines.append(f"{field_name}: {field_value}")

        if not chunk_lines:
            continue

        chunks.append(
            {
                "source_file": filename,
                "page_number": page_result["page_number"],
                "table_number": ocr_json.get("table_number", 1),
                "split_number": None,
                "equipment_number": None,
                "context_type": "ocr_rows",
                "text": "\n".join(chunk_lines),
                "chunk_number": chunk_number,
            }
        )
        chunk_number += 1

    return {
        "metadata": {
            "source_file": filename,
            "raw_table_count": len(ocr_results),
            "matched_table_count": len([result for result in ocr_results if result["ocr_json"].get("matched_rows")]),
            "candidate_table_count": len(ocr_results),
            "selected_table_count": 0,
            "chunk_count": len(chunks),
            "equipment_count": 0,
            "extraction_mode": "ocr",
        },
        "extracted_tables": [],
        "tables": [],
        "chunks": chunks,
        "ocr_results": ocr_results,
    }
