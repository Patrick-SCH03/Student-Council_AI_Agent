"""Claude 호출: 질문 분류·규정 검토·감사 분석(구조화 출력), 종합 조정(스트리밍), 문서 OCR.

이 파일은 공식 anthropic SDK 호출만 담고, 언제 쓸지는 graph.py·ingest.py가 정한다.
종합 조정의 토큰과 각 호출의 사용량은 LangGraph custom 스트림으로 흘린다
(main.py가 stream_mode "custom"으로 받아 SSE·지표로 옮긴다).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from app.config import CLAUDE_API_KEY, CLAUDE_EFFORT, CLAUDE_MODEL, CLAUDE_TIMEOUT

# SDK는 타임아웃도 재시도한다. 상류가 멈추면 CLAUDE_TIMEOUT × 3회 안에 사용자에게 오류를 돌려준다.
CLAUDE_MAX_RETRIES = 2
# 문서 OCR은 업로드 때만 돌고 한 번에 수십 쪽을 읽어 질의보다 오래 걸린다
OCR_TIMEOUT = 600
# 50쪽 감사보고서 추출본이 3만 토큰을 넘는다 (Haiku 5.5 출력 상한 128K)
OCR_MAX_TOKENS = 64000

T = TypeVar("T", bound=BaseModel)

_client = None
_sync_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        # 재시도 대상은 SDK 기본(408·409·429·5xx·연결 오류·타임아웃), 횟수만 줄인다.
        _client = anthropic.AsyncAnthropic(
            api_key=CLAUDE_API_KEY, timeout=CLAUDE_TIMEOUT, max_retries=CLAUDE_MAX_RETRIES
        )
    return _client


def _writer() -> Callable[[dict], None]:
    """LangGraph custom 스트림 writer. 스트리밍이 아닌 실행(ainvoke·평가)에서는 아무것도 안 한다."""
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:  # noqa: BLE001 - 그래프 밖 호출(단위 테스트 등)
        return lambda _payload: None


def _report_usage(write: Callable[[dict], None], usage) -> None:
    write({"usage": {
        "provider": "claude",
        "model": CLAUDE_MODEL,
        # Claude의 input_tokens는 캐시 적중·캐시 쓰기 토큰을 뺀 값이라 합쳐서 넘긴다 (pricing.cost_usd 규약).
        # 캐시 쓰기는 정가의 1.25배지만 지금은 프롬프트 캐싱을 쓰지 않아 0이다 — 켜면 pricing에 단가를 더한다.
        "input_tokens": (usage.input_tokens or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "cached_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "output_tokens": usage.output_tokens or 0,
    }})


class ClaudeRefusal(RuntimeError):
    """안전 분류기가 응답을 거절했다 (stop_reason == "refusal")."""


class OcrTruncated(RuntimeError):
    """OCR 출력이 max_tokens에서 잘렸다. 같은 PDF로 다시 불러도 다시 잘리므로 재시도하지 않는다."""


async def structured(system: str, user: str, schema: type[T], max_tokens: int = 16000) -> T:
    """질문 분류·규정 검토·감사 분석: 스키마로 검증된 구조화 출력."""
    write = _writer()
    response = await _get_client().messages.parse(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": CLAUDE_EFFORT},
        output_format=schema,
    )
    _report_usage(write, response.usage)
    if response.stop_reason == "refusal":
        raise ClaudeRefusal(str(response.stop_details))
    if response.parsed_output is None:
        raise RuntimeError(f"구조화 출력 없음 (stop_reason={response.stop_reason})")
    return response.parsed_output


class StreamStarted(RuntimeError):
    """토큰을 일부 내보낸 뒤 실패했다. 다른 모델로 처음부터 다시 쓰면 답이 중복된다.

    partial에 이미 내보낸 텍스트를 담는다 — 호출 쪽이 요청 전체를 버리지 않고 완결할 수 있게.
    """

    def __init__(self, message: str, partial: str = ""):
        super().__init__(message)
        self.partial = partial


async def coordinate(system: str, user: str) -> str:
    """종합 조정: 토큰을 흘리며 생성하고 전체 텍스트를 돌려준다."""
    write = _writer()
    parts: list[str] = []
    stream = None
    try:
        async with _get_client().messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": CLAUDE_EFFORT},
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    parts.append(text)
                    write({"token": text})
            final = await stream.get_final_message()
    except Exception as e:
        # 끊기기 전까지 생성된 토큰도 과금된다 — 스냅샷에 남은 사용량을 보고한다.
        # 첫 이벤트 전에 끊기면 스냅샷 접근이 AssertionError를 내므로 원래 예외를 가리지 않게 삼킨다.
        # (출력 토큰은 끝 이벤트에서만 갱신돼 부분 보고는 사실상 입력 토큰만 — 비용 대부분이 입력이다)
        try:
            snapshot = stream.current_message_snapshot if stream is not None else None
        except Exception:  # noqa: BLE001
            snapshot = None
        if snapshot is not None and getattr(snapshot, "usage", None):
            _report_usage(write, snapshot.usage)
        if parts:
            raise StreamStarted(f"{type(e).__name__}: {e}", partial="".join(parts)) from e
        raise
    _report_usage(write, final.usage)
    if final.stop_reason == "refusal":
        if parts:
            raise StreamStarted("refusal after partial output", partial="".join(parts))
        raise ClaudeRefusal(str(final.stop_details))
    return "".join(parts)


def ocr_pdf(file_bytes: bytes, prompt: str) -> str:
    """PDF를 Claude에 문서로 넣어 텍스트를 추출한다 (스캔본·감사보고서 표 구조 보존용).

    업로드 경로는 동기 함수라 동기 클라이언트를 쓴다. 출력이 길어 스트리밍으로 받는다
    (긴 비스트리밍 요청은 SDK가 거부한다).
    """
    import base64

    global _sync_client
    if _sync_client is None:
        import anthropic

        _sync_client = anthropic.Anthropic(
            api_key=CLAUDE_API_KEY, timeout=OCR_TIMEOUT, max_retries=CLAUDE_MAX_RETRIES
        )
    document = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf",
                   "data": base64.standard_b64encode(file_bytes).decode()},
    }
    with _sync_client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=OCR_MAX_TOKENS,
        messages=[{"role": "user", "content": [document, {"type": "text", "text": prompt}]}],
        # 받아 적는 작업이라 깊은 사고가 필요 없다 — 사고 토큰은 출력 단가로 과금된다
        output_config={"effort": "low"},
    ) as stream:
        final = stream.get_final_message()
    usage = final.usage
    print(f"  Claude OCR 사용량: 입력 {usage.input_tokens:,} · 출력 {usage.output_tokens:,} 토큰")
    if final.stop_reason == "refusal":
        raise ClaudeRefusal(str(final.stop_details))
    if final.stop_reason == "max_tokens":
        # 잘린 추출본을 색인하면 문서 뒷부분이 통째로 빠진다 — 호출 쪽이 pypdf 결과로 대신하게 알린다
        raise OcrTruncated(f"OCR 출력이 {OCR_MAX_TOKENS:,}토큰 한도에서 잘렸다")
    return "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
