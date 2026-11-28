"""홈 화면 '다가오는 일정': 관리자가 총회·자료 제출 마감 같은 날짜를 넣으면 지나지 않은 것만 보여 준다.

설정 표의 `events` 한 줄(JSON 목록)에 둔다. 인하광장 학생자치기구 공고에서 확인한 날짜를 넣는 용도다.
"""

import json
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app import db
from app.notice import internal_href, one_line, today_kst

_KEY = "events"
MAX_EVENTS = 30
SHOW = 4  # 홈에 보이는 개수


class EventIn(BaseModel):
    date: date
    title: str = Field(min_length=1, max_length=80)
    href: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return one_line(v, "일정 이름을 적어 주세요.")

    @field_validator("href")
    @classmethod
    def _href(cls, v: str | None) -> str | None:
        return internal_href(v)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list, max_length=MAX_EVENTS)


def stored() -> list[dict]:
    try:
        items = json.loads(db.get_raw_setting(_KEY) or "[]")
    except ValueError:
        return []
    return items if isinstance(items, list) else []


def upcoming(today: date | None = None, limit: int = SHOW) -> list[dict]:
    day = (today or today_kst()).isoformat()
    return [e for e in stored() if e.get("date", "") >= day][:limit]


def save(body: EventsIn) -> list[dict]:
    items = sorted(({"date": e.date.isoformat(), "title": e.title, "href": e.href} for e in body.events), key=lambda e: e["date"])
    db.set_raw_setting(_KEY, json.dumps(items, ensure_ascii=False) if items else None)
    return items
