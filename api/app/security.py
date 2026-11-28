"""관리자 인증. 관리자 API(app/admin.py)와 채팅의 한도 예외 판정(main.py)이 함께 쓴다."""

import re
import secrets

from fastapi import Depends, Header, HTTPException, Request

from app.auth import optional_user, origin_guard
from app.config import ADMIN_TOKEN


# 관리자 계정 세션(쿠키)으로 열 수 있는 경로 — 관리자 패널(/stats)이 쓰는 것만 명시한다.
# 그 밖(문서·색인·백업, 앞으로 생길 관리자 경로)은 기본으로 토큰만 받는다 (Fable 리뷰: 막을 목록보다 열 목록이 안전)
SESSION_PATHS = re.compile(r"/api/(?:stats|stats/export|settings|settings/notice|settings/notice/draft|settings/events|users|users/\d+|users/\d+/(?:logout|block)|cache/clear|analyses/\d+)")


def _token_ok(authorization: str | None) -> bool:
    # 바이트로 비교한다. 문자열 비교는 비ASCII 헤더에서 TypeError → 500이 된다.
    return bool(ADMIN_TOKEN and authorization) and secrets.compare_digest(
        authorization.encode(), f"Bearer {ADMIN_TOKEN}".encode()
    )


def require_admin(request: Request, authorization: str | None = Header(default=None)) -> None:
    """관리자 전용 엔드포인트 보호. ADMIN_TOKEN 또는 (패널 경로에 한해) 관리자 계정(ADMIN_EMAILS) 로그인 세션.

    문서 관리와 운영 지표(전체 질의 로그 포함)는 공개되면 안 되므로,
    토큰도 관리자 세션도 없으면 열어두지 않고 차단한다.
    세션(쿠키)으로 들어온 상태 변경 요청은 로그인 라우터와 같이 Origin을 검사한다 (CSRF).
    브라우저에 낡은 토큰이 남아 있어도 관리자 세션이면 들어온다 (토큰이 틀렸다고 세션까지 막지 않는다).
    """
    if _token_ok(authorization):
        return
    if SESSION_PATHS.fullmatch(request.url.path):
        user = optional_user(request)
        if user and user["role"] == "admin":
            origin_guard(request)
            return
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN이 설정되지 않아 관리자 API를 열지 않았어요.",
        )
    raise HTTPException(status_code=401, detail="관리자 인증이 필요해요.")


admin_only = Depends(require_admin)


def is_admin_request(authorization: str | None) -> bool:
    """관리자 토큰이 실린 요청인지 판별한다 (차단하지 않고 참/거짓만 돌려준다).

    회귀 테스트처럼 운영자가 직접 돌리는 질의까지 일일 한도에 걸리면
    정작 점검이 막힌다. 한도 계산에서만 빼고 지표에는 그대로 기록한다.
    """
    return _token_ok(authorization)
