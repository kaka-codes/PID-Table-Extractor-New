import json
import time
from functools import lru_cache
from typing import Any, Dict, List, Tuple
from urllib import error, request

import pandas as pd

from google_api_key import get_google_api_key

MECHANICAL_TEMPLATE_HEADERS = [
    "REV No.",
    "CONTRACTOR EQUIPMENT TAG NO.",
    "DESCRIPTION",
    "EQUIPMENT TYPE",
    "PRODUCT/ SERVICE",
    "P&ID",
    "MATERIAL OF CONSTRUCTION",
    "CONFIGURATION",
    "ORIENTATION",
    "LOCATION",
    "OPERATING PRESSURE",
    "OPERATING TEMPERATURE",
    "DESIGN PRESSURE",
    "DESIGN TEMPERATURE",
    "DESIGN CAPACITY",
    "DIMENSION",
    "L or T/T",
    "W or ID",
    "H or T/T",
    "DUTY",
    "ABSORBED POWER",
    "DESIGN CODE",
    "DIFFERENTIAL PRESSURE",
    "DRY WT (each)",
    "OPE WT (each)",
    "DRY WT (total)",
    "OPE WT (total)",
    "REMARKS",
]
MECHANICAL_MODEL_CANDIDATES = [
    "gemini-3.1-flash-lite",
]

DEFAULT_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _extract_response_text(response_payload: Dict[str, Any]) -> str:
    candidates = response_payload.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text_chunks = [str(part.get("text", "")) for part in parts if part.get("text")]
        if text_chunks:
            return "\n".join(text_chunks).strip()

    prompt_feedback = response_payload.get("promptFeedback") or {}
    block_reason = prompt_feedback.get("blockReason")
    if block_reason:
        raise RuntimeError(f"Gemini blocked the request: {block_reason}")

    raise RuntimeError("Gemini returned no text content.")


def _post_to_gemini(prompt: str, model_name: str) -> str:
    google_api_key = get_google_api_key()
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    body = json.dumps(payload).encode("utf-8")
    endpoint = DEFAULT_GEMINI_API_URL.format(model=model_name)
    http_request = request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": google_api_key,
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw_output = exc.read().decode("utf-8", errors="replace")
        runtime_error = RuntimeError(raw_output or str(exc))
        runtime_error.status_code = exc.code
        runtime_error.raw_output = raw_output
        raise runtime_error from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason or exc)) from exc

    return _extract_response_text(response_payload)


def _should_try_next_model(error_message: str, status_code: Any) -> bool:
    text = str(error_message or "").lower()
    return status_code in {400, 404} or "not found" in text or "unsupported" in text


def _is_high_demand_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    message = str(error).lower()
    return status_code == 503 or (
        "503" in message
        and (
            "high demand" in message
            or "try again later" in message
            or "unavailable" in message
        )
    )


def _call_mechanical_model(prompt: str) -> Tuple[str, str]:
    google_api_key = get_google_api_key()
    if not google_api_key:
        raise ValueError("Set GOOGLE_API_KEY in Streamlit secrets before building the Mechanical Equipment List.")

    last_error = None
    for model_name in MECHANICAL_MODEL_CANDIDATES:
        try:
            return _post_to_gemini(prompt, model_name), model_name
        except Exception as exc:
            last_error = exc
            if not _should_try_next_model(str(exc), getattr(exc, "status_code", None)):
                raise

    if last_error is not None:
        raise last_error

    raise RuntimeError("No Gemini model candidates were available.")


def _build_mechanical_prompt(payload: Dict[str, Any]) -> str:
    headers_json = json.dumps(MECHANICAL_TEMPLATE_HEADERS, ensure_ascii=True)
    payload_json = json.dumps(payload, ensure_ascii=True, indent=2)

    return f"""
You are converting extracted P&ID structured JSON into a Mechanical Equipment List table.

Use these exact output headers in this exact order:
{headers_json}

Input JSON:
{payload_json}

Instructions:
You convert input JSON into a Mechanical Equipment List table.

INPUT TYPES
- If JSON has "equipment": create one output row per equipment item.
- If JSON has "matched_rows": interpret OCR row-wise key/value data and infer equipment row(s).
- For OCR inputs, split into multiple equipment rows only when grouping is clear. Otherwise return the best inferred row(s) and leave uncertain fields blank.

GENERAL RULES
- Map source properties to existing Mechanical Equipment List headers first.
- Correct obvious header spelling mistakes before mapping.
  Examples:
  - "Diffrntial Pressure" → "Differential Pressure"
  - "Dimmension"/"Dimennsion" → "Dimension"
- If a property does not fit any existing header, add a concise business-ready column using only the property name.
- Do not put units in any column header. Append units to values instead.
- Keep standard Mechanical Equipment List headers unchanged and in the same order.
- Additional columns must be inserted before:
  "DRY WT (each)", "OPE WT (each)", "DRY WT (total)", "OPE WT (total)", "REMARKS".
- These five columns must always remain at the end and always be blank:
  "DRY WT (each)", "OPE WT (each)", "DRY WT (total)", "OPE WT (total)", "REMARKS".
- Never infer, calculate, estimate, or populate these five columns, even if weight-related data exists.
- Missing or uncertain values must be "".
- Keep values concise and business-ready.

DOCUMENT FIELDS
- Use document-level fields when helpful:
  document_title, source_file, revision_number, document_numbers, page_number, table_number, split_number.
- Populate "P&ID" only from document_numbers when document_numbers is available.
- "CONTRACTOR EQUIPMENT TAG NO." should usually come from item/equipment tag or item number identifiers.

VALUE NORMALIZATION
- Normalize temperature unit variants like "OC", "0C", "oC", "Oc" to "°C".
- If "Material of Construction" starts with "Hell", replace only that term with "Shell".
- If DESCRIPTION, EQUIPMENT TYPE, or PRODUCT/SERVICE contains values like "(1 × 100%)", "(2 × 100%)", "(3 × 33%)", put that value in "CONFIGURATION".
- If DESCRIPTION, EQUIPMENT TYPE, or PRODUCT/SERVICE contains "Vertical" or "Horizontal", put it in "ORIENTATION".
- If the property is specifically "Motor Duty", map it to "MOTOR DUTY".
- Other duty values must go to "DUTY".

BLANK / DASH VALUE RULE
- If a source value is exactly "-" or only a dash-like placeholder, map it as "-" to the respective column.
- Do not append any unit to dash-only values.
  Example:
  - Source: ABSORBED POWER (kw) : "-"  or  ABSORBED POWER : "-kw"
  - Output: ABSORBED POWER : "-"
  - Not: "- kw"

DIMENSION/DUTY ROW RULE
- If a source row/property is "DIMENSION/DUTY", decide by the value content:
  - Map to dimension columns if the value contains dimension indicators such as "mm", "m", "ID", "I/D", "OD", "O/D", "D", "T/T", "S/F", "F/F", "dia", "diameter", or dimension-style patterns like "950 (I/D) X 1800 (T/T)".
  - Map to "DUTY" if the value contains duty units or duty-like values or no dimension indicators.
- For dimension values, apply the existing Dimension Mapping Rules.
- For duty values, keep the value concise and place it only in "DUTY".

DIMENSION MAPPING
- If dimension text contains diameter identifiers "ID", "I/D", "OD", "O/D", or "D":
  - Extract that value into "W or ID".
  - Preserve identifier and unit.
  - Example: "1700 mm (ID)", "812.8 mm (O/D)".
- For the remaining non-diameter dimension:
  - If ORIENTATION is Horizontal, map to "L or T/T".
  - If ORIENTATION is Vertical, map to "H or T/T".
  - If ORIENTATION is unclear, prefer "L or T/T" and leave "H or T/T" blank unless clearly vertical.
- Preserve identifiers like "T/T", "S/F", "F/F" with the value.
  Examples:
  - "5500 mm (T/T)"
  - "1450 mm (S/F)"

Return JSON only, with this shape. Extra property columns may also appear in each row object when needed:
{{
  "rows": [
    {{
      "REV No.": "",
      "CONTRACTOR EQUIPMENT TAG NO.": "",
      "DESCRIPTION": "",
      "EQUIPMENT TYPE": "",
      "PRODUCT/ SERVICE": "",
      "P&ID": "",
      "MATERIAL OF CONSTRUCTION": "",
      "CONFIGURATION": "",
      "ORIENTATION",
      "LOCATION": "",
      "OPERATING PRESSURE": "",
      "OPERATING TEMPERATURE": "",
      "DESIGN PRESSURE": "",
      "DESIGN TEMPERATURE": "",
      "DESIGN CAPACITY": "",
      "DIMENSION": "",
      "L or T/T": "",
      "W or ID": "",
      "H or T/T": "",
      "DUTY": "",
      "ABSORBED POWER": "",
      "DESIGN CODE": "",
      "DIFFERENTIAL PRESSURE": "",
      "DRY WT (each)": "",
      "OPE WT (each)": "",
      "DRY WT (total)": "",
      "OPE WT (total)": "",
      "REMARKS": ""
    }}
  ]
}}
""".strip()


def _normalize_cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_normalize_cell_value(item) for item in value if _normalize_cell_value(item))
    if isinstance(value, dict):
        parts = []
        for key, item_value in value.items():
            normalized_item = _normalize_cell_value(item_value)
            if normalized_item:
                parts.append(f"{key}: {normalized_item}")
        return ", ".join(parts)
    return str(value).strip()


def _normalize_mechanical_row(raw_row: Dict[str, Any]) -> Dict[str, str]:
    normalized_row = {}
    for header in MECHANICAL_TEMPLATE_HEADERS:
        normalized_row[header] = _normalize_cell_value(raw_row.get(header, ""))

    for key, value in raw_row.items():
        normalized_key = str(key).strip()
        if not normalized_key or normalized_key in normalized_row:
            continue
        normalized_row[normalized_key] = _normalize_cell_value(value)

    return normalized_row


def _ordered_mechanical_columns(rows: List[Dict[str, str]]) -> List[str]:
    extra_columns: List[str] = []

    fixed_tail_columns = [
        "DRY WT (each)",
        "OPE WT (each)",
        "DRY WT (total)",
        "OPE WT (total)",
        "REMARKS",
    ]

    base_columns = [
        column
        for column in MECHANICAL_TEMPLATE_HEADERS
        if column not in fixed_tail_columns
    ]

    for row in rows:
        for column in row.keys():
            if (
                column in MECHANICAL_TEMPLATE_HEADERS
                or column in extra_columns
            ):
                continue

            extra_columns.append(column)

    ordered_columns = (
        base_columns
        + extra_columns
        + fixed_tail_columns
    )

    return ordered_columns

@lru_cache(maxsize=128)
def _map_payload_json_to_mechanical_rows(payload_json: str) -> Tuple[List[Dict[str, str]], str]:
    payload = json.loads(payload_json)
    prompt = _build_mechanical_prompt(payload)

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            raw_text, model_name = _call_mechanical_model(prompt)
            break
        except Exception as error:
            if not _is_high_demand_error(error) or attempt == max_attempts:
                raise

            wait_seconds = attempt * 2
            time.sleep(wait_seconds)

    cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(cleaned_text)

    raw_rows = parsed.get("rows", parsed if isinstance(parsed, list) else [])
    if not isinstance(raw_rows, list):
        raise ValueError("Gemini did not return a valid rows list for the Mechanical Equipment List.")

    return [_normalize_mechanical_row(row or {}) for row in raw_rows], model_name


def build_collection_mechanical_equipment_list(
    documents: List[Dict[str, Any]]
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    all_rows: List[Dict[str, str]] = []
    errors: List[str] = []
    used_models: List[str] = []

    for document in documents:
        metadata = document.get("metadata", {})
        source_file = str(metadata.get("source_file", "uploaded PDF"))

        for section in document.get("tables") or []:
            payload = dict(section.get("equipment_json") or {})
            if not payload.get("equipment"):
                continue

            payload_json = json.dumps(payload, sort_keys=True)

            try:
                mapped_rows, model_name = _map_payload_json_to_mechanical_rows(payload_json)
            except Exception as exc:
                errors.append(f"{source_file}: {exc}")
                continue

            if model_name not in used_models:
                used_models.append(model_name)

            all_rows.extend(mapped_rows)

        for result in document.get("ocr_results") or []:
            payload = dict(result.get("ocr_json") or {})
            if not payload.get("matched_rows"):
                continue

            payload.setdefault("source_file", source_file)
            payload.setdefault("page_number", result.get("page_number"))

            payload_json = json.dumps(payload, sort_keys=True)

            try:
                mapped_rows, model_name = _map_payload_json_to_mechanical_rows(payload_json)
            except Exception as exc:
                page_number = result.get("page_number")
                page_suffix = f" | OCR page {page_number}" if page_number is not None else " | OCR"
                errors.append(f"{source_file}{page_suffix}: {exc}")
                continue

            if model_name not in used_models:
                used_models.append(model_name)

            all_rows.extend(mapped_rows)

    if not all_rows:
        return pd.DataFrame(columns=MECHANICAL_TEMPLATE_HEADERS), errors, used_models

    dataframe = pd.DataFrame(all_rows)
    dataframe = dataframe.reindex(columns=_ordered_mechanical_columns(all_rows)).fillna("")
    return dataframe, errors, used_models
