"""관리자 인증. 관리자 API(app/admin.py)와 채팅의 한도 예외 판정(main.py)이 함께 쓴다."""

import secrets

from fastapi import Depends, Header, HTTPException

from app.config import ADMIN_TOKEN


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """관리자 전용 엔드포인트 보호.

    문서 관리와 운영 지표(전체 질의 로그 포함)는 공개되면 안 되므로,
    ADMIN_TOKEN이 설정되지 않은 경우 열어두지 않고 차단한다.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN이 설정되지 않아 관리자 API를 열지 않았어요.",
        )
    expected = f"Bearer {ADMIN_TOKEN}"
    # 바이트로 비교한다. 문자열 비교는 비ASCII 헤더에서 TypeError → 500이 된다.
    if not authorization or not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="관리자 인증이 필요해요.")


admin_only = Depends(require_admin)


def is_admin_request(authorization: str | None) -> bool:
    """관리자 토큰이 실린 요청인지 판별한다 (차단하지 않고 참/거짓만 돌려준다).

    회귀 테스트처럼 운영자가 직접 돌리는 질의까지 일일 한도에 걸리면
    정작 점검이 막힌다. 한도 계산에서만 빼고 지표에는 그대로 기록한다.
    """
    if not ADMIN_TOKEN or not authorization:
        return False
    return secrets.compare_digest(authorization.encode(), f"Bearer {ADMIN_TOKEN}".encode())
