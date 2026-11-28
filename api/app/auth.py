"""학교 계정 로그인 (v3). 문서 검토·법령 점검표·작업함이 쓰고, 규정 질문은 익명으로 남는다.

흐름: 브라우저가 Google Identity Services로 받은 ID 토큰을 POST /api/auth/google 로 보낸다 →
서버가 서명·aud·iss·만료·이메일 확인·학교 도메인을 직접 검증한다(클라이언트의 hd 힌트는 보안이 아니다) →
불투명 세션 토큰을 httpOnly 쿠키로 내려주고, DB에는 그 해시만 둔다.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import db
from app.config import (
    ADMIN_EMAILS,
    AUTH_EMAIL_DOMAIN,
    CORS_ORIGINS,
    GOOGLE_CLIENT_ID,
    SESSION_COOKIE,
    SESSION_TTL_DAYS,
)

def check_origin(request: Request) -> None:
    """쿠키로 인증하는 상태 변경 요청은 허용한 화면 주소에서 온 것만 받는다 (CSRF 방어).

    SameSite=Lax만으로는 같은 사이트의 다른 하위 도메인에서 오는 요청을 막지 못한다.
    """
    origin = request.headers.get("origin")
    if not origin or origin not in CORS_ORIGINS:
        raise HTTPException(status_code=403, detail="허용되지 않은 요청이에요.")


SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def origin_guard(request: Request) -> None:
    """로그인(쿠키) 라우터에 거는 의존성: 읽기 외 모든 요청의 Origin을 본다.

    경로마다 check_origin을 부르던 방식은 새 경로에서 빠뜨리기 쉬웠다 — 라우터에 한 번 걸면 새 경로도 자동으로 검사된다.
    """
    if request.method not in SAFE_METHODS:
        check_origin(request)


router = APIRouter(prefix="/api/auth", dependencies=[Depends(origin_guard)])  # 로그인·로그아웃도 Origin 검사

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
_jwks: jwt.PyJWKClient | None = None


class AuthError(Exception):
    """토큰을 받지 않는 이유 (사용자에게 그대로 보여 줄 수 있는 문구)."""


class AuthUnavailable(Exception):
    """Google 공개키를 받지 못해 지금은 검증할 수 없다 — 토큰 탓이 아니니 401이 아니라 503."""


def _google_signing_key(token: str):
    """토큰 헤더의 kid로 Google 공개키를 찾는다. 키 목록은 PyJWKClient가 캐시한다."""
    global _jwks
    if _jwks is None:
        # 키 목록 캐시만 쓰고(1시간 만료) 개별 키 캐시는 끈다 — 개별 키 캐시는 시간 만료가 없어
        # Google이 폐기한 키를 프로세스가 살아 있는 동안 계속 믿게 된다. 모르는 kid면 목록을 다시 받는다.
        _jwks = jwt.PyJWKClient(_GOOGLE_CERTS, cache_keys=False, cache_jwk_set=True, lifespan=3600, timeout=10)
    try:
        return _jwks.get_signing_key_from_jwt(token).key
    except jwt.PyJWKClientConnectionError as e:
        raise AuthUnavailable from e


def verify_google_token(
    token: str,
    *,
    client_id: str | None = None,
    domain: str | None = None,
    key_resolver: Callable[[str], object] | None = None,
) -> dict:
    """ID 토큰을 검증하고 {sub, email, name}을 돌려준다. 받지 않으면 AuthError, Google 장애면 AuthUnavailable.

    key_resolver는 테스트가 가짜 키를 주입하는 자리다 (운영은 Google 공개키).
    """
    client_id = client_id or GOOGLE_CLIENT_ID
    domain = (domain or AUTH_EMAIL_DOMAIN).lower()
    if not client_id:
        raise AuthError("로그인이 아직 설정되지 않았어요.")
    try:
        key = (key_resolver or _google_signing_key)(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=client_id,
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("로그인 정보가 만료됐어요. 다시 로그인해 주세요.") from e
    except (jwt.PyJWTError, ValueError) as e:
        raise AuthError("로그인 정보를 확인하지 못했어요. 다시 로그인해 주세요.") from e
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise AuthError("로그인 정보를 확인하지 못했어요. 다시 로그인해 주세요.")
    email = str(claims.get("email") or "").strip().lower()
    if claims.get("email_verified") is not True or not email:
        raise AuthError("확인된 이메일이 있는 계정으로 로그인해 주세요.")
    # hd(Workspace 도메인)와 이메일 끝을 둘 다 본다 — 개인 Gmail은 hd가 없다
    if str(claims.get("hd") or "").lower() != domain or not email.endswith(f"@{domain}"):
        raise AuthError(f"인하대학교 메일(@{domain}) 계정으로 로그인해 주세요.")
    name = str(claims.get("name") or "").strip()[:60] or None
    return {"sub": str(claims["sub"]), "email": email, "name": name}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session_token(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    return token if token and 20 <= len(token) <= 200 else None


def _role_of(email: str) -> str:
    return "admin" if email in ADMIN_EMAILS else "member"


def optional_user(request: Request) -> dict | None:
    token = _session_token(request)
    user = db.get_session_user(_hash(token)) if token else None
    # 역할은 매 요청 ADMIN_EMAILS로 정한다 — 환경변수를 바꾸면 다시 로그인하지 않아도 바로 반영(추가·해제 모두)
    return {**user, "role": _role_of(user["email"])} if user else None


def current_user(request: Request) -> dict:
    user = optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요해요.")
    return user


def require_role(*roles: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="이 기능을 쓸 권한이 없어요.")
        return user

    return dep


def _public(user: dict) -> dict:
    return {"email": user["email"], "name": user["name"], "role": user["role"]}


def _set_cookie(response: Response, token: str | None) -> None:
    if token is None:
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_DAYS * 86400,
        path="/",
        secure=True,  # localhost도 보안 출처라 개발 중에도 동작한다
        httponly=True,
        samesite="lax",
    )


class GoogleLogin(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)


@router.post("/google")
def login_google(body: GoogleLogin, request: Request, response: Response) -> dict:
    # 동기 함수: Google 공개키 조회(네트워크)가 이벤트 루프를 막지 않도록 스레드에서 돈다
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="로그인이 아직 설정되지 않았어요.")
    try:
        info = verify_google_token(body.credential)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except AuthUnavailable as e:
        raise HTTPException(status_code=503, detail="Google 로그인 확인이 잠시 안 돼요. 조금 뒤에 다시 시도해 주세요.") from e
    if db.is_blocked(info["sub"]):  # 막힌 계정은 로그인 기록(최근 로그인 시각)도 바꾸지 않는다
        raise HTTPException(status_code=403, detail="이용이 제한된 계정이에요. 사이드바의 '오류 신고·문의'로 알려 주세요.")
    user = db.upsert_user(info["sub"], info["email"], info["name"], _role_of(info["email"]))
    # 이전 세션이 있으면 폐기하고 새로 발급한다 (세션 고정 방지)
    old = _session_token(request)
    if old:
        db.revoke_session(_hash(old))
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    db.create_session(_hash(token), user["id"], expires.isoformat())
    _set_cookie(response, token)
    return {"user": _public(user)}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"user": _public(user)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = _session_token(request)
    if token:
        db.revoke_session(_hash(token))
    _set_cookie(response, None)
    return {"ok": True}
