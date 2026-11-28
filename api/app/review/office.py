"""한글(HWP·HWPX)·워드(DOCX) → 텍스트. 학생회 총회 자료의 절반 가까이가 한글 파일이다(2026-2 총회 자료 339개 중 HWP 141개).

표는 행 단위로 '칸 | 칸 | 칸' 한 줄로 낸다 — 예산표의 항목·단가·수량·금액이 한 줄에 남아야 추출·검산이 된다.
업로드 파일은 신뢰하지 않는다: 압축을 풀 때 크기 상한을 두고(압축 폭탄), 암호·배포용 문서는 거절한다.
"""

import io
import struct
import zipfile
import zlib
from xml.etree import ElementTree

MAX_UNPACKED = 40 * 1024 * 1024  # 한 파일에서 풀어 읽을 총량


class OfficeError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 문구."""


def _rows_text(rows: dict[int, dict[int, list[str]]]) -> list[str]:
    lines = []
    for r in sorted(rows):
        cells = [" ".join(t for t in rows[r][c] if t).strip() for c in sorted(rows[r])]
        if any(cells):
            lines.append(" | ".join(cells))
    return lines


# ---------------------------------------------------------------- HWP 5.0 (OLE 복합 문서 + 레코드)

_PARA_TEXT, _CTRL_HEADER, _LIST_HEADER = 0x10 + 51, 0x10 + 55, 0x10 + 56
_TABLE_ID = b" lbt"  # 컨트롤 ID 'tbl '을 리틀 엔디언으로 저장한 모양
# 8글자(16바이트)를 차지하는 확장·인라인 컨트롤 문자. 나머지 32 미만 문자는 1글자다.
_WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _records(data: bytes):
    pos, n = 0, len(data)
    while pos + 4 <= n:
        (head,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag, level, size = head & 0x3FF, (head >> 10) & 0x3FF, head >> 20
        if size == 0xFFF:
            if pos + 4 > n:
                return
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, level, data[pos : pos + size]
        pos += size


def _para_text(data: bytes) -> str:
    out, i, n = [], 0, len(data) // 2
    while i < n:
        (ch,) = struct.unpack_from("<H", data, i * 2)
        if ch >= 32:
            out.append(chr(ch))
            i += 1
        elif ch in _WIDE_CONTROLS:
            if ch == 9:
                out.append(" ")  # 탭
            i += 8
        else:
            if ch == 10:
                out.append(" ")  # 줄 바꿈
            i += 1  # 13 문단 끝 등
    return "".join(out).strip()


def hwp_section_lines(section: bytes) -> list[str]:
    """압축을 푼 BodyText/SectionN 한 개 → 줄 목록. 표는 행마다 한 줄."""
    lines: list[str] = []
    tables: list[dict] = []  # 중첩 표: {"level", "rows", "cell"}

    def close_table() -> None:
        table = tables.pop()
        emitted = _rows_text(table["rows"])
        if tables:
            parent = tables[-1]
            parent["rows"].setdefault(parent["cell"][0], {}).setdefault(parent["cell"][1], []).append(" / ".join(emitted))
        else:
            lines.extend(emitted)

    for tag, level, data in _records(section):
        while tables and level <= tables[-1]["level"]:
            close_table()
        if tag == _CTRL_HEADER and data[:4] == _TABLE_ID:
            tables.append({"level": level, "rows": {}, "cell": (0, 0)})
        elif tag == _LIST_HEADER and tables and level == tables[-1]["level"] + 1 and len(data) >= 12:
            col, row = struct.unpack_from("<HH", data, 8)
            tables[-1]["cell"] = (row, col)
        elif tag == _PARA_TEXT:
            text = _para_text(data)
            if not text:
                continue
            if tables:
                row, col = tables[-1]["cell"]
                tables[-1]["rows"].setdefault(row, {}).setdefault(col, []).append(text)
            else:
                lines.append(text)
    while tables:
        close_table()
    return lines


MAX_SECTIONS = 500  # 한 문서의 구역 수 상한 (실제 문서는 수십 개)


def _inflate(data: bytes, budget: int) -> bytes:
    d = zlib.decompressobj(-15)
    out = d.decompress(data, budget + 1)
    if len(out) > budget or d.unconsumed_tail:
        raise OfficeError("파일이 너무 커요. 내용을 나눠서 올려 주세요.")
    return out


def hwp_text(data: bytes) -> str:
    import olefile  # 한글 파일을 올릴 때만 불러온다

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except OSError as e:
        raise OfficeError("한글 파일을 열지 못했어요. 손상된 파일인지 확인해 주세요.") from e
    with ole:
        if not ole.exists("FileHeader"):
            raise OfficeError("한글(HWP) 파일이 아니에요.")
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
        if flags & 0b10:
            raise OfficeError("암호가 걸린 한글 파일이에요. 암호를 풀고 올려 주세요.")
        if flags & 0b100:
            raise OfficeError("배포용 한글 문서는 읽지 못해요. 한글에서 PDF로 저장해 올려 주세요.")
        compressed = bool(flags & 1)
        sections = sorted(
            (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
            key=lambda e: int(e[1][7:] or 0),
        )
        if len(sections) > MAX_SECTIONS:
            raise OfficeError("파일이 너무 커요. 내용을 나눠서 올려 주세요.")
        lines, budget = [], MAX_UNPACKED
        for entry in sections:
            # 읽기 전에 선언 크기로 상한을 본다 — 비압축 구역은 그대로 쌓이고, OLE 중복 참조면 같은 본문이 여러 번 읽힌다
            if ole.get_size(entry) > (MAX_UNPACKED if compressed else budget):
                raise OfficeError("파일이 너무 커요. 내용을 나눠서 올려 주세요.")
            raw = ole.openstream(entry).read()
            body = _inflate(raw, budget) if compressed else raw
            budget -= len(body)
            if budget < 0:
                raise OfficeError("파일이 너무 커요. 내용을 나눠서 올려 주세요.")
            lines.extend(hwp_section_lines(body))
    return "\n".join(lines)


# ---------------------------------------------------------------- HWPX·DOCX (ZIP + XML)
# 두 형식 모두 문단 p · 글자 t · 표 tbl · 행 tr · 칸 tc 로 이름이 같다 (네임스페이스만 다름).

_BREAKS = {"tab", "lineBreak", "br", "cr"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _xml_parts(data: bytes, pick) -> list[ElementTree.Element]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise OfficeError("파일을 열지 못했어요. 손상된 파일인지 확인해 주세요.") from e
    with zf:
        # section10이 section2보다 앞에 오지 않게 숫자로 정렬한다
        infos = sorted((i for i in zf.infolist() if pick(i.filename)), key=lambda i: (len(i.filename), i.filename))
        if not infos:
            raise OfficeError("본문을 찾지 못했어요. 한글·워드에서 PDF로 저장해 올려 주세요.")
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise OfficeError("파일이 너무 커요. 내용을 나눠서 올려 주세요.")
        # 파이썬 3.12의 expat은 엔티티 폭증을 막고, ElementTree는 외부 엔티티를 불러오지 않는다
        return [ElementTree.fromstring(zf.read(i)) for i in infos]


def _table(t: ElementTree.Element) -> list[str]:
    rows = []
    for tr in (c for c in t if _local(c.tag) == "tr"):
        cells = [" ".join(_walk(tc)).strip() for tc in tr if _local(tc.tag) == "tc"]
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def _paragraph(p: ElementTree.Element) -> list[str]:
    texts: list[str] = []
    tables: list[str] = []

    def visit(el: ElementTree.Element) -> None:
        for c in el:
            name = _local(c.tag)
            if name == "tbl":
                tables.extend(_table(c))
            elif name == "t":
                texts.append(c.text or "")
                for sub in c:  # <t>글<tab/>글</t> 처럼 섞인 내용
                    texts.append(" " if _local(sub.tag) in _BREAKS else "")
                    texts.append(sub.tail or "")
            elif name in _BREAKS:
                texts.append(" ")
            else:
                visit(c)

    visit(p)
    line = "".join(texts).strip()
    return ([line] if line else []) + tables


def _walk(el: ElementTree.Element) -> list[str]:
    lines: list[str] = []
    for child in el:
        name = _local(child.tag)
        if name == "tbl":
            lines.extend(_table(child))
        elif name == "p":
            lines.extend(_paragraph(child))
        else:
            lines.extend(_walk(child))
    return lines


def hwpx_text(data: bytes) -> str:
    roots = _xml_parts(data, lambda n: n.startswith("Contents/section") and n.endswith(".xml"))
    return "\n".join(line for r in roots for line in _walk(r))


def docx_text(data: bytes) -> str:
    (root,) = _xml_parts(data, lambda n: n == "word/document.xml")
    return "\n".join(_walk(root))
