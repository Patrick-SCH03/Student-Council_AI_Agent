"""올린 파일 → 텍스트. 원본은 저장하지 않고 메모리에서만 읽는다."""

import io
from dataclasses import dataclass, field

from pypdf import PdfReader

from app.review.models import Finding
from app.review.office import OfficeError, docx_text, hwp_text, hwpx_text
from app.review.sheets import SheetTooLarge, check_workbook, workbook_text

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 60
MAX_TEXT = 60_000
_OLE = bytes.fromhex("d0cf11e0a1b11ae1")  # HWP 5.0은 OLE 복합 문서다
_OFFICE = {"hwp": hwp_text, "hwpx": hwpx_text, "docx": docx_text}


class UnsupportedFile(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 문구를 담는다."""


@dataclass
class Extracted:
    kind: str  # pdf | xlsx | hwp | hwpx | docx
    text: str
    pages: int = 0
    findings: list[Finding] = field(default_factory=list)  # 파일 자체 검사(수식 등)


def _kind(filename: str, data: bytes) -> str:
    name = filename.lower()
    if data[:4] == b"%PDF" or name.endswith(".pdf"):
        return "pdf"
    if data[:2] == b"PK" and name.endswith((".xlsx", ".xlsm")):
        return "xlsx"
    if data[:2] == b"PK" and name.endswith(".hwpx"):
        return "hwpx"
    if data[:2] == b"PK" and name.endswith(".docx"):
        return "docx"
    if data[:8] == _OLE and name.endswith(".hwp"):
        return "hwp"
    if name.endswith((".pdf", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".docx")):
        # 확장자는 맞는데 내용이 그 형식이 아니다 (손상·이름만 바꾼 파일·한글 97 같은 옛 형식)
        raise UnsupportedFile("파일을 열지 못했어요. 손상됐거나 확장자와 내용이 다른 파일이에요. 다시 저장하거나 PDF로 올려 주세요.")
    if name.endswith((".xls", ".doc")):
        raise UnsupportedFile("예전 형식(.xls·.doc)은 읽지 못해요. 새 형식(.xlsx·.docx)이나 PDF로 저장해 올려 주세요.")
    raise UnsupportedFile("PDF·한글(.hwp·.hwpx)·워드(.docx)·엑셀(.xlsx) 파일만 올릴 수 있어요.")


def _pdf_text(data: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages[:MAX_PAGES]
    parts = [f"[{i}쪽]\n{(page.extract_text() or '').strip()}" for i, page in enumerate(pages, 1)]
    return "\n".join(parts), len(reader.pages)


def extract_file(filename: str, data: bytes) -> Extracted:
    if not data:
        raise UnsupportedFile("빈 파일이에요.")
    if len(data) > MAX_BYTES:
        raise UnsupportedFile("파일이 너무 커요. 15MB 이하로 올려 주세요.")
    kind = _kind(filename, data)
    try:
        findings: list[Finding] = []
        pages = 0
        if kind == "pdf":
            text, pages = _pdf_text(data)
        elif kind == "xlsx":
            text = workbook_text(data)
            findings = check_workbook(data)
        else:
            text = _OFFICE[kind](data)
    except UnsupportedFile:
        raise
    except OfficeError as e:
        raise UnsupportedFile(str(e)) from e
    except SheetTooLarge as e:
        raise UnsupportedFile(str(e)) from e
    except Exception as e:  # noqa: BLE001 - 손상·암호화 파일은 이유를 사용자 문구로 바꾼다
        raise UnsupportedFile("파일을 열지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인해 주세요.") from e
    if len(text.replace("\n", "").strip()) < 30:
        raise UnsupportedFile("글자를 읽지 못했어요. 스캔한 이미지 PDF라면 한글·워드에서 PDF로 다시 저장해 올려 주세요.")
    return Extracted(kind=kind, text=text[:MAX_TEXT], pages=pages, findings=findings)
