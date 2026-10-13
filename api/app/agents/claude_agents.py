"""Claude로 도는 규정 검토·감사 분석·종합 조정 (AGENT_PROVIDER=claude일 때).

프롬프트·출력 스키마는 Gemini 경로와 같다 — 바뀌는 것은 모델뿐이다. 이 파일은 공식
anthropic SDK 호출만 담고, 언제 쓸지(디스패치·폴백)는 graph.py가 정한다.

LangChain 모델이 아니라서 LangGraph의 "messages" 스트림에 토큰이 잡히지 않는다.
그래서 종합 조정의 토큰과 각 호출의 사용량을 LangGraph custom 스트림으로 직접 흘린다
(main.py가 stream_mode "custom"으로 받는다).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from app.config import CLAUDE_API_KEY, CLAUDE_EFFORT, CLAUDE_MODEL, CLAUDE_TIMEOUT

# SDK는 타임아웃도 재시도한다. Gemini 폴백이 가용성 장치로 동작하려면 Claude 쪽 대기는 짧아야 한다.
# 상류가 멈추면 CLAUDE_TIMEOUT × 2회 안에 Gemini로 넘어간다.
CLAUDE_MAX_RETRIES = 1

T = TypeVar("T", bound=BaseModel)

_client = None


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
        # Claude의 input_tokens는 캐시 적중분을 뺀 값이라 합쳐서 넘긴다 (pricing.cost_usd 규약)
        "input_tokens": (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0),
        "cached_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "output_tokens": usage.output_tokens or 0,
    }})


class ClaudeRefusal(RuntimeError):
    """안전 분류기가 응답을 거절했다 (stop_reason == "refusal")."""


async def structured(system: str, user: str, schema: type[T]) -> T:
    """규정 검토·감사 분석: 스키마로 검증된 구조화 출력."""
    write = _writer()
    response = await _get_client().messages.parse(
        model=CLAUDE_MODEL,
        max_tokens=16000,
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
