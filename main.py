from io import BytesIO
import os
from pathlib import Path
import re
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
import pytesseract

app = FastAPI()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _detect_tesseract_exe() -> str | None:
    exe = shutil.which("tesseract")
    if exe:
        return exe

    for candidate in (
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    ):
        if candidate.exists():
            return str(candidate)

    return None


def _detect_poppler_bin() -> str | None:
    if shutil.which("pdftoppm") or shutil.which("pdftocairo"):
        return None

    env_path = os.environ.get("POPPLER_PATH") or os.environ.get("POPPLER_BIN")
    if env_path and Path(env_path).exists():
        return env_path

    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None

    winget_packages = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
    if not winget_packages.exists():
        return None

    try:
        for exe in winget_packages.rglob("pdftoppm.exe"):
            return str(exe.parent)
    except Exception:
        return None

    return None


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_multi_pattern(patterns: list[str], text: str, flags: int = 0) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .:-")
    cleaned = re.sub(r"\bAdi\s*Soyad[ıi]?\b.*$", "", cleaned, flags=re.IGNORECASE).strip(" .:-")
    return cleaned or None


def _extract_receipt_fields(raw_text: str) -> dict:
    text = _normalize_text(raw_text)
    compact_text = re.sub(r"\s+", " ", text).strip()

    iban = _extract_multi_pattern([
        r"(TR[0-9O]{2}(?:\s*[0-9O]{4}){5}\s*[0-9O]{2})",
        r"(TR[0-9O]{24})"
    ], compact_text, flags=re.IGNORECASE)

    normalized_iban = iban.replace(" ", "").upper().replace("O", "0") if iban else None

    sender_name = None
    receiver_name = None

    names = re.findall(
        r"Ad[ıi]\s*Soyad[ıi]/?Unvan\s*:?\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\.]{3,}?)"
        r"(?=\s+Ad[ıi]\s*Soyad[ıi]/?Unvan|\s+Adres|\s+TR[0-9O]{2}|\s+VKN|\s+Vergi|\s+M[üu]steri|$)",
        compact_text,
        flags=re.IGNORECASE,
    )
    cleaned_names = [_clean_name(n) for n in names if n.strip()]
    cleaned_names = [n for n in cleaned_names if n]
    if cleaned_names:
        sender_name = cleaned_names[0]
    if len(cleaned_names) > 1:
        receiver_name = cleaned_names[1]

    if not receiver_name:
        receiver_name = _extract_multi_pattern([
            r"Al[ıi]c[ıi]\s*[:\-]\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\.]{3,})",
            r"Alici\s*[:\-]\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\.]{3,})",
            r"Gönderilen\s*Kişi\s*[:\-]\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\.]{3,})"
        ], compact_text, flags=re.IGNORECASE)

        receiver_name = _clean_name(receiver_name)

    if not sender_name:
        sender_name = _extract_multi_pattern([
            r"G[öo]nderici\s*[:\-]\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\.]{3,})",
            r"[İI]şlemi\s*Yapan\s*Ad-?Soyad\s*[:\-]\s*([A-ZÇĞİÖŞÜa-zçğıöşü\s\.]{3,})",
        ], compact_text, flags=re.IGNORECASE)
        sender_name = _clean_name(sender_name)

    return {
        "sender_name": sender_name,
        "receiver_name": receiver_name,
        "iban": normalized_iban,
    }


def _log_extraction(filename: str | None, raw_text: str, extracted_fields: dict) -> None:
    print("=" * 70, flush=True)
    print(f"[OCR+REGEX] File: {filename or 'unknown'}", flush=True)
    print("[OCR+REGEX] sender_name:", extracted_fields.get("sender_name"), flush=True)
    print("[OCR+REGEX] receiver_name:", extracted_fields.get("receiver_name"), flush=True)
    print("[OCR+REGEX] iban:", extracted_fields.get("iban"), flush=True)
    print("=" * 70, flush=True)


def _extract_text_from_content(content: bytes, file_ext: str) -> str:
    if file_ext in {".png", ".jpg", ".jpeg"}:
        image = Image.open(BytesIO(content))
        return pytesseract.image_to_string(image, lang="tur+eng")

    try:
        from pdf2image import convert_from_bytes
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="pdf2image not installed. Run: pip install pdf2image",
        ) from exc

    try:
        poppler_path = _detect_poppler_bin()
        pages = convert_from_bytes(content, poppler_path=poppler_path)
        raw_text_parts = []
        for page in pages:
            raw_text_parts.append(pytesseract.image_to_string(page, lang="tur+eng"))
        return "\n".join(raw_text_parts).strip()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="PDF OCR failed. Check Poppler installation on Windows.",
        ) from exc


@app.post("/upload")
async def upload_check(file: UploadFile = File(...)):
    tesseract_exe = _detect_tesseract_exe()
    if tesseract_exe:
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe

    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    save_path = UPLOAD_DIR / (file.filename or "uploaded_file")
    save_path.write_bytes(content)
    raw_text = _extract_text_from_content(content, file_ext)

    extracted_fields = _extract_receipt_fields(raw_text)
    _log_extraction(file.filename, raw_text, extracted_fields)

    return {
        "status": "ok",
        "filename": file.filename,
        "extracted_fields": extracted_fields,
    }


@app.get("/process-uploads")
def process_uploads():
    tesseract_exe = _detect_tesseract_exe()
    if tesseract_exe:
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe

    supported_exts = {".pdf", ".png", ".jpg", ".jpeg"}
    files = [p for p in sorted(UPLOAD_DIR.iterdir()) if p.is_file() and p.suffix.lower() in supported_exts]

    if not files:
        return {"status": "ok", "message": "No supported files found in uploads.", "count": 0, "results": []}

    results = []
    for path in files:
        try:
            content = path.read_bytes()
            raw_text = _extract_text_from_content(content, path.suffix.lower())
            extracted_fields = _extract_receipt_fields(raw_text)
            _log_extraction(path.name, raw_text, extracted_fields)
            results.append(
                {
                    "filename": path.name,
                    "status": "ok",
                    "extracted_fields": extracted_fields,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "filename": path.name,
                    "status": "error",
                    "detail": str(exc),
                }
            )

    return {"status": "ok", "count": len(results), "results": results}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/test-db")
def test_db():
    raise HTTPException(
        status_code=503,
        detail="Database phase is not active yet. Current phase only supports OCR + regex output.",
    )