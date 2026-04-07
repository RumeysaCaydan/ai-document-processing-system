from io import BytesIO
import os
from pathlib import Path
import re
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
import pytesseract

from database.database import SessionLocal, Base, engine
from models.models import Receipt

Base.metadata.create_all(bind=engine)

app = FastAPI()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def _detect_tesseract_exe() -> str | None:
    # 1) Already on PATH
    exe = shutil.which("tesseract")
    if exe:
        return exe

    # 2) Common Windows install location (UB-Mannheim)
    for candidate in (
        Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
        Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    ):
        if candidate.exists():
            return str(candidate)

    return None

def _detect_poppler_bin() -> str | None:
    """
    Best-effort Poppler bin detection on Windows.
    `pdf2image` needs `pdftoppm` (or `pdftocairo`) available, either via PATH or poppler_path.
    """
    # 1) Already on PATH
    if shutil.which("pdftoppm") or shutil.which("pdftocairo"):
        return None

    # 2) User-provided env override
    env_path = os.environ.get("POPPLER_PATH") or os.environ.get("POPPLER_BIN")
    if env_path and Path(env_path).exists():
        return env_path

    # 3) Common winget location
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
    # Keep line structure but normalize repeated spaces.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_with_pattern(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return match.group(1).strip()


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .:-")
    # Remove OCR spill-over tokens.
    cleaned = re.sub(r"\bAdi\s*Soyad[ıi]?\b.*$", "", cleaned, flags=re.IGNORECASE).strip(" .:-")
    return cleaned or None


def _extract_receipt_fields(raw_text: str) -> dict:
    text = _normalize_text(raw_text)

    amount = _extract_with_pattern(
        r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*,\d{2}\s*TL)(?!\w)",
        text,
        flags=re.IGNORECASE,
    )
    date = _extract_with_pattern(
        r"(\d{2}[./-]\d{2}[./-]\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)",
        text,
    )
    iban = _extract_with_pattern(
        r"(TR\d{2}(?:\s?\d{4}){5}\s?\d{2})",
        text,
        flags=re.IGNORECASE,
    )

    sender_name = None
    receiver_name = None
    for line in text.splitlines():
        if "Adi Soyadi/Unvan" in line or "Adi Soyadı/Unvan" in line:
            # OCR often outputs both sender and receiver on the same line.
            names = re.findall(
                r"Adi\s*Soyad[ıi]/Unvan\s*:\s*([A-ZÇĞİÖŞÜ\s\.]{3,})",
                line,
                flags=re.IGNORECASE,
            )
            cleaned = [_clean_name(n) for n in names if n.strip()]
            cleaned = [n for n in cleaned if n]
            if cleaned:
                sender_name = cleaned[0]
            if len(cleaned) > 1:
                receiver_name = cleaned[1]
            break

    # Fallback receiver extraction for lines like "Adi Soyadı/Unvan : NAME"
    if not receiver_name:
        receiver_name = _extract_with_pattern(
            r"Al[ıi]c[ıi]\s*[:\-]\s*([A-ZÇĞİÖŞÜ\s\.]{3,})",
            text,
            flags=re.IGNORECASE,
        )
        receiver_name = _clean_name(receiver_name)

    normalized_iban = iban.replace(" ", "") if iban else None

    return {
        "amount": amount,
        "date": date,
        "iban": normalized_iban,
        "sender_name": sender_name,
        "receiver_name": receiver_name,
    }

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

    if file_ext in {".png", ".jpg", ".jpeg"}:
        image = Image.open(BytesIO(content))
        raw_text = pytesseract.image_to_string(image, lang="tur+eng")
    else:
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
            raw_text = "\n".join(raw_text_parts).strip()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="PDF OCR failed. Check Poppler installation on Windows.",
            ) from exc

    return {
        "status": "ok",
        "filename": file.filename,
        "raw_text": raw_text.strip(),
        "extracted_fields": _extract_receipt_fields(raw_text),
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/test-db")
def test_db():
    db = SessionLocal()

    new_receipt = Receipt(
        name="Test User",
        iban="TR123456789",
        amount="1000"
    )

    db.add(new_receipt)
    db.commit()
    db.close()

    return {"message": "Veri eklendi"}