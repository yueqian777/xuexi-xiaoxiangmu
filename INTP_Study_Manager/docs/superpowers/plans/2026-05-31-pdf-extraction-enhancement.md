# PDF Extraction Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve uploaded PDF recognition with local structured extraction by default and optional MinerU high-accuracy extraction when the user installs it separately.

**Architecture:** Add a focused PDF extraction service that returns the existing slide-record shape, then route `ppt_service` through it. The Streamlit page exposes a PDF extraction settings expander that only offers MinerU when a configured or PATH-discovered executable is available.

**Tech Stack:** Python, Streamlit, PyMuPDF, pypdf, optional pdfplumber/pdfminer.six, optional external MinerU CLI/API installation.

---

### Task 1: Local Enhanced Extraction Service

**Files:**
- Create: `services/pdf_extraction_service.py`
- Test: `tests/test_pdf_extraction_service.py`

- [ ] **Step 1: Write failing tests**

Add tests for per-page fallback behavior, pdfplumber table-style extraction, and notes that identify the extraction source.

- [ ] **Step 2: Run the focused tests**

Run: `D:\SoftwareDownload\python.exe -B -m unittest tests.test_pdf_extraction_service`
Expected: FAIL because `services.pdf_extraction_service` does not exist yet.

- [ ] **Step 3: Implement the service**

Create a small service with:
- `extract_pdf_pages(path, method="local")`
- local pipeline: pypdf text, PyMuPDF fallback, optional pdfplumber text/table extraction when installed
- stable output keys: `slide_number`, `title`, `slide_text`, `notes`

- [ ] **Step 4: Run focused tests again**

Run: `D:\SoftwareDownload\python.exe -B -m unittest tests.test_pdf_extraction_service`
Expected: PASS.

### Task 2: MinerU Availability and Adapter

**Files:**
- Modify: `services/pdf_extraction_service.py`
- Test: `tests/test_pdf_extraction_service.py`

- [ ] **Step 1: Write failing tests**

Add tests for:
- MinerU unavailable when no executable/config exists
- MinerU output parsing from `*_content_list.json`
- status message includes installation/config guidance

- [ ] **Step 2: Implement adapter**

Add:
- `MinerUStatus`
- `get_mineru_status()`
- `extract_pdf_pages(..., method="mineru")`
- `INTP_MINERU_COMMAND` and `INTP_MINERU_OUTPUT_DIR` support

### Task 3: App Integration

**Files:**
- Modify: `services/ppt_service.py`
- Modify: `pages/ppt_tutor.py`
- Test: focused service tests plus syntax checks

- [ ] **Step 1: Route PDF imports and refresh through the new service**

`ppt_service.extract_pdf_pages()` becomes a compatibility wrapper around the new service.

- [ ] **Step 2: Add PDF extraction settings UI**

In the deck actions area, add an expander for PDF extraction mode. MinerU is only included in selectable options when `get_mineru_status().available` is true.

### Task 4: Documentation and Optional Dependency Contract

**Files:**
- Modify: `README.md`
- Modify: `requirements.txt`

- [ ] **Step 1: Document local enhanced extraction**

Explain that local enhanced extraction uses lightweight local dependencies for better tables/layout than the old pypdf-only path.

- [ ] **Step 2: Document MinerU as voluntary install**

Explain performance needs, Python/version caveats, D-drive install recommendation, and environment variables. Do not add `mineru` as a mandatory requirement.

### Task 5: Local MinerU Install

**Files:**
- No repository files.

- [ ] **Step 1: Create D-drive isolated environment**

Create `D:\MinerU\.venv` using the best available Python.

- [ ] **Step 2: Install MinerU**

Install MinerU into that environment only, then provide the command path for `INTP_MINERU_COMMAND`.

### Task 6: Verification

Run:
- `D:\SoftwareDownload\python.exe -B -m unittest tests.test_pdf_extraction_service`
- `D:\SoftwareDownload\python.exe -B -m unittest discover -s tests`
- Python AST/compile check
- `git diff --check`
- Streamlit HTTP smoke test
