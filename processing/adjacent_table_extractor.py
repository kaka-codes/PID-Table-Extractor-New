import json
import re
import time
from io import BytesIO
from typing import Any, Dict
from urllib import error, request

import pandas as pd
import pdfplumber

from google_api_key import get_google_api_key

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
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


def _generate_gemini_content(prompt: str) -> str:
    google_api_key = get_google_api_key()
    if not google_api_key:
        raise ValueError("Set GOOGLE_API_KEY in Streamlit secrets before running this script.")

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
        },
    }

    body = json.dumps(payload).encode("utf-8")
    endpoint = DEFAULT_GEMINI_API_URL.format(model=DEFAULT_GEMINI_MODEL)
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
        with request.urlopen(http_request, timeout=60) as response:
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


def dataframe_to_text(df: pd.DataFrame) -> str:
    rows = []
    for _, row in df.iterrows():
        clean_row = [str(cell).strip() for cell in row]
        rows.append(" | ".join(clean_row))
    return "\n".join(rows)


def is_high_demand_error(error: Exception) -> bool:
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


def extract_required_data(table_text: str) -> Dict[str, Any]:
    table_text = table_text[:12000]

    prompt = f"""
    You are reading an engineering equipment datasheet table extracted from a PDF.

    Extract:
    - revision_number
    - document_numbers

    Rules:
    - Extract ALL document numbers in the table

    - For revision_number:
    1. Prefer the COMPANY REVISION CODE if explicitly mentioned (e.g., "Company Rev", "Client Rev", "Company Revision")
    2. If latest company revision is NOT present, extract the latest revision code available in the table
    3. Latest revision = most recent entry

    - For document_numbers:
    1. Document numbers are not present in Document Title so, do not confuse with it.
    2. They may be present in Document Ids.
    3. They may be present as just No.
    4. Use your knowledge of what a P&ID document number looks like.

    Return ONLY valid JSON in this exact format:

    {{
    "revision_number": "",
    "document_numbers": []
    }}

    Additional rules:
    - Do NOT return multiple revisions, only one final value based on the latest date above
    - Do NOT hallucinate values
    - Ignore empty or irrelevant rows
    - If nothing is found, return "" for revision_numbers and [] for document_numbers
    - Output strictly JSON only (no explanation)

    TABLE:
    {table_text}
    """

    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            raw = _generate_gemini_content(prompt)
            break
        except Exception as error:
            if not is_high_demand_error(error) or attempt == max_attempts:
                raise

            wait_seconds = attempt * 2
            time.sleep(wait_seconds)

    raw = raw.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    parsed = json.loads(raw)
    document_numbers = parsed.get("document_numbers")

    if isinstance(document_numbers, list) and len(document_numbers) >= 3:
        parsed["document_numbers"] = document_numbers[-3:]

    return parsed


def extract_required_data_from_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        return {"ok": False, "status": "empty_table", "data": {}}

    table_text = dataframe_to_text(df)
    if not table_text.strip():
        return {"ok": False, "status": "empty_table", "data": {}}

    try:
        parsed = extract_required_data(table_text)
    except Exception as error:
        raw_output = getattr(error, "raw_output", "")
        message = str(error)
        if "GOOGLE_API_KEY" in message:
            status = "missing_api_key"
        else:
            status = "parse_error" if isinstance(error, json.JSONDecodeError) else "request_error"
        result: Dict[str, Any] = {
            "ok": False,
            "status": status,
            "message": message,
            "data": {},
        }
        if raw_output:
            result["raw_output"] = raw_output
        return result

    revision_number = str(parsed.get("revision_number", "") or "").strip()
    document_title = str(parsed.get("document_title", "") or "").strip()
    document_numbers = parsed.get("document_numbers", [])

    if not isinstance(document_numbers, list):
        document_numbers = [document_numbers] if document_numbers else []

    normalized_document_numbers = [
        str(value).strip() for value in document_numbers if str(value).strip()
    ]

    return {
        "ok": True,
        "status": "ok",
        "data": {
            "revision_number": revision_number,
            "document_numbers": normalized_document_numbers,
        },
    }


def extract_raw_tables_for_adjacent_lookup(pdf_bytes: bytes) -> list[dict[str, Any]]:
    pdf_source = BytesIO(pdf_bytes)
    all_tables: list[dict[str, Any]] = []

    with pdfplumber.open(pdf_source) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables() or []

            for table_no, table_obj in enumerate(tables, start=1):
                table = table_obj.extract()
                if not table:
                    continue

                df = pd.DataFrame(table).fillna("")
                all_tables.append(
                    {
                        "page_number": page_no,
                        "table_number": table_no,
                        "dataframe": df,
                        "bbox": {
                            "x0": float(table_obj.bbox[0]),
                            "top": float(table_obj.bbox[1]),
                            "x1": float(table_obj.bbox[2]),
                            "bottom": float(table_obj.bbox[3]),
                        },
                    }
                )

    return all_tables


def extract_required_data_from_next_source_table(
    pdf_bytes: bytes,
    source_page_number: int,
    source_table_number: int,
) -> Dict[str, Any]:
    all_tables = extract_raw_tables_for_adjacent_lookup(pdf_bytes)
    source_index = None

    for index, item in enumerate(all_tables):
        if (
            item["page_number"] == source_page_number
            and item["table_number"] == source_table_number
        ):
            source_index = index
            break

    if source_index is None:
        return {
            "ok": False,
            "status": "source_table_not_found",
            "message": (
                "The displayed equipment table's source table could not be matched "
                "in the raw pdfplumber table sequence."
            ),
            "data": {},
        }

    next_index = source_index + 1
    if next_index >= len(all_tables):
        return {
            "ok": False,
            "status": "next_table_not_found",
            "message": "No next raw table was found after the displayed equipment table's source table.",
            "data": {},
        }

    next_table = all_tables[next_index]
    extraction_result = extract_required_data_from_dataframe(next_table["dataframe"])
    extraction_result["adjacent_table_page_number"] = next_table["page_number"]
    extraction_result["adjacent_table_table_number"] = next_table["table_number"]
    return extraction_result
