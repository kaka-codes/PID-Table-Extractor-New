# import json
# import hashlib
# import time
# from io import BytesIO
# from pathlib import Path
# from zipfile import ZIP_DEFLATED, ZipFile
# from xml.sax.saxutils import escape
# import re

# import pandas as pd
# import streamlit as st
# import streamlit.components.v1 as components

# from processing.mechanical_equipment_list import (
#     MECHANICAL_TEMPLATE_HEADERS,
#     build_collection_mechanical_equipment_list,
# )
# from processing.structurer import (
#     build_document_for_upload,
#     retrieve_relevant_chunks,
#     select_documents_for_question,
# )

# RETRIEVED_CONTEXT_LIMIT = 1
# MULTI_VALUE_DELIMITER_RE = re.compile(r"\s*[;,]\s*")
# QUESTION_INPUT_LABEL = "Prompt about an equipment and get all it's details"

# st.set_page_config(page_title="P&ID Table Info Fetcher", layout="wide")

# st.title("Get P&ID Table Equipment Details 📋")

# st.caption(
#     "Upload one or more P&ID PDFs, and extract the equipments details from the tables.\n\n"
#     "(Upload < 10 PDFs at a time for best results)"
# )

# st.markdown(
#     """
#     <style>
#     [data-testid="stTextInput"] [data-testid="InputInstructions"] {
#         display: none;
#     }
#     </style>
#     """,
#     unsafe_allow_html=True,
# )


# @st.cache_data(show_spinner=False)
# def process_pdf(pdf_bytes: bytes, filename: str, file_size: int) -> dict:
#     return build_document_for_upload(pdf_bytes, filename, file_size)


# @st.cache_data(show_spinner=False)
# def build_mechanical_equipment_list_cached(documents_payload_json: str):
#     documents = json.loads(documents_payload_json)
#     return build_collection_mechanical_equipment_list(documents)


# def build_table_preview(table: dict) -> pd.DataFrame:
#     rows = table.get("rows", [])
#     if not rows:
#         return pd.DataFrame()

#     column_count = max(len(row) for row in rows)
#     columns = [f"Col {index + 1}" for index in range(column_count)]
#     normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
#     return pd.DataFrame(normalized_rows, columns=columns)


# def dedupe_display_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
#     if dataframe is None or dataframe.empty:
#         return dataframe

#     # Display-only cleanup so extraction outputs and downstream logic stay unchanged.
#     return dataframe.drop_duplicates(ignore_index=True)


# def add_display_index_column(dataframe: pd.DataFrame) -> pd.DataFrame:
#     if dataframe is None or dataframe.empty:
#         return dataframe

#     display_df = dataframe.reset_index(drop=True).copy()
#     display_df.insert(0, "Index", range(1, len(display_df) + 1))
#     return display_df


# def render_upload_processing_timer(started_at: float, completed_at: float = 0.0) -> None:
#     started_at_ms = int(max(float(started_at), 0.0) * 1000)
#     completed_at_ms = int(max(float(completed_at), 0.0) * 1000)
#     components.html(
#         f"""
#         <div id="upload-processing-timer" style="
#             padding: 0.75rem 1rem;
#             margin: 0.5rem 0 1rem 0;
#             border: 1px solid rgba(250, 250, 250, 0.12);
#             border-radius: 0.5rem;
#             background: rgba(49, 51, 63, 0.45);
#             color: #fafafa;
#             font-family: sans-serif;
#             font-size: 0.95rem;
#         ">
#             Processing uploaded PDFs... Elapsed time:
#             <strong id="upload-processing-elapsed">00:00</strong>
#         </div>
#         <script>
#         const startedAtMs = {started_at_ms};
#         const completedAtMs = {completed_at_ms};
#         const hideDelayMs = 3000;
#         const timerRoot = document.getElementById("upload-processing-timer");
#         const elapsedNode = document.getElementById("upload-processing-elapsed");
#         let intervalId = null;

#         function formatElapsed(totalSeconds) {{
#             const minutes = Math.floor(totalSeconds / 60);
#             const seconds = totalSeconds % 60;
#             return String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
#         }}

#         function updateElapsed() {{
#             if (!elapsedNode) return;
#             const effectiveNowMs = completedAtMs > 0 ? completedAtMs : Date.now();
#             const elapsedSeconds = Math.max(0, Math.floor((effectiveNowMs - startedAtMs) / 1000));
#             elapsedNode.textContent = formatElapsed(elapsedSeconds);
#         }}

#         function hideTimer() {{
#             if (timerRoot) {{
#                 timerRoot.style.display = "none";
#             }}
#         }}

#         updateElapsed();
#         if (completedAtMs > 0) {{
#             const remainingVisibleMs = Math.max(0, hideDelayMs - (Date.now() - completedAtMs));
#             window.setTimeout(hideTimer, remainingVisibleMs);
#         }} else {{
#             intervalId = window.setInterval(updateElapsed, 1000);
#         }}
#         </script>
#         """,
#         height=64,
#     )


# def mark_repeated_mechanical_tags_for_display(dataframe: pd.DataFrame) -> pd.DataFrame:
#     if dataframe is None or dataframe.empty:
#         return dataframe

#     tag_column = "CONTRACTOR EQUIPMENT TAG NO."
#     if tag_column not in dataframe.columns:
#         return dataframe

#     display_df = dataframe.copy()
#     seen_counts: dict[str, int] = {}

#     for row_index, value in display_df[tag_column].items():
#         text_value = str(value or "").strip()
#         if not text_value:
#             continue

#         seen_counts[text_value] = seen_counts.get(text_value, 0) + 1
#         if seen_counts[text_value] > 1:
#             display_df.at[row_index, tag_column] = f"{text_value} (repeat)"

#     return display_df


# def build_mechanical_row_ids(dataframe: pd.DataFrame) -> list[str]:
#     if dataframe is None or dataframe.empty:
#         return []

#     row_ids: list[str] = []
#     occurrence_counts: dict[str, int] = {}
#     normalized_df = dataframe.fillna("")

#     for _, row in normalized_df.iterrows():
#         row_payload = {column: str(row[column]) for column in normalized_df.columns}
#         row_hash = hashlib.sha256(
#             json.dumps(row_payload, sort_keys=True).encode("utf-8")
#         ).hexdigest()
#         occurrence_counts[row_hash] = occurrence_counts.get(row_hash, 0) + 1
#         row_ids.append(f"{row_hash}:{occurrence_counts[row_hash]}")

#     return row_ids


# def filter_mechanical_rows_by_deleted_ids(
#     dataframe: pd.DataFrame,
#     deleted_row_ids: set[str],
# ) -> pd.DataFrame:
#     if dataframe is None or dataframe.empty or not deleted_row_ids:
#         return dataframe

#     row_ids = build_mechanical_row_ids(dataframe)
#     kept_indices = [
#         index for index, row_id in enumerate(row_ids) if row_id not in deleted_row_ids
#     ]
#     return dataframe.iloc[kept_indices].reset_index(drop=True)


# def build_mechanical_row_delete_options(dataframe: pd.DataFrame) -> list[tuple[str, str]]:
#     if dataframe is None or dataframe.empty:
#         return []

#     row_ids = build_mechanical_row_ids(dataframe)
#     display_df = mark_repeated_mechanical_tags_for_display(dataframe).fillna("")
#     options: list[tuple[str, str]] = []

#     for index, row_id in enumerate(row_ids):
#         row = display_df.iloc[index]
#         tag_value = str(row.get("CONTRACTOR EQUIPMENT TAG NO.", "") or "").strip() or "-"
#         description_value = str(row.get("DESCRIPTION", "") or "").strip() or "-"
#         label = f"Row {index + 1} | {tag_value} | {description_value}"
#         options.append((label, row_id))

#     return options


# def _excel_column_name(index: int) -> str:
#     name = ""
#     current = index

#     while current >= 0:
#         current, remainder = divmod(current, 26)
#         name = chr(65 + remainder) + name
#         current -= 1

#     return name


# def _xml_safe_text(value) -> str:
#     if pd.isna(value):
#         return ""

#     text = str(value)
#     filtered = "".join(
#         character
#         for character in text
#         if character in ("\t", "\n", "\r") or ord(character) >= 32
#     )
#     return escape(filtered)


# def _build_excel_styles_xml() -> str:
#     return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
#   <fonts count="2">
#     <font>
#       <sz val="11"/>
#       <name val="Calibri"/>
#       <family val="2"/>
#     </font>
#     <font>
#       <b/>
#       <sz val="11"/>
#       <name val="Calibri"/>
#       <family val="2"/>
#     </font>
#   </fonts>
#   <fills count="2">
#     <fill><patternFill patternType="none"/></fill>
#     <fill><patternFill patternType="gray125"/></fill>
#   </fills>
#   <borders count="1">
#     <border><left/><right/><top/><bottom/><diagonal/></border>
#   </borders>
#   <cellStyleXfs count="1">
#     <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
#   </cellStyleXfs>
#   <cellXfs count="3">
#     <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
#     <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">
#       <alignment horizontal="center" vertical="center" wrapText="1"/>
#     </xf>
#     <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">
#       <alignment vertical="top" wrapText="1"/>
#     </xf>
#   </cellXfs>
#   <cellStyles count="1">
#     <cellStyle name="Normal" xfId="0" builtinId="0"/>
#   </cellStyles>
# </styleSheet>"""


# def _build_excel_cell_xml(row_index: int, column_index: int, value, style_id: int) -> str:
#     cell_ref = f"{_excel_column_name(column_index)}{row_index}"
#     return (
#         f'<c r="{cell_ref}" s="{style_id}" t="inlineStr">'
#         f'<is><t xml:space="preserve">{_xml_safe_text(value)}</t></is>'
#         f"</c>"
#     )


# def dataframe_to_excel_bytes(dataframe: pd.DataFrame, sheet_title: str = "Equipment List") -> bytes:
#     normalized_df = dataframe.fillna("")
#     row_count = len(normalized_df.index) + 1
#     column_count = len(normalized_df.columns)
#     last_cell = f"{_excel_column_name(max(column_count - 1, 0))}{max(row_count, 1)}"

#     column_width_xml = []
#     for column_index, column_name in enumerate(normalized_df.columns):
#         max_length = len(str(column_name))
#         for value in normalized_df.iloc[:, column_index].tolist():
#             max_length = max(max_length, len(str(value)))

#         adjusted_width = min(max_length + 4, 80)
#         column_number = column_index + 1
#         column_width_xml.append(
#             f'<col min="{column_number}" max="{column_number}" width="{adjusted_width}" customWidth="1"/>'
#         )

#     rows_xml = []
#     header_cells_xml = [
#         _build_excel_cell_xml(1, column_index, column_name, style_id=1)
#         for column_index, column_name in enumerate(normalized_df.columns)
#     ]
#     rows_xml.append(
#         f'<row r="1" spans="1:{max(column_count, 1)}">{"".join(header_cells_xml)}</row>'
#     )

#     for row_number, row_data in enumerate(normalized_df.values.tolist(), start=2):
#         row_cells_xml = [
#             _build_excel_cell_xml(row_number, column_index, value, style_id=2)
#             for column_index, value in enumerate(row_data)
#         ]
#         rows_xml.append(
#             f'<row r="{row_number}" spans="1:{max(column_count, 1)}">{"".join(row_cells_xml)}</row>'
#         )

#     worksheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
#   <dimension ref="A1:{last_cell}"/>
#   <sheetViews>
#     <sheetView workbookViewId="0">
#       <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
#       <selection pane="bottomLeft" activeCell="A2" sqref="A2"/>
#     </sheetView>
#   </sheetViews>
#   <sheetFormatPr defaultRowHeight="15"/>
#   <cols>
#     {"".join(column_width_xml)}
#   </cols>
#   <sheetData>
#     {"".join(rows_xml)}
#   </sheetData>
# </worksheet>"""

#     workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
#  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
#   <sheets>
#     <sheet name="{_xml_safe_text(sheet_title or 'Equipment List')}" sheetId="1" r:id="rId1"/>
#   </sheets>
# </workbook>"""

#     workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
#   <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
#   <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
# </Relationships>"""

#     root_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
#   <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
# </Relationships>"""

#     content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
#   <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
#   <Default Extension="xml" ContentType="application/xml"/>
#   <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
#   <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
#   <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
# </Types>"""

#     output = BytesIO()
#     with ZipFile(output, "w", ZIP_DEFLATED) as workbook_zip:
#         workbook_zip.writestr("[Content_Types].xml", content_types_xml)
#         workbook_zip.writestr("_rels/.rels", root_rels_xml)
#         workbook_zip.writestr("xl/workbook.xml", workbook_xml)
#         workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
#         workbook_zip.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
#         workbook_zip.writestr("xl/styles.xml", _build_excel_styles_xml())

#     return output.getvalue()


# def format_condition_summary(table: dict) -> str:
#     condition_matches = table.get("condition_matches", [])
#     if not condition_matches:
#         return "No keyword column met the matching condition."

#     match_bits = []
#     for match in condition_matches:
#         keyword_text = ", ".join(match.get("matched_keywords", []))
#         match_bits.append(f"Col {match.get('column_index', 0) + 1}: {keyword_text}")

#     return "Matched conditions in " + " | ".join(match_bits)


# def _uploaded_file_fingerprint(uploaded_file):
#     file_bytes = uploaded_file.getvalue()
#     return hashlib.sha256(file_bytes).hexdigest()


# def _expand_multivalue_field_line(line: str) -> str:
#     if ":" not in line:
#         return line

#     field_name, remainder = line.split(":", 1)
#     remainder = remainder.strip()
#     field_name_lower = field_name.lower()

#     if (
#         not remainder
#         or ("pressure" not in field_name_lower and "temperature" not in field_name_lower)
#         or ("," not in remainder and ";" not in remainder)
#     ):
#         return line

#     parts = [part.strip() for part in MULTI_VALUE_DELIMITER_RE.split(remainder) if part.strip()]
#     if len(parts) <= 1:
#         return line

#     return " , ".join(f"{field_name}: {part}" for part in parts)


# def format_chunk_text(text: str) -> str:
#     lines = []

#     for line in (text or "").splitlines():
#         lines.append(_expand_multivalue_field_line(line))

#     return "\n".join(lines)


# def format_extraction_caption(metadata: dict, ocr_results: list[dict]) -> str:
#     extraction_reason = metadata.get("extraction_reason")
#     if extraction_reason == "pdfplumber_error":
#         reason_text = "PDF table extraction failed under the size-based routing rule"
#     elif extraction_reason == "pdfplumber_no_condition_match":
#         reason_text = "No condition-matching table was found with pdfplumber, so OCR was used"
#     elif extraction_reason == "file_size_threshold":
#         reason_text = "File size exceeded 600 KB, so OCR was used"
#     else:
#         reason_text = "OCR was used"

#     return f"Extraction mode: OCR | {reason_text} | OCR pages: {len(ocr_results)}"


# def format_adjacent_table_status(metadata: dict) -> tuple[str, str]:
#     status = metadata.get("adjacent_table_extraction_status", "not_run")
#     message = str(metadata.get("adjacent_table_extraction_message", "") or "").strip()
#     page_number = metadata.get("adjacent_table_page_number")
#     table_number = metadata.get("adjacent_table_table_number")

#     location_bits = []
#     if page_number is not None:
#         location_bits.append(f"Page {page_number}")
#     if table_number is not None:
#         location_bits.append(f"Table {table_number}")

#     location_text = f" ({' | '.join(location_bits)})" if location_bits else ""

#     status_messages = {
#         "ok": f"Revision/document extraction succeeded{location_text}.",
#         "no_condition_matching_tables": (
#             "No extracted table matched the conditions, so the adjacent-table extraction did not run."
#         ),
#         "selected_table_not_found": "No equipment table was selected, so the adjacent-table extraction did not run.",
#         "next_table_not_found": "No next table was found after the selected equipment table.",
#         "empty_table": f"The next table{location_text} was empty after extraction.",
#         "missing_api_key": "GOOGLE_API_KEY is not set in Streamlit secrets, so adjacent-table extraction could not run.",
#         "dependency_missing": "The 'google-genai' package is not installed, so adjacent-table extraction could not run.",
#         "request_error": f"The Gemini request failed{location_text}.",
#         "empty_response": f"Gemini returned an empty response for the next table{location_text}.",
#         "parse_error": f"Gemini returned a response that could not be parsed as JSON{location_text}.",
#         "not_run": "Adjacent-table extraction did not run.",
#     }

#     severity = "success" if status == "ok" else "warning"
#     summary = status_messages.get(status, f"Adjacent-table extraction status: {status}{location_text}.")

#     if message:
#         summary = f"{summary} Details: {message}"

#     return severity, summary


# def render_retrieved_context(chunks: list[dict]) -> None:
#     with st.expander("Retrieved Context", expanded=True):
#         for chunk in chunks:
#             location_bits = [chunk.get("source_file", "uploaded PDF")]
#             if chunk.get("page_number") is not None:
#                 location_bits.append(f"Page {chunk['page_number']}")
#             if chunk.get("table_number") is not None:
#                 location_bits.append(f"Table {chunk['table_number']}")
#             if chunk.get("split_number"):
#                 location_bits.append(f"Section {chunk['split_number']}")
#             if chunk.get("equipment_number"):
#                 location_bits.append(f"Equipment {chunk['equipment_number']}")

#             st.markdown(f"**{' | '.join(location_bits)}**")
#             st.markdown(f"```text\n{format_chunk_text(chunk['text'])}\n```")


# def blur_question_input() -> None:
#     components.html(
#         """
#         <script>
#         const parentWindow = window.parent;
#         const parentDoc = parentWindow.document;

#         if (!parentWindow.__pidQuestionBlurHookInstalled) {
#             parentWindow.__pidQuestionBlurHookInstalled = true;

#             const blurQuestionInput = () => {
#                 const questionInput = parentDoc.querySelector(
#                     'input[aria-label="Enter an equipment prompt to retrieve matching context"]'
#                 );
#                 if (questionInput) {
#                     questionInput.blur();
#                 }

#                 if (parentDoc.activeElement && typeof parentDoc.activeElement.blur === "function") {
#                     parentDoc.activeElement.blur();
#                 }
#             };

#             const scheduleBlur = () => {
#                 [0, 50, 150, 300].forEach((delay) => {
#                     parentWindow.setTimeout(blurQuestionInput, delay);
#                 });
#             };

#             parentDoc.addEventListener("keydown", (event) => {
#                 const target = event.target;
#                 if (
#                     event.key === "Enter" &&
#                     target instanceof parentWindow.HTMLInputElement &&
#                     target.getAttribute("aria-label") === "Enter an equipment prompt to retrieve matching context"
#                 ) {
#                     scheduleBlur();
#                 }
#             }, true);

#             parentDoc.addEventListener("click", (event) => {
#                 const button = event.target instanceof parentWindow.Element
#                     ? event.target.closest('button[kind="primary"]')
#                     : null;

#                 if (
#                     button &&
#                     button.textContent &&
#                     ["Show Context", "Get Answer"].includes(button.textContent.trim())
#                 ) {
#                     scheduleBlur();
#                 }
#             }, true);

#             scheduleBlur();
#         }
#         </script>
#         """,
#         height=0,
#         width=0,
#     )


# with st.sidebar:
#     st.subheader("Collection")
#     st.caption("Retrieved context: top 1 most relevant chunk")
#     if st.button("Clear PDF Collection", use_container_width=True):
#         st.session_state["document_collection"] = {}
#         st.session_state["processed_upload_keys"] = set()
#         st.session_state["notified_skip_keys"] = set()
#         st.session_state["last_added_pdf_count"] = 0
#         st.session_state["last_skipped_pdf_names"] = []
#         st.session_state["mechanical_deleted_row_ids"] = set()
#         st.session_state["mechanical_deleted_row_signature"] = ""
#         st.session_state["upload_processing_timer_active"] = False
#         st.session_state["upload_processing_timer_started_at"] = 0.0
#         st.session_state["upload_processing_timer_completed_at"] = 0.0
#         st.session_state["uploader_reset_counter"] = int(
#             st.session_state.get("uploader_reset_counter", 0)
#         ) + 1
#         st.rerun()

# uploader_reset_counter = int(st.session_state.get("uploader_reset_counter", 0))

# uploaded_pdf_files = st.file_uploader(
#     "Upload one or more P&ID PDFs",
#     type=["pdf"],
#     accept_multiple_files=True,
#     key=f"uploaded_pdf_files_{uploader_reset_counter}",
# )
# uploaded_folder_files = st.file_uploader(
#     "Or upload a folder of P&ID PDFs",
#     type=["pdf"],
#     accept_multiple_files="directory",
#     help="Use this when you want to add an entire folder of PDF files at once.",
#     key=f"uploaded_folder_files_{uploader_reset_counter}",
# )

# uploaded_files = []
# uploaded_files_by_key = {}

# candidate_uploads = []
# candidate_uploads.extend(uploaded_pdf_files or [])
# candidate_uploads.extend(uploaded_folder_files or [])

# for uploaded_file in candidate_uploads:
#     upload_fingerprint = _uploaded_file_fingerprint(uploaded_file)
#     if upload_fingerprint in uploaded_files_by_key:
#         continue
#     uploaded_files_by_key[upload_fingerprint] = uploaded_file
#     uploaded_files.append(uploaded_file)

# with st.form("question_form", clear_on_submit=False, enter_to_submit=True):
#     question = st.text_input(
#         QUESTION_INPUT_LABEL,
#         key="question_input",
#     )
#     get_answer_clicked = st.form_submit_button("Show Context", type="primary")

# blur_question_input()

# result_container = st.container()
# timer_placeholder = st.empty()

# document_collection = dict(st.session_state.get("document_collection", {}))
# processed_upload_keys = set(st.session_state.get("processed_upload_keys", set()))
# notified_skip_keys = set(st.session_state.get("notified_skip_keys", set()))
# last_added_pdf_count = int(st.session_state.pop("last_added_pdf_count", 0))
# last_skipped_pdf_names = list(st.session_state.pop("last_skipped_pdf_names", []))
# upload_processing_timer_active = bool(
#     st.session_state.get("upload_processing_timer_active", False)
# )
# upload_processing_timer_started_at = float(
#     st.session_state.get("upload_processing_timer_started_at", 0.0) or 0.0
# )
# upload_processing_timer_completed_at = float(
#     st.session_state.get("upload_processing_timer_completed_at", 0.0) or 0.0
# )
# mechanical_deleted_row_ids = set(st.session_state.get("mechanical_deleted_row_ids", set()))
# mechanical_deleted_row_signature = str(
#     st.session_state.get("mechanical_deleted_row_signature", "") or ""
# )

# if (
#     upload_processing_timer_active
#     and upload_processing_timer_completed_at
#     and (time.time() - upload_processing_timer_completed_at) >= 3
# ):
#     upload_processing_timer_active = False
#     upload_processing_timer_started_at = 0.0
#     upload_processing_timer_completed_at = 0.0
#     st.session_state["upload_processing_timer_active"] = False
#     st.session_state["upload_processing_timer_started_at"] = 0.0
#     st.session_state["upload_processing_timer_completed_at"] = 0.0

# existing_upload_fingerprints = set()

# for key in document_collection.keys():
#     if isinstance(key, tuple) and key:
#         existing_upload_fingerprints.add(str(key[-1]))
#     else:
#         existing_upload_fingerprints.add(str(key))

# for key in processed_upload_keys:
#     if isinstance(key, tuple) and key:
#         existing_upload_fingerprints.add(str(key[-1]))
#     else:
#         existing_upload_fingerprints.add(str(key))

# fresh_uploaded_files = []
# newly_skipped_files = []

# for uploaded_file in uploaded_files:
#     upload_fingerprint = _uploaded_file_fingerprint(uploaded_file)
#     if upload_fingerprint in existing_upload_fingerprints:
#         if upload_fingerprint not in notified_skip_keys:
#             newly_skipped_files.append(uploaded_file.name)
#             notified_skip_keys.add(upload_fingerprint)
#         continue
#     fresh_uploaded_files.append(uploaded_file)

# if upload_processing_timer_active and upload_processing_timer_started_at:
#     with timer_placeholder:
#         render_upload_processing_timer(
#             upload_processing_timer_started_at,
#             upload_processing_timer_completed_at,
#         )

# if fresh_uploaded_files:
#     if not upload_processing_timer_started_at:
#         upload_processing_timer_started_at = time.time()
#     upload_processing_timer_active = True
#     st.session_state["upload_processing_timer_active"] = True
#     st.session_state["upload_processing_timer_started_at"] = upload_processing_timer_started_at
#     st.session_state["upload_processing_timer_completed_at"] = 0.0
#     upload_processing_timer_completed_at = 0.0

#     with timer_placeholder:
#         render_upload_processing_timer(upload_processing_timer_started_at)

#     with st.spinner("Extracting and structuring tables from uploaded PDFs..."):
#         for uploaded_file in fresh_uploaded_files:
#             upload_fingerprint = _uploaded_file_fingerprint(uploaded_file)
#             document_collection[upload_fingerprint] = process_pdf(
#                 uploaded_file.getvalue(),
#                 uploaded_file.name,
#                 getattr(uploaded_file, "size", len(uploaded_file.getvalue())),
#             )
#             processed_upload_keys.add(upload_fingerprint)

# st.session_state["document_collection"] = document_collection
# st.session_state["processed_upload_keys"] = processed_upload_keys

# st.session_state["notified_skip_keys"] = notified_skip_keys

# if uploaded_files:
#     st.session_state["last_added_pdf_count"] = len(fresh_uploaded_files)
#     st.session_state["last_skipped_pdf_names"] = sorted(set(newly_skipped_files))
#     st.session_state["uploader_reset_counter"] = uploader_reset_counter + 1
#     st.rerun()

# documents = list(document_collection.values())
# mechanical_collection_df = pd.DataFrame(columns=MECHANICAL_TEMPLATE_HEADERS)
# mechanical_errors = []
# mechanical_models = []

# if last_skipped_pdf_names:
#     skip_message = "Already uploaded, so skipped: " + ", ".join(last_skipped_pdf_names)
#     if hasattr(st, "toast"):
#         st.toast(skip_message)
#     else:
#         st.info(skip_message)

# if documents:
#     if last_added_pdf_count:
#         st.success(f"Added {last_added_pdf_count} new PDF(s) to the collection.")

#     total_raw_tables = sum(doc["metadata"].get("raw_table_count", 0) for doc in documents)
#     total_matched_tables = sum(
#         doc["metadata"].get(
#             "matched_table_count",
#             doc["metadata"].get("candidate_table_count", 0),
#         )
#         for doc in documents
#     )
#     total_tables = sum(doc["metadata"]["selected_table_count"] for doc in documents)
#     total_chunks = sum(doc["metadata"]["chunk_count"] for doc in documents)
#     total_ocr_documents = sum(
#         1 for doc in documents if doc["metadata"].get("extraction_mode") == "ocr"
#     )
#     files_with_tables = sum(
#         1
#         for doc in documents
#         if doc.get("extracted_tables") or doc["tables"] or doc.get("ocr_results")
#     )

#     st.info(
#         f"Collection contains {len(documents)} PDF(s)."
#         # f"table(s), {total_matched_tables} condition-matching table(s), "
#         # f"{total_tables} cleaned table section(s), built {total_chunks} QA chunk(s), and used OCR "
#         # f"for {total_ocr_documents} file(s) across {files_with_tables} file(s) with usable output."
#     )

#     for document_key, document in document_collection.items():
#         metadata = document["metadata"]
#         if metadata.get("extraction_mode") == "ocr":
#             expander_label = (
#                 f"{metadata['source_file']} "
#                 f"(OCR JSON | {len(document.get('ocr_results') or [])} page(s))"
#             )
#         else:
#             expander_label = (
#                 f"{metadata['source_file']} "
#                 f"({metadata.get('matched_table_count', 0)} matching table(s))"
#             )

#         with st.expander(expander_label):
#             if st.button(
#                 "Delete This PDF From Collection",
#                 key=f"delete-pdf-{document_key}",
#                 use_container_width=True,
#             ):
#                 document_collection.pop(document_key, None)
#                 processed_upload_keys.discard(document_key)
#                 notified_skip_keys.discard(document_key)
#                 st.session_state["document_collection"] = document_collection
#                 st.session_state["processed_upload_keys"] = processed_upload_keys
#                 st.session_state["notified_skip_keys"] = notified_skip_keys
#                 st.session_state["mechanical_deleted_row_ids"] = set()
#                 st.session_state["mechanical_deleted_row_signature"] = ""
#                 st.session_state["last_added_pdf_count"] = 0
#                 st.session_state["last_skipped_pdf_names"] = []
#                 st.session_state["uploader_reset_counter"] = uploader_reset_counter + 1
#                 st.rerun()

#             extracted_tables = document.get("extracted_tables") or []
#             ocr_results = document.get("ocr_results") or []
#             matching_tables = [
#                 table for table in extracted_tables if table.get("matches_conditions")
#             ]
#             extraction_mode = metadata.get("extraction_mode", "pdfplumber")

#             if not extracted_tables and not document["tables"] and not ocr_results:
#                 st.warning("No usable tables were extracted from this PDF.")
#             elif extraction_mode == "ocr":
#                 st.caption(format_extraction_caption(metadata, ocr_results))
#                 if not ocr_results:
#                     st.info("OCR was selected for this file, but no OCR JSON output was produced.")
#                 else:
#                     for result in ocr_results:
#                         st.markdown(f"**Page {result['page_number']} | OCR JSON**")
#                         st.json(result.get("ocr_json", {}))
#             else:
#                 st.caption(
#                     f"Raw tables: {metadata.get('raw_table_count', len(extracted_tables))} | "
#                     f"Matched conditions: {metadata.get('matched_table_count', 0)} | "
#                     f"Candidate tables: {metadata.get('candidate_table_count', 0)} | "
#                     f"Structured sections: {metadata.get('selected_table_count', len(document['tables']))} | "
#                     f"Equipment blocks: {metadata['equipment_count']}"
#                 )
#                 adjacent_status_severity, adjacent_status_text = format_adjacent_table_status(
#                     metadata
#                 )
#                 if adjacent_status_severity == "success":
#                     st.caption(f"Adjacent table: {adjacent_status_text}")
#                 else:
#                     st.warning(adjacent_status_text)

#                 if (
#                     metadata.get("matched_table_count", 0) == 0
#                     and metadata.get("selected_table_count", 0) > 0
#                 ):
#                     st.caption(
#                         "No extracted table met the keyword condition, so the fallback pipeline structured all extracted tables."
#                     )

#                 if not matching_tables:
#                     st.info("No condition-matching tables are available to display for this PDF.")
#                 else:
#                     for table in matching_tables:
#                         location_bits = [
#                             f"Page {table['page_number']}",
#                             f"Table {table['table_number']}",
#                         ]
#                         if table.get("split_number"):
#                             location_bits.append(f"Section {table['split_number']}")
#                         location_bits.append("Matches conditions")
#                         table_label = " | ".join(location_bits)

#                         st.markdown(f"**{table_label}**")
#                         st.caption(format_condition_summary(table))
#                         preview_df = build_table_preview(table)
#                         if not preview_df.empty:
#                             st.table(dedupe_display_rows(preview_df))

#                         related_sections = [
#                             section
#                             for section in document["tables"]
#                             if section["page_number"] == table["page_number"]
#                             and section["table_number"] == table["table_number"]
#                             and (
#                                 table.get("split_number") is None
#                                 or section.get("split_number") == table.get("split_number")
#                             )
#                         ]

#                         if related_sections:
#                             with st.expander("Structured JSON"):
#                                 for section in related_sections:
#                                     section_label = (
#                                         f"Section {section['split_number']}"
#                                         if section.get("split_number")
#                                         else "Structured table"
#                                     )
#                                     st.markdown(f"**{section_label}**")
#                                     st.json(section["equipment_json"])
#                         else:
#                             st.caption(
#                                 "This table matched the condition, but no structured section was produced after cleaning."
#                             )

#             st.download_button(
#                 "Download extracted JSON",
#                 data=json.dumps(document, indent=2),
#                 file_name=f"{Path(metadata['source_file']).stem}_table_qa.json",
#                 mime="application/json",
#                 key=f"download-{metadata['source_file']}",
#                 use_container_width=True,
#             )

# if documents:
#     documents_payload_json = json.dumps(documents, sort_keys=True)
#     with st.spinner("Building the Mechanical Equipment List from the structured JSON..."):
#         mechanical_collection_df, mechanical_errors, mechanical_models = (
#             build_mechanical_equipment_list_cached(documents_payload_json)
#         )
# else:
#     documents_payload_json = "[]"

# mechanical_collection_signature = hashlib.sha256(
#     documents_payload_json.encode("utf-8")
# ).hexdigest()
# if mechanical_collection_signature != mechanical_deleted_row_signature:
#     mechanical_deleted_row_ids = set()
#     mechanical_deleted_row_signature = mechanical_collection_signature
#     st.session_state["mechanical_deleted_row_ids"] = set()
#     st.session_state["mechanical_deleted_row_signature"] = mechanical_collection_signature

# st.subheader("Mechanical Equipment List")
# st.caption(
#     "This template-aligned table is generated from the structured JSON and mapped into the "
#     "Mechanical Equipment List columns using Gemini. Units are kept in the values."
# )

# if mechanical_models:
#     st.caption("Gemini model used: " + ", ".join(mechanical_models))

# if mechanical_errors:
#     st.warning("Mechanical Equipment List issues: " + " | ".join(mechanical_errors[:3]))

# filtered_mechanical_df = filter_mechanical_rows_by_deleted_ids(
#     mechanical_collection_df,
#     mechanical_deleted_row_ids,
# )
# mechanical_display_df = mark_repeated_mechanical_tags_for_display(filtered_mechanical_df)

# if mechanical_deleted_row_ids:
#     if st.button(
#         "Restore Deleted Mechanical Equipment Rows",
#         key=f"restore-mechanical-rows-{mechanical_collection_signature}",
#         use_container_width=True,
#     ):
#         mechanical_deleted_row_ids = set()
#         st.session_state["mechanical_deleted_row_ids"] = set()
#         st.session_state["mechanical_deleted_row_signature"] = mechanical_collection_signature
#         st.rerun()

# if not filtered_mechanical_df.empty:
#     with st.expander("Delete Mechanical Equipment List Rows"):
#         row_delete_options = build_mechanical_row_delete_options(filtered_mechanical_df)
#         row_delete_label_to_id = {label: row_id for label, row_id in row_delete_options}
#         selected_row_labels = st.multiselect(
#             "Select rows to delete",
#             options=list(row_delete_label_to_id.keys()),
#             key=f"mechanical-row-delete-{mechanical_collection_signature}",
#         )
#         if st.button(
#             "Delete Selected Rows",
#             key=f"delete-mechanical-rows-{mechanical_collection_signature}",
#             use_container_width=True,
#         ):
#             selected_row_ids = {
#                 row_delete_label_to_id[label] for label in selected_row_labels
#             }
#             if selected_row_ids:
#                 mechanical_deleted_row_ids.update(selected_row_ids)
#                 st.session_state["mechanical_deleted_row_ids"] = mechanical_deleted_row_ids
#                 st.session_state["mechanical_deleted_row_signature"] = (
#                     mechanical_collection_signature
#                 )
#                 st.rerun()

# st.dataframe(
#     mechanical_display_df,
#     use_container_width=True,
#     hide_index=True,
# )

# if documents and filtered_mechanical_df.empty:
#     if mechanical_collection_df.empty:
#         st.info("No Mechanical Equipment List rows are available yet.")
#     else:
#         st.info("All Mechanical Equipment List rows are currently deleted from view.")
# elif not filtered_mechanical_df.empty:
#     st.download_button(
#         "Download Mechanical Equipment List Excel",
#         data=dataframe_to_excel_bytes(
#             mechanical_display_df,
#             sheet_title="Mechanical Equipment List",
#         ),
#         file_name="mechanical_equipment_list.xlsx",
#         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         key="download-mechanical-equipment-list-excel",
#         use_container_width=True,
#     )

# if upload_processing_timer_active:
#     if not upload_processing_timer_completed_at:
#         upload_processing_timer_completed_at = time.time()
#         st.session_state["upload_processing_timer_completed_at"] = upload_processing_timer_completed_at

#     with timer_placeholder:
#         render_upload_processing_timer(
#             upload_processing_timer_started_at,
#             upload_processing_timer_completed_at,
#         )

# if get_answer_clicked:
#     with result_container:
#         if not question.strip():
#             validation_placeholder = st.empty()
#             validation_placeholder.warning("Enter a valid question")
#             time.sleep(2)
#             validation_placeholder.empty()
#         elif not documents:
#             st.warning("Upload at least one P&ID PDF first.")
#         elif not any(document["chunks"] for document in documents):
#             st.warning("No extracted table context is available yet.")
#         else:
#             selected_documents = select_documents_for_question(documents, question)
#             retrieved_chunks = retrieve_relevant_chunks(
#                 selected_documents,
#                 question,
#                 top_k=RETRIEVED_CONTEXT_LIMIT,
#             )

#             if not retrieved_chunks:
#                 st.warning("No relevant extracted table context was found for this question.")
#             else:
#                 selected_source_files = [
#                     document["metadata"]["source_file"] for document in selected_documents
#                 ]

#                 if len(selected_source_files) == 1 and len(documents) > 1:
#                     st.info(f"Searching only in: {selected_source_files[0]}")
#                 elif len(selected_source_files) < len(documents):
#                     st.info(
#                         "Searching in matched PDFs only: "
#                         + ", ".join(selected_source_files)
#                     )

#                 render_retrieved_context(retrieved_chunks)


import json
import hashlib
import time
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape
import re

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from processing.mechanical_equipment_list import (
    MECHANICAL_TEMPLATE_HEADERS,
    build_collection_mechanical_equipment_list,
)
from processing.structurer import (
    build_document_for_upload,
    retrieve_relevant_chunks,
    select_documents_for_question,
)

RETRIEVED_CONTEXT_LIMIT = 1
MULTI_VALUE_DELIMITER_RE = re.compile(r"\s*[;,]\s*")
QUESTION_INPUT_LABEL = "Prompt about an equipment and get all it's details"

st.set_page_config(page_title="P&ID Table Info Fetcher", layout="wide")

st.title("Get P&ID Table Equipment Details 📋")

st.caption(
    "Upload one or more P&ID PDFs, and extract the equipments details from the tables.\n\n"
    "(Upload < 10 PDFs at a time for best results)"
)

st.markdown(
    """
    <style>
    [data-testid="stTextInput"] [data-testid="InputInstructions"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def process_pdf(
    pdf_bytes: bytes,
    filename: str,
    file_size: int,
    force_ocr: bool = False,
) -> dict:
    return build_document_for_upload(
        pdf_bytes,
        filename,
        file_size,
        force_ocr=force_ocr,
    )


@st.cache_data(show_spinner=False)
def build_mechanical_equipment_list_cached(documents_payload_json: str):
    documents = json.loads(documents_payload_json)
    return build_collection_mechanical_equipment_list(documents)


def build_table_preview(table: dict) -> pd.DataFrame:
    rows = table.get("rows", [])
    if not rows:
        return pd.DataFrame()

    column_count = max(len(row) for row in rows)
    columns = [f"Col {index + 1}" for index in range(column_count)]
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    return pd.DataFrame(normalized_rows, columns=columns)


def dedupe_display_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return dataframe

    # Display-only cleanup so extraction outputs and downstream logic stay unchanged.
    return dataframe.drop_duplicates(ignore_index=True)


def add_display_index_column(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return dataframe

    display_df = dataframe.reset_index(drop=True).copy()
    display_df.insert(0, "Index", range(1, len(display_df) + 1))
    return display_df


def render_upload_processing_timer(started_at: float, completed_at: float = 0.0) -> None:
    started_at_ms = int(max(float(started_at), 0.0) * 1000)
    completed_at_ms = int(max(float(completed_at), 0.0) * 1000)
    components.html(
        f"""
        <div id="upload-processing-timer" style="
            padding: 0.75rem 1rem;
            margin: 0.5rem 0 1rem 0;
            border: 1px solid rgba(250, 250, 250, 0.12);
            border-radius: 0.5rem;
            background: rgba(49, 51, 63, 0.45);
            color: #fafafa;
            font-family: sans-serif;
            font-size: 0.95rem;
        ">
            Processing uploaded PDFs... Elapsed time:
            <strong id="upload-processing-elapsed">00:00</strong>
        </div>
        <script>
        const startedAtMs = {started_at_ms};
        const completedAtMs = {completed_at_ms};
        const hideDelayMs = 3000;
        const timerRoot = document.getElementById("upload-processing-timer");
        const elapsedNode = document.getElementById("upload-processing-elapsed");
        let intervalId = null;

        function formatElapsed(totalSeconds) {{
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;
            return String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
        }}

        function updateElapsed() {{
            if (!elapsedNode) return;
            const effectiveNowMs = completedAtMs > 0 ? completedAtMs : Date.now();
            const elapsedSeconds = Math.max(0, Math.floor((effectiveNowMs - startedAtMs) / 1000));
            elapsedNode.textContent = formatElapsed(elapsedSeconds);
        }}

        function hideTimer() {{
            if (timerRoot) {{
                timerRoot.style.display = "none";
            }}
        }}

        updateElapsed();
        if (completedAtMs > 0) {{
            const remainingVisibleMs = Math.max(0, hideDelayMs - (Date.now() - completedAtMs));
            window.setTimeout(hideTimer, remainingVisibleMs);
        }} else {{
            intervalId = window.setInterval(updateElapsed, 1000);
        }}
        </script>
        """,
        height=64,
    )


def mark_repeated_mechanical_tags_for_display(dataframe: pd.DataFrame) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return dataframe

    tag_column = "CONTRACTOR EQUIPMENT TAG NO."
    if tag_column not in dataframe.columns:
        return dataframe

    display_df = dataframe.copy()
    seen_counts: dict[str, int] = {}

    for row_index, value in display_df[tag_column].items():
        text_value = str(value or "").strip()
        if not text_value:
            continue

        seen_counts[text_value] = seen_counts.get(text_value, 0) + 1
        if seen_counts[text_value] > 1:
            display_df.at[row_index, tag_column] = f"{text_value} (repeat)"

    return display_df


def build_mechanical_row_ids(dataframe: pd.DataFrame) -> list[str]:
    if dataframe is None or dataframe.empty:
        return []

    row_ids: list[str] = []
    occurrence_counts: dict[str, int] = {}
    normalized_df = dataframe.fillna("")

    for _, row in normalized_df.iterrows():
        row_payload = {column: str(row[column]) for column in normalized_df.columns}
        row_hash = hashlib.sha256(
            json.dumps(row_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        occurrence_counts[row_hash] = occurrence_counts.get(row_hash, 0) + 1
        row_ids.append(f"{row_hash}:{occurrence_counts[row_hash]}")

    return row_ids


def filter_mechanical_rows_by_deleted_ids(
    dataframe: pd.DataFrame,
    deleted_row_ids: set[str],
) -> pd.DataFrame:
    if dataframe is None or dataframe.empty or not deleted_row_ids:
        return dataframe

    row_ids = build_mechanical_row_ids(dataframe)
    kept_indices = [
        index for index, row_id in enumerate(row_ids) if row_id not in deleted_row_ids
    ]
    return dataframe.iloc[kept_indices].reset_index(drop=True)


def build_mechanical_row_delete_options(dataframe: pd.DataFrame) -> list[tuple[str, str]]:
    if dataframe is None or dataframe.empty:
        return []

    row_ids = build_mechanical_row_ids(dataframe)
    display_df = mark_repeated_mechanical_tags_for_display(dataframe).fillna("")
    options: list[tuple[str, str]] = []

    for index, row_id in enumerate(row_ids):
        row = display_df.iloc[index]
        tag_value = str(row.get("CONTRACTOR EQUIPMENT TAG NO.", "") or "").strip() or "-"
        description_value = str(row.get("DESCRIPTION", "") or "").strip() or "-"
        label = f"Row {index + 1} | {tag_value} | {description_value}"
        options.append((label, row_id))

    return options


def _excel_column_name(index: int) -> str:
    name = ""
    current = index

    while current >= 0:
        current, remainder = divmod(current, 26)
        name = chr(65 + remainder) + name
        current -= 1

    return name


def _xml_safe_text(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value)
    filtered = "".join(
        character
        for character in text
        if character in ("\t", "\n", "\r") or ord(character) >= 32
    )
    return escape(filtered)


def _build_excel_styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font>
      <sz val="11"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
    <font>
      <b/>
      <sz val="11"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">
      <alignment vertical="top" wrapText="1"/>
    </xf>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>"""


def _build_excel_cell_xml(row_index: int, column_index: int, value, style_id: int) -> str:
    cell_ref = f"{_excel_column_name(column_index)}{row_index}"
    return (
        f'<c r="{cell_ref}" s="{style_id}" t="inlineStr">'
        f'<is><t xml:space="preserve">{_xml_safe_text(value)}</t></is>'
        f"</c>"
    )


def dataframe_to_excel_bytes(dataframe: pd.DataFrame, sheet_title: str = "Equipment List") -> bytes:
    normalized_df = dataframe.fillna("")
    row_count = len(normalized_df.index) + 1
    column_count = len(normalized_df.columns)
    last_cell = f"{_excel_column_name(max(column_count - 1, 0))}{max(row_count, 1)}"

    column_width_xml = []
    for column_index, column_name in enumerate(normalized_df.columns):
        max_length = len(str(column_name))
        for value in normalized_df.iloc[:, column_index].tolist():
            max_length = max(max_length, len(str(value)))

        adjusted_width = min(max_length + 4, 80)
        column_number = column_index + 1
        column_width_xml.append(
            f'<col min="{column_number}" max="{column_number}" width="{adjusted_width}" customWidth="1"/>'
        )

    rows_xml = []
    header_cells_xml = [
        _build_excel_cell_xml(1, column_index, column_name, style_id=1)
        for column_index, column_name in enumerate(normalized_df.columns)
    ]
    rows_xml.append(
        f'<row r="1" spans="1:{max(column_count, 1)}">{"".join(header_cells_xml)}</row>'
    )

    for row_number, row_data in enumerate(normalized_df.values.tolist(), start=2):
        row_cells_xml = [
            _build_excel_cell_xml(row_number, column_index, value, style_id=2)
            for column_index, value in enumerate(row_data)
        ]
        rows_xml.append(
            f'<row r="{row_number}" spans="1:{max(column_count, 1)}">{"".join(row_cells_xml)}</row>'
        )

    worksheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_cell}"/>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
      <selection pane="bottomLeft" activeCell="A2" sqref="A2"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    {"".join(column_width_xml)}
  </cols>
  <sheetData>
    {"".join(rows_xml)}
  </sheetData>
</worksheet>"""

    workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{_xml_safe_text(sheet_title or 'Equipment List')}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    root_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as workbook_zip:
        workbook_zip.writestr("[Content_Types].xml", content_types_xml)
        workbook_zip.writestr("_rels/.rels", root_rels_xml)
        workbook_zip.writestr("xl/workbook.xml", workbook_xml)
        workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        workbook_zip.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        workbook_zip.writestr("xl/styles.xml", _build_excel_styles_xml())

    return output.getvalue()


def format_condition_summary(table: dict) -> str:
    condition_matches = table.get("condition_matches", [])
    if not condition_matches:
        return "No keyword column met the matching condition."

    match_bits = []
    for match in condition_matches:
        keyword_text = ", ".join(match.get("matched_keywords", []))
        match_bits.append(f"Col {match.get('column_index', 0) + 1}: {keyword_text}")

    return "Matched conditions in " + " | ".join(match_bits)


def _uploaded_file_fingerprint(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    return hashlib.sha256(file_bytes).hexdigest()


def _expand_multivalue_field_line(line: str) -> str:
    if ":" not in line:
        return line

    field_name, remainder = line.split(":", 1)
    remainder = remainder.strip()
    field_name_lower = field_name.lower()

    if (
        not remainder
        or ("pressure" not in field_name_lower and "temperature" not in field_name_lower)
        or ("," not in remainder and ";" not in remainder)
    ):
        return line

    parts = [part.strip() for part in MULTI_VALUE_DELIMITER_RE.split(remainder) if part.strip()]
    if len(parts) <= 1:
        return line

    return " , ".join(f"{field_name}: {part}" for part in parts)


def format_chunk_text(text: str) -> str:
    lines = []

    for line in (text or "").splitlines():
        lines.append(_expand_multivalue_field_line(line))

    return "\n".join(lines)


def format_extraction_caption(metadata: dict, ocr_results: list[dict]) -> str:
    extraction_reason = metadata.get("extraction_reason")
    if extraction_reason == "pdfplumber_error":
        reason_text = "PDF table extraction failed under the size-based routing rule"
    elif extraction_reason == "pdfplumber_no_condition_match":
        reason_text = "No condition-matching table was found with pdfplumber, so OCR was used"
    elif extraction_reason == "file_size_threshold":
        reason_text = "File size exceeded 600 KB, so OCR was used"
    elif extraction_reason == "manual_ocr_toggle":
        reason_text = "Force OCR toggle was enabled, so OCR was used"
    else:
        reason_text = "OCR was used"

    return f"Extraction mode: OCR | {reason_text} | OCR pages: {len(ocr_results)}"


def format_adjacent_table_status(metadata: dict) -> tuple[str, str]:
    status = metadata.get("adjacent_table_extraction_status", "not_run")
    message = str(metadata.get("adjacent_table_extraction_message", "") or "").strip()
    page_number = metadata.get("adjacent_table_page_number")
    table_number = metadata.get("adjacent_table_table_number")

    location_bits = []
    if page_number is not None:
        location_bits.append(f"Page {page_number}")
    if table_number is not None:
        location_bits.append(f"Table {table_number}")

    location_text = f" ({' | '.join(location_bits)})" if location_bits else ""

    status_messages = {
        "ok": f"Revision/document extraction succeeded{location_text}.",
        "no_condition_matching_tables": (
            "No extracted table matched the conditions, so the adjacent-table extraction did not run."
        ),
        "selected_table_not_found": "No equipment table was selected, so the adjacent-table extraction did not run.",
        "next_table_not_found": "No next table was found after the selected equipment table.",
        "empty_table": f"The next table{location_text} was empty after extraction.",
        "missing_api_key": "GOOGLE_API_KEY is not set in Streamlit secrets, so adjacent-table extraction could not run.",
        "dependency_missing": "The 'google-genai' package is not installed, so adjacent-table extraction could not run.",
        "request_error": f"The Gemini request failed{location_text}.",
        "empty_response": f"Gemini returned an empty response for the next table{location_text}.",
        "parse_error": f"Gemini returned a response that could not be parsed as JSON{location_text}.",
        "not_run": "Adjacent-table extraction did not run.",
    }

    severity = "success" if status == "ok" else "warning"
    summary = status_messages.get(status, f"Adjacent-table extraction status: {status}{location_text}.")

    if message:
        summary = f"{summary} Details: {message}"

    return severity, summary


def render_retrieved_context(chunks: list[dict]) -> None:
    with st.expander("Retrieved Context", expanded=True):
        for chunk in chunks:
            location_bits = [chunk.get("source_file", "uploaded PDF")]
            if chunk.get("page_number") is not None:
                location_bits.append(f"Page {chunk['page_number']}")
            if chunk.get("table_number") is not None:
                location_bits.append(f"Table {chunk['table_number']}")
            if chunk.get("split_number"):
                location_bits.append(f"Section {chunk['split_number']}")
            if chunk.get("equipment_number"):
                location_bits.append(f"Equipment {chunk['equipment_number']}")

            st.markdown(f"**{' | '.join(location_bits)}**")
            st.markdown(f"```text\n{format_chunk_text(chunk['text'])}\n```")


def blur_question_input() -> None:
    components.html(
        """
        <script>
        const parentWindow = window.parent;
        const parentDoc = parentWindow.document;

        if (!parentWindow.__pidQuestionBlurHookInstalled) {
            parentWindow.__pidQuestionBlurHookInstalled = true;

            const blurQuestionInput = () => {
                const questionInput = parentDoc.querySelector(
                    'input[aria-label="Enter an equipment prompt to retrieve matching context"]'
                );
                if (questionInput) {
                    questionInput.blur();
                }

                if (parentDoc.activeElement && typeof parentDoc.activeElement.blur === "function") {
                    parentDoc.activeElement.blur();
                }
            };

            const scheduleBlur = () => {
                [0, 50, 150, 300].forEach((delay) => {
                    parentWindow.setTimeout(blurQuestionInput, delay);
                });
            };

            parentDoc.addEventListener("keydown", (event) => {
                const target = event.target;
                if (
                    event.key === "Enter" &&
                    target instanceof parentWindow.HTMLInputElement &&
                    target.getAttribute("aria-label") === "Enter an equipment prompt to retrieve matching context"
                ) {
                    scheduleBlur();
                }
            }, true);

            parentDoc.addEventListener("click", (event) => {
                const button = event.target instanceof parentWindow.Element
                    ? event.target.closest('button[kind="primary"]')
                    : null;

                if (
                    button &&
                    button.textContent &&
                    ["Show Context", "Get Answer"].includes(button.textContent.trim())
                ) {
                    scheduleBlur();
                }
            }, true);

            scheduleBlur();
        }
        </script>
        """,
        height=0,
        width=0,
    )


with st.sidebar:
    st.subheader("Collection")
    st.caption("Retrieved context: top 1 most relevant chunk")

    force_ocr_uploads = st.toggle(
        "Force OCR for new uploads",
        value=bool(st.session_state.get("force_ocr_uploads", False)),
        help=(
            "When enabled, PDFs uploaded after this will directly use OCR, "
            "even if they are below the 600 KB pdfplumber limit."
        ),
    )
    st.session_state["force_ocr_uploads"] = force_ocr_uploads
    if st.button("Clear PDF Collection", use_container_width=True):
        st.session_state["document_collection"] = {}
        st.session_state["processed_upload_keys"] = set()
        st.session_state["notified_skip_keys"] = set()
        st.session_state["last_added_pdf_count"] = 0
        st.session_state["last_skipped_pdf_names"] = []
        st.session_state["mechanical_deleted_row_ids"] = set()
        st.session_state["mechanical_deleted_row_signature"] = ""
        st.session_state["upload_processing_timer_active"] = False
        st.session_state["upload_processing_timer_started_at"] = 0.0
        st.session_state["upload_processing_timer_completed_at"] = 0.0
        st.session_state["uploader_reset_counter"] = int(
            st.session_state.get("uploader_reset_counter", 0)
        ) + 1
        st.rerun()

force_ocr_uploads = bool(st.session_state.get("force_ocr_uploads", False))
uploader_reset_counter = int(st.session_state.get("uploader_reset_counter", 0))

uploaded_pdf_files = st.file_uploader(
    "Upload one or more P&ID PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    key=f"uploaded_pdf_files_{uploader_reset_counter}",
)
uploaded_folder_files = st.file_uploader(
    "Or upload a folder of P&ID PDFs",
    type=["pdf"],
    accept_multiple_files="directory",
    help="Use this when you want to add an entire folder of PDF files at once.",
    key=f"uploaded_folder_files_{uploader_reset_counter}",
)

uploaded_files = []
uploaded_files_by_key = {}

candidate_uploads = []
candidate_uploads.extend(uploaded_pdf_files or [])
candidate_uploads.extend(uploaded_folder_files or [])

for uploaded_file in candidate_uploads:
    upload_fingerprint = _uploaded_file_fingerprint(uploaded_file)
    if upload_fingerprint in uploaded_files_by_key:
        continue
    uploaded_files_by_key[upload_fingerprint] = uploaded_file
    uploaded_files.append(uploaded_file)

with st.form("question_form", clear_on_submit=False, enter_to_submit=True):
    question = st.text_input(
        QUESTION_INPUT_LABEL,
        key="question_input",
    )
    get_answer_clicked = st.form_submit_button("Show Context", type="primary")

blur_question_input()

result_container = st.container()
timer_placeholder = st.empty()

document_collection = dict(st.session_state.get("document_collection", {}))
processed_upload_keys = set(st.session_state.get("processed_upload_keys", set()))
notified_skip_keys = set(st.session_state.get("notified_skip_keys", set()))
last_added_pdf_count = int(st.session_state.pop("last_added_pdf_count", 0))
last_skipped_pdf_names = list(st.session_state.pop("last_skipped_pdf_names", []))
upload_processing_timer_active = bool(
    st.session_state.get("upload_processing_timer_active", False)
)
upload_processing_timer_started_at = float(
    st.session_state.get("upload_processing_timer_started_at", 0.0) or 0.0
)
upload_processing_timer_completed_at = float(
    st.session_state.get("upload_processing_timer_completed_at", 0.0) or 0.0
)
mechanical_deleted_row_ids = set(st.session_state.get("mechanical_deleted_row_ids", set()))
mechanical_deleted_row_signature = str(
    st.session_state.get("mechanical_deleted_row_signature", "") or ""
)

if (
    upload_processing_timer_active
    and upload_processing_timer_completed_at
    and (time.time() - upload_processing_timer_completed_at) >= 3
):
    upload_processing_timer_active = False
    upload_processing_timer_started_at = 0.0
    upload_processing_timer_completed_at = 0.0
    st.session_state["upload_processing_timer_active"] = False
    st.session_state["upload_processing_timer_started_at"] = 0.0
    st.session_state["upload_processing_timer_completed_at"] = 0.0

existing_upload_fingerprints = set()

for key in document_collection.keys():
    if isinstance(key, tuple) and key:
        existing_upload_fingerprints.add(str(key[-1]))
    else:
        existing_upload_fingerprints.add(str(key))

for key in processed_upload_keys:
    if isinstance(key, tuple) and key:
        existing_upload_fingerprints.add(str(key[-1]))
    else:
        existing_upload_fingerprints.add(str(key))

fresh_uploaded_files = []
newly_skipped_files = []

for uploaded_file in uploaded_files:
    upload_fingerprint = _uploaded_file_fingerprint(uploaded_file)
    upload_key = ("ocr" if force_ocr_uploads else "auto", upload_fingerprint)

    if str(upload_key) in existing_upload_fingerprints:
        if str(upload_key) not in notified_skip_keys:
            newly_skipped_files.append(uploaded_file.name)
            notified_skip_keys.add(str(upload_key))
        continue

    fresh_uploaded_files.append(uploaded_file)

if upload_processing_timer_active and upload_processing_timer_started_at:
    with timer_placeholder:
        render_upload_processing_timer(
            upload_processing_timer_started_at,
            upload_processing_timer_completed_at,
        )

if fresh_uploaded_files:
    if not upload_processing_timer_started_at:
        upload_processing_timer_started_at = time.time()
    upload_processing_timer_active = True
    st.session_state["upload_processing_timer_active"] = True
    st.session_state["upload_processing_timer_started_at"] = upload_processing_timer_started_at
    st.session_state["upload_processing_timer_completed_at"] = 0.0
    upload_processing_timer_completed_at = 0.0

    with timer_placeholder:
        render_upload_processing_timer(upload_processing_timer_started_at)

    with st.spinner("Extracting and structuring tables from uploaded PDFs..."):
        for uploaded_file in fresh_uploaded_files:
            upload_fingerprint = _uploaded_file_fingerprint(uploaded_file)
            upload_key = ("ocr" if force_ocr_uploads else "auto", upload_fingerprint)
            uploaded_file_bytes = uploaded_file.getvalue()

            document_collection[upload_key] = process_pdf(
                uploaded_file_bytes,
                uploaded_file.name,
                getattr(uploaded_file, "size", len(uploaded_file_bytes)),
                force_ocr=force_ocr_uploads,
            )
            processed_upload_keys.add(upload_key)

st.session_state["document_collection"] = document_collection
st.session_state["processed_upload_keys"] = processed_upload_keys

st.session_state["notified_skip_keys"] = notified_skip_keys

if uploaded_files:
    st.session_state["last_added_pdf_count"] = len(fresh_uploaded_files)
    st.session_state["last_skipped_pdf_names"] = sorted(set(newly_skipped_files))
    st.session_state["uploader_reset_counter"] = uploader_reset_counter + 1
    st.rerun()

documents = list(document_collection.values())
mechanical_collection_df = pd.DataFrame(columns=MECHANICAL_TEMPLATE_HEADERS)
mechanical_errors = []
mechanical_models = []

if last_skipped_pdf_names:
    skip_message = "Already uploaded, so skipped: " + ", ".join(last_skipped_pdf_names)
    if hasattr(st, "toast"):
        st.toast(skip_message)
    else:
        st.info(skip_message)

if documents:
    if last_added_pdf_count:
        st.success(f"Added {last_added_pdf_count} new PDF(s) to the collection.")

    total_raw_tables = sum(doc["metadata"].get("raw_table_count", 0) for doc in documents)
    total_matched_tables = sum(
        doc["metadata"].get(
            "matched_table_count",
            doc["metadata"].get("candidate_table_count", 0),
        )
        for doc in documents
    )
    total_tables = sum(doc["metadata"]["selected_table_count"] for doc in documents)
    total_chunks = sum(doc["metadata"]["chunk_count"] for doc in documents)
    total_ocr_documents = sum(
        1 for doc in documents if doc["metadata"].get("extraction_mode") == "ocr"
    )
    files_with_tables = sum(
        1
        for doc in documents
        if doc.get("extracted_tables") or doc["tables"] or doc.get("ocr_results")
    )

    st.info(
        f"Collection contains {len(documents)} PDF(s)."
        # f"table(s), {total_matched_tables} condition-matching table(s), "
        # f"{total_tables} cleaned table section(s), built {total_chunks} QA chunk(s), and used OCR "
        # f"for {total_ocr_documents} file(s) across {files_with_tables} file(s) with usable output."
    )

    for document_key, document in document_collection.items():
        metadata = document["metadata"]
        if metadata.get("extraction_mode") == "ocr":
            expander_label = (
                f"{metadata['source_file']} "
                f"(OCR JSON | {len(document.get('ocr_results') or [])} page(s))"
            )
        else:
            expander_label = (
                f"{metadata['source_file']} "
                f"({metadata.get('matched_table_count', 0)} matching table(s))"
            )

        with st.expander(expander_label):
            if st.button(
                "Delete This PDF From Collection",
                key=f"delete-pdf-{document_key}",
                use_container_width=True,
            ):
                document_collection.pop(document_key, None)
                processed_upload_keys.discard(document_key)
                notified_skip_keys.discard(document_key)
                st.session_state["document_collection"] = document_collection
                st.session_state["processed_upload_keys"] = processed_upload_keys
                st.session_state["notified_skip_keys"] = notified_skip_keys
                st.session_state["mechanical_deleted_row_ids"] = set()
                st.session_state["mechanical_deleted_row_signature"] = ""
                st.session_state["last_added_pdf_count"] = 0
                st.session_state["last_skipped_pdf_names"] = []
                st.session_state["uploader_reset_counter"] = uploader_reset_counter + 1
                st.rerun()

            extracted_tables = document.get("extracted_tables") or []
            ocr_results = document.get("ocr_results") or []
            matching_tables = [
                table for table in extracted_tables if table.get("matches_conditions")
            ]
            extraction_mode = metadata.get("extraction_mode", "pdfplumber")

            if not extracted_tables and not document["tables"] and not ocr_results:
                st.warning("No usable tables were extracted from this PDF.")
            elif extraction_mode == "ocr":
                st.caption(format_extraction_caption(metadata, ocr_results))
                if not ocr_results:
                    st.info("OCR was selected for this file, but no OCR JSON output was produced.")
                else:
                    for result in ocr_results:
                        st.markdown(f"**Page {result['page_number']} | OCR JSON**")
                        st.json(result.get("ocr_json", {}))
            else:
                st.caption(
                    f"Raw tables: {metadata.get('raw_table_count', len(extracted_tables))} | "
                    f"Matched conditions: {metadata.get('matched_table_count', 0)} | "
                    f"Candidate tables: {metadata.get('candidate_table_count', 0)} | "
                    f"Structured sections: {metadata.get('selected_table_count', len(document['tables']))} | "
                    f"Equipment blocks: {metadata['equipment_count']}"
                )
                adjacent_status_severity, adjacent_status_text = format_adjacent_table_status(
                    metadata
                )
                if adjacent_status_severity == "success":
                    st.caption(f"Adjacent table: {adjacent_status_text}")
                else:
                    st.warning(adjacent_status_text)

                if (
                    metadata.get("matched_table_count", 0) == 0
                    and metadata.get("selected_table_count", 0) > 0
                ):
                    st.caption(
                        "No extracted table met the keyword condition, so the fallback pipeline structured all extracted tables."
                    )

                if not matching_tables:
                    st.info("No condition-matching tables are available to display for this PDF.")
                else:
                    for table in matching_tables:
                        location_bits = [
                            f"Page {table['page_number']}",
                            f"Table {table['table_number']}",
                        ]
                        if table.get("split_number"):
                            location_bits.append(f"Section {table['split_number']}")
                        location_bits.append("Matches conditions")
                        table_label = " | ".join(location_bits)

                        st.markdown(f"**{table_label}**")
                        st.caption(format_condition_summary(table))
                        preview_df = build_table_preview(table)
                        if not preview_df.empty:
                            st.table(dedupe_display_rows(preview_df))

                        related_sections = [
                            section
                            for section in document["tables"]
                            if section["page_number"] == table["page_number"]
                            and section["table_number"] == table["table_number"]
                            and (
                                table.get("split_number") is None
                                or section.get("split_number") == table.get("split_number")
                            )
                        ]

                        if related_sections:
                            with st.expander("Structured JSON"):
                                for section in related_sections:
                                    section_label = (
                                        f"Section {section['split_number']}"
                                        if section.get("split_number")
                                        else "Structured table"
                                    )
                                    st.markdown(f"**{section_label}**")
                                    st.json(section["equipment_json"])
                        else:
                            st.caption(
                                "This table matched the condition, but no structured section was produced after cleaning."
                            )

            st.download_button(
                "Download extracted JSON",
                data=json.dumps(document, indent=2),
                file_name=f"{Path(metadata['source_file']).stem}_table_qa.json",
                mime="application/json",
                key=f"download-{metadata['source_file']}",
                use_container_width=True,
            )

if documents:
    documents_payload_json = json.dumps(documents, sort_keys=True)
    with st.spinner("Building the Mechanical Equipment List from the structured JSON..."):
        mechanical_collection_df, mechanical_errors, mechanical_models = (
            build_mechanical_equipment_list_cached(documents_payload_json)
        )
else:
    documents_payload_json = "[]"

mechanical_collection_signature = hashlib.sha256(
    documents_payload_json.encode("utf-8")
).hexdigest()
if mechanical_collection_signature != mechanical_deleted_row_signature:
    mechanical_deleted_row_ids = set()
    mechanical_deleted_row_signature = mechanical_collection_signature
    st.session_state["mechanical_deleted_row_ids"] = set()
    st.session_state["mechanical_deleted_row_signature"] = mechanical_collection_signature

st.subheader("Mechanical Equipment List")
st.caption(
    "This template-aligned table is generated from the structured JSON and mapped into the "
    "Mechanical Equipment List columns using Gemini. Units are kept in the values."
)

if mechanical_models:
    st.caption("Gemini model used: " + ", ".join(mechanical_models))

if mechanical_errors:
    st.warning("Mechanical Equipment List issues: " + " | ".join(mechanical_errors[:3]))

filtered_mechanical_df = filter_mechanical_rows_by_deleted_ids(
    mechanical_collection_df,
    mechanical_deleted_row_ids,
)
mechanical_display_df = mark_repeated_mechanical_tags_for_display(filtered_mechanical_df)

if mechanical_deleted_row_ids:
    if st.button(
        "Restore Deleted Mechanical Equipment Rows",
        key=f"restore-mechanical-rows-{mechanical_collection_signature}",
        use_container_width=True,
    ):
        mechanical_deleted_row_ids = set()
        st.session_state["mechanical_deleted_row_ids"] = set()
        st.session_state["mechanical_deleted_row_signature"] = mechanical_collection_signature
        st.rerun()

if not filtered_mechanical_df.empty:
    with st.expander("Delete Mechanical Equipment List Rows"):
        row_delete_options = build_mechanical_row_delete_options(filtered_mechanical_df)
        row_delete_label_to_id = {label: row_id for label, row_id in row_delete_options}
        selected_row_labels = st.multiselect(
            "Select rows to delete",
            options=list(row_delete_label_to_id.keys()),
            key=f"mechanical-row-delete-{mechanical_collection_signature}",
        )
        if st.button(
            "Delete Selected Rows",
            key=f"delete-mechanical-rows-{mechanical_collection_signature}",
            use_container_width=True,
        ):
            selected_row_ids = {
                row_delete_label_to_id[label] for label in selected_row_labels
            }
            if selected_row_ids:
                mechanical_deleted_row_ids.update(selected_row_ids)
                st.session_state["mechanical_deleted_row_ids"] = mechanical_deleted_row_ids
                st.session_state["mechanical_deleted_row_signature"] = (
                    mechanical_collection_signature
                )
                st.rerun()

st.dataframe(
    mechanical_display_df,
    use_container_width=True,
    hide_index=True,
)

if documents and filtered_mechanical_df.empty:
    if mechanical_collection_df.empty:
        st.info("No Mechanical Equipment List rows are available yet.")
    else:
        st.info("All Mechanical Equipment List rows are currently deleted from view.")
elif not filtered_mechanical_df.empty:
    st.download_button(
        "Download Mechanical Equipment List Excel",
        data=dataframe_to_excel_bytes(
            mechanical_display_df,
            sheet_title="Mechanical Equipment List",
        ),
        file_name="mechanical_equipment_list.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download-mechanical-equipment-list-excel",
        use_container_width=True,
    )

if upload_processing_timer_active:
    if not upload_processing_timer_completed_at:
        upload_processing_timer_completed_at = time.time()
        st.session_state["upload_processing_timer_completed_at"] = upload_processing_timer_completed_at

    with timer_placeholder:
        render_upload_processing_timer(
            upload_processing_timer_started_at,
            upload_processing_timer_completed_at,
        )

if get_answer_clicked:
    with result_container:
        if not question.strip():
            validation_placeholder = st.empty()
            validation_placeholder.warning("Enter a valid question")
            time.sleep(2)
            validation_placeholder.empty()
        elif not documents:
            st.warning("Upload at least one P&ID PDF first.")
        elif not any(document["chunks"] for document in documents):
            st.warning("No extracted table context is available yet.")
        else:
            selected_documents = select_documents_for_question(documents, question)
            retrieved_chunks = retrieve_relevant_chunks(
                selected_documents,
                question,
                top_k=RETRIEVED_CONTEXT_LIMIT,
            )

            if not retrieved_chunks:
                st.warning("No relevant extracted table context was found for this question.")
            else:
                selected_source_files = [
                    document["metadata"]["source_file"] for document in selected_documents
                ]

                if len(selected_source_files) == 1 and len(documents) > 1:
                    st.info(f"Searching only in: {selected_source_files[0]}")
                elif len(selected_source_files) < len(documents):
                    st.info(
                        "Searching in matched PDFs only: "
                        + ", ".join(selected_source_files)
                    )

                render_retrieved_context(retrieved_chunks)

