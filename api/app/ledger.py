"""공문 번호 대장 (v3, 로그인 필요). 공문 본문은 저장하지 않고 번호·날짜·제목·수신만 남긴다.

학생회 드라이브에서 5주 동안 낸 공문 15건의 번호를 한꺼번에 고친 사례가 있었다 — 다음 번호를 대장에서 정하고,
빈 번호·중복·날짜 역순을 바로 보여 준다.
"""

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app import db
from app.auth import current_user, origin_guard
from app.privacy import mask_text

router = APIRouter(prefix="/api/ledger", dependencies=[Depends(origin_guard)])  # 읽기 외 요청은 Origin 검사 (CSRF)

MAX_ENTRIES = 500  # 사용자당 (한 학기 공문 수를 넉넉히 넘는다)
_PREFIX = re.compile(r"^[0-9A-Za-z가-힣·\-_ ]{1,30}$")


def number_for(prefix: str, year: int, seq: int) -> str:
    return f"{prefix}-{year}-{seq:04d}"


def problems(entries: list[dict]) -> list[str]:
    """같은 기구·연도에서 빈 번호·중복 번호·날짜 역순을 찾는다 (entries는 seq 순)."""
    out: list[str] = []
    groups: dict[tuple[str, int], list[dict]] = {}
    for e in entries:
        groups.setdefault((e["prefix"], e["year"]), []).append(e)
    for (prefix, year), rows in groups.items():
        seqs = [r["seq"] for r in rows]
        dup = sorted({s for s in seqs if seqs.count(s) > 1})
        if dup:
            out.append(f"{prefix}-{year}: 겹치는 번호 {', '.join(f'{s:04d}' for s in dup)}")
        missing = sorted(set(range(1, max(seqs) + 1)) - set(seqs))
        if missing:
            shown = ", ".join(f"{s:04d}" for s in missing[:10]) + (" …" if len(missing) > 10 else "")
            out.append(f"{prefix}-{year}: 빠진 번호 {shown}")
        ordered = sorted(rows, key=lambda r: r["seq"])
        for a, b in zip(ordered, ordered[1:]):
            if b["issued_on"] < a["issued_on"]:
                out.append(f"{number_for(prefix, year, b['seq'])}의 시행일이 앞 번호보다 빨라요")
    return out


class EntryIn(BaseModel):
    prefix: str = Field(min_length=1, max_length=30)
    issued_on: date
    title: str = Field(min_length=1, max_length=120)
    recipient: str = Field(default="", max_length=60)
    seq: int | None = Field(default=None, ge=1, le=9999, description="비우면 다음 번호")

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, v: str) -> str:
        v = v.strip()
        if not _PREFIX.match(v):
            raise ValueError("기구 약칭은 한글·영문·숫자로 30자 이내여야 해요")
        return v


def _view(user: dict) -> dict:
    entries = db.list_ledger(user["id"])
    return {"entries": entries, "problems": problems(entries)}


@router.get("")
def list_entries(user: dict = Depends(current_user)) -> dict:
    return _view(user)


@router.get("/next")
def next_number(prefix: str, year: int, user: dict = Depends(current_user)) -> dict:
    seq = db.next_ledger_seq(user["id"], prefix.strip(), year)
    return {"seq": seq, "number": number_for(prefix.strip(), year, seq)}


@router.post("")
def add_entry(body: EntryIn, user: dict = Depends(current_user)) -> dict:
    if db.count_ledger(user["id"]) >= MAX_ENTRIES:
        raise HTTPException(status_code=429, detail="대장에는 500건까지 남길 수 있어요. 지난 기록을 지워 주세요.")
    db.add_ledger(
        user["id"], body.prefix, body.issued_on.year, body.seq, body.issued_on.isoformat(),
        mask_text(body.title), mask_text(body.recipient),
    )
    return _view(user)


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, user: dict = Depends(current_user)) -> dict:
    if not db.delete_ledger(user["id"], entry_id):
        raise HTTPException(status_code=404, detail="없는 기록이에요.")
    return _view(user)
