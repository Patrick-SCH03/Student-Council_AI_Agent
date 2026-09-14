"""LangGraph 1.0 멀티에이전트 파이프라인.

구조:
    router ─┬─(regulation)─> retrieve ─┬─> reviewer ─┐
            │                          └─> auditor  ─┴─> coordinator ─> END
            └─(general)───> general ─────────────────────────────────> END
    (reviewer/auditor 병렬 실행, 검색은 retrieve에서 한 번만)

라우팅과 각 에이전트의 판정은 구조화 출력으로 받아, 위험도를 코드에서 계산한다.
MOCK_MODE에서는 LLM 호출 없이 고정 응답으로 전체 플로우를 검증할 수 있다.
"""

import asyncio
import operator
import os
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph

from app.agents import prompts
from app.agents.schemas import (
    AuditorResult,
    Citation,
    ReviewerResult,
    RiskLevel,
    RouteDecision,
)
from app.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_ROUTER_MODEL,
    LLM_TIMEOUT,
    MOCK_MODE,
)
from app.privacy import find_private_name
from app.rag import citation_graph, store

# 코퍼스가 커지면서 상위 5개로는 규정 조항이 감사보고서에 밀려나므로,
# 유형별로 나눠 충분히 확보한다.
K_REGULATION = 6  # 회칙·세칙
K_AUDIT = 5  # 감사보고서(선례)
# 감사 에이전트는 감사보고서가 주 근거이고 규정은 판단 기준으로만 참고하므로
# 규정 컨텍스트를 검토 에이전트보다 좁게 준다 (토큰 절감).
K_AUDITOR_REGULATION = 3
# 인접 청크는 상위 몇 건만 확장한다. 하위 순위까지 늘리면 토큰만 불어난다.
NEIGHBOR_TOP_N = 3


class AgentState(TypedDict, total=False):
    query: str
    # 이전 대화 [{"question": ..., "answer": ...}] — 후속 질문 맥락 유지용
    history: list[dict]
    # 대화 맥락을 반영해 독립적으로 재작성된 질의 (검색·분석에 사용)
    standalone_query: str
    route: str
    # 입구에서 거절한 사유 (예: private_name). general 노드가 안내문을 고를 때 쓴다
    guard: str
    # 판례 집계형 질문 여부 (라우터 판별) — 인용 그래프 확장 게이트
    needs_precedents: bool
    # 검색 노드가 한 번만 채우고 두 에이전트가 나눠 쓴다
    reg_hits: list[dict]
    audit_brief: list[dict]
    audit_full: list[dict]
    reviewer: ReviewerResult | None
    auditor: AuditorResult | None
    # 병렬 노드가 동시에 기록하므로 리듀서 필요
    citations: Annotated[list[Citation], operator.add]
    final_markdown: str


_llm_cache: dict = {}


def _get_llm(model: str | None = None, thinking: str | None = None):
    """역할별 LLM 인스턴스 (같은 설정은 재사용).

    temperature는 지정하지 않는다. Gemini 3 공식 가이드가 기본값 1.0 유지를
    강력 권장하며(낮추면 루핑·품질 저하 위험), 사실성 제어는 temperature가
    아니라 thinking_level과 프롬프트의 근거 강제로 한다.

    thinking_level: 사고 토큰은 첫 응답 토큰 전에 생성되고 출력 단가로 과금된다.
    분류·요약 병합처럼 사실 처리에 가까운 역할은 'low'로 제한해 지연·비용을 줄인다.
    """
    key = (model or GEMINI_MODEL, thinking)
    if key not in _llm_cache:
        from langchain_google_genai import ChatGoogleGenerativeAI

        # 기본값(timeout 없음, 재시도 6회)은 상류가 느려질 때 요청을 몇 분씩 붙잡는다.
        kwargs: dict = {"timeout": LLM_TIMEOUT, "max_retries": 2}
        if thinking:
            kwargs["thinking_level"] = thinking
        _llm_cache[key] = ChatGoogleGenerativeAI(
            model=key[0], google_api_key=GEMINI_API_KEY, **kwargs
        )
    return _llm_cache[key]


def content_to_text(content) -> str:
    """LLM 응답 content 정규화. Gemini는 문자열 대신 블록 리스트를 반환할 수 있다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content)


# 인용문(snippet)은 원문 복사가 아니라 에이전트가 실명 금지 규칙 아래에서 쓴다.
# 번호 인용으로 출력 토큰을 아끼는 방안을 시도했으나, 코드가 원문을 그대로 옮기면
# 감사보고서 곳곳(명단·의결 의견·서명)의 실명이 근거 패널에 노출된다 — 평가셋
# forbid_names 검사에 걸려 되돌렸다. 질의당 1~3원 절감과 바꿀 수 있는 위험이 아니다.
def _format_hits(hits: list[dict]) -> str:
    if not hits:
        return "(검색된 규정이 없습니다. 문서가 색인되어 있는지 확인이 필요합니다.)"
    return "\n\n".join(
        f"--- 출처: {h['source_file']}\n{h['text']}" for h in hits
    )


# ---------------------------------------------------------------- 노드 정의

def _format_history(history: list[dict]) -> str:
    """이전 대화를 프롬프트용 텍스트로 변환. 없으면 빈 문자열."""
    if not history:
        return ""
    lines = ["**이전 대화:**"]
    for item in history[-3:]:
        lines.append(f"- 질문: {item.get('question', '')}")
        answer = (item.get("answer") or "")[:500]
        lines.append(f"  답변 요약: {answer}")
    return "\n".join(lines) + "\n\n"


async def route_node(state: AgentState) -> AgentState:
    query = state["query"]
    history = state.get("history") or []

    # 등록된 실명이 질문(또는 이전 질문)에 있으면 LLM을 부르지 않고 입구에서 거절한다.
    # 프롬프트 규칙·출력 마스킹은 답변 단계의 방어다. 이름으로 특정인의 처분을
    # 캐묻는 질문은 받지 않는 편이 맞고, 비용도 판단 여지도 0이다.
    if find_private_name(" ".join([query, *(h.get("question", "") for h in history)])):
        return {
            "route": "general",
            "guard": "private_name",
            "standalone_query": query,
            "needs_precedents": False,
        }

    if MOCK_MODE:
        keywords = ("학생회", "규정", "예산", "감사", "회계", "회비", "지원금", "선거")
        text = query + " ".join(h.get("question", "") for h in history)
        route = "regulation" if any(k in text for k in keywords) else "general"
        precedents = any(k in query for k in ("사례", "판례", "처분 내역", "이력"))
        return {"route": route, "standalone_query": query, "needs_precedents": precedents}

    # 분류 + 한 문장 재작성뿐이라 경량 모델로 충분하다 (단가 1/3, 첫 토큰 지연 최단)
    llm = _get_llm(GEMINI_ROUTER_MODEL).with_structured_output(RouteDecision)
    try:
        decision: RouteDecision = await llm.ainvoke(
            [
                ("system", prompts.ROUTER_SYSTEM),
                ("user", prompts.ROUTER_USER.format(
                    history=_format_history(history), query=query
                )),
            ]
        )
    except Exception as e:  # noqa: BLE001 - 라우터 실패가 전체 응답을 막지 않도록
        # 분류가 안 되면 규정 경로로 보낸다. 규정 질문을 잘라내는 것보다
        # 범위 밖 질문에 한 번 성실히 답하는 쪽이 덜 해롭다.
        print(f"라우터 호출 실패, regulation 경로로 폴백: {type(e).__name__}: {e}")
        return {"route": "regulation", "standalone_query": query, "needs_precedents": False}
    route = decision.route if decision.route in ("regulation", "general") else "regulation"
    standalone = (decision.standalone_query or "").strip() or query
    return {
        "route": route,
        "standalone_query": standalone,
        "needs_precedents": bool(decision.needs_precedents),
    }


async def retrieve_node(state: AgentState) -> AgentState:
    """두 에이전트가 쓸 검색을 한 번에 수행한다.

    검토·감사 노드가 각자 돌리면 같은 질의로 같은 규정 검색을 두 번 하게 되어,
    임베딩 호출과 BM25 순회가 그대로 중복된다.
    """
    query = state.get("standalone_query") or state["query"]
    # 같은 질의를 쓰는 두 검색이 각각 임베딩 API를 부르지 않도록 한 번만 임베딩한다.
    # (임베딩 호출 감소는 무료 티어 분당 쿼터 초과 확률도 함께 낮춘다)
    query_vec = await asyncio.to_thread(store.embed_query, query)
    reg_hits, audit_brief, audit_full = await asyncio.gather(
        asyncio.to_thread(
            store.search, query, K_REGULATION, "regulation", 3, query_vec
        ),
        # 검토 에이전트가 참고할 감사 선례 (실제 적용 사례 확인용)
        asyncio.to_thread(store.search, query, 2, "audit", 3, query_vec),
        # 접미사를 붙인 질의는 의도적으로 다른 벡터가 되므로 자체 임베딩을 유지한다
        asyncio.to_thread(store.search, f"{query} 감사 처분 사례", K_AUDIT, "audit"),
    )
    # 한 사안에 대한 처분이 여러 건이면 보고서에 연속으로 나열된다.
    # 인접 청크를 붙여야 목록 일부만 답변되는 일을 막을 수 있다.
    audit_full = await asyncio.to_thread(
        store.expand_neighbors, audit_full, 1, NEIGHBOR_TOP_N
    )

    # 인용 그래프 1-hop 확장 — 근거 조항의 판례를 문서 경계를 넘어 모은다.
    # 일반 질의에서도 게이트가 98% 열려 전역 상시 적용은 비용(+7원)·지연(+2초)
    # 회귀를 만들므로, 라우터가 '판례 집계형'으로 판별한 질의에만 켠다.
    # GRAPH_EXPANSION 환경변수는 강제 스위치: "1"=항상, "0"=차단(킬 스위치).
    # (호출 시점에 읽는다 — A/B 실행 중 토글할 수 있어야 한다)
    flag = os.getenv("GRAPH_EXPANSION", "")
    if flag == "1" or (flag != "0" and state.get("needs_precedents")):
        expanded = await asyncio.to_thread(citation_graph.expand, reg_hits + audit_full)
        for extra in expanded[len(reg_hits) + len(audit_full):]:
            (reg_hits if extra.get("doc_type") == "regulation" else audit_full).append(extra)

    return {"reg_hits": reg_hits, "audit_brief": audit_brief, "audit_full": audit_full}


async def reviewer_node(state: AgentState) -> AgentState:
    query = state.get("standalone_query") or state["query"]
    # 규정 검토는 회칙·세칙이 근거이므로 규정 문서를 우선 확보하고,
    # 감사 선례도 소수 포함해 실제 적용 사례를 참고한다.
    hits = state.get("reg_hits", []) + state.get("audit_brief", [])

    if MOCK_MODE:
        await asyncio.sleep(0.8)
        result = ReviewerResult(
            violation="위반 가능성 높음",
            risk_level=RiskLevel.HIGH,
            reasoning="(목업) 재정·회계 세칙 제10조에 따르면 학생회비는 공식 활동 목적으로만 집행할 수 있습니다.",
            recommendation="(목업) 회식비 대신 공식 행사 운영비 항목으로 집행하십시오.",
            citations=[
                Citation(source_file=h["source_file"], snippet=h["text"][:80]) for h in hits[:2]
            ]
            or [Citation(source_file="재정·회계 세칙(목업)", snippet="제10조 학생회비의 용도 제한")],
        )
        return {"reviewer": result, "citations": result.citations}

    llm = _get_llm().with_structured_output(ReviewerResult)
    result: ReviewerResult = await llm.ainvoke(
        [
            ("system", prompts.REVIEWER_SYSTEM),
            ("user", prompts.REVIEWER_USER.format(
                query=query, regulations=_format_hits(hits)
            )),
        ]
    )
    return {"reviewer": result, "citations": result.citations}


async def auditor_node(state: AgentState) -> AgentState:
    query = state.get("standalone_query") or state["query"]
    # 감사 분석은 감사보고서(선례)가 핵심이고, 판단 근거로 규정도 함께 본다.
    reg_hits = state.get("reg_hits", [])[:K_AUDITOR_REGULATION]
    audit_hits = state.get("audit_full", [])

    if MOCK_MODE:
        await asyncio.sleep(1.0)
        result = AuditorResult(
            compliance="위반 가능성 높음",
            sanction_likelihood=RiskLevel.HIGH,
            reasoning="(목업) 2024년 정기감사 보고서에서 유사 사례에 대한 경고 처분 기록이 확인됩니다.",
            recommendation="(목업) 집행 전 감사위원회에 사전 질의하여 서면 확인을 받으십시오.",
            citations=[
                Citation(source_file=h["source_file"], snippet=h["text"][:80])
                for h in audit_hits[:2]
            ]
            or [Citation(source_file="정기감사 보고서(목업)", snippet="회식비 집행 관련 경고 처분 사례")],
        )
        return {"auditor": result, "citations": result.citations}

    llm = _get_llm().with_structured_output(AuditorResult)
    result: AuditorResult = await llm.ainvoke(
        [
            ("system", prompts.AUDITOR_SYSTEM),
            ("user", prompts.AUDITOR_USER.format(
                query=query,
                regulations=_format_hits(reg_hits),
                audit_records=_format_hits(audit_hits),
            )),
        ]
    )
    return {"auditor": result, "citations": result.citations}


async def coordinator_node(state: AgentState) -> AgentState:
    reviewer = state.get("reviewer")
    auditor = state.get("auditor")

    if MOCK_MODE:
        await asyncio.sleep(0.5)
        markdown = (
            "### 핵심 요약\n(목업 응답) 규정 검토와 감사 분석 모두 위반 가능성이 높다고 판단했습니다.\n\n"
            "### 최종 권고\n회식비 대신 공식 활동비 항목으로 집행하고, 사전에 감사위원회 서면 확인을 받으십시오.\n\n"
            "> ⚠️ GEMINI_API_KEY가 설정되지 않아 목업 모드로 동작 중입니다.\n\n"
            "<followups>\n- 공식 활동비 항목은 어떻게 인준받나요?\n- 예산 초과 시 처분 수위는 어떻게 되나요?\n- 증빙서류는 무엇을 준비해야 하나요?\n</followups>"
        )
        return {"final_markdown": markdown}

    user_prompt = prompts.COORDINATOR_USER.format(
        query=state.get("standalone_query") or state["query"],
        violation=reviewer.violation if reviewer else "분석 실패",
        reviewer_risk=reviewer.risk_level.value if reviewer else "-",
        reviewer_reasoning=reviewer.reasoning if reviewer else "-",
        reviewer_recommendation=reviewer.recommendation if reviewer else "-",
        compliance=auditor.compliance if auditor else "분석 실패",
        sanction_likelihood=auditor.sanction_likelihood.value if auditor else "-",
        auditor_reasoning=auditor.reasoning if auditor else "-",
        auditor_recommendation=auditor.recommendation if auditor else "-",
    )
    # 조정은 이미 구조화된 두 분석을 병합하는 작업이라 깊은 사고가 필요 없다.
    # 사고 토큰은 첫 응답 토큰을 늦추고 출력 단가로 과금되므로 low로 제한한다.
    response = await _get_llm(thinking="low").ainvoke(
        [("system", prompts.COORDINATOR_SYSTEM), ("user", user_prompt)]
    )
    return {"final_markdown": content_to_text(response.content)}


OUT_OF_SCOPE_MESSAGE = """\
안녕하세요! 저는 **인하대학교 학생회 규정·재정·감사 전용 AI 어시스턴트**입니다.

질문해주신 내용은 학생회 업무 범위를 벗어나 답변드리기 어렵습니다. 아래와 같은 질문을 도와드릴 수 있어요:

- 학생회비·예산 집행이 규정에 맞는지 (예: "학생회비로 회식비 사용이 가능한가요?")
- 감사 기준과 처분 가능성 (예: "예산 초과 집행 시 어떤 처분을 받나요?")
- 회칙·세칙의 절차 확인 (예: "예산 변경 시 승인 절차는 무엇인가요?")"""

PERSON_QUERY_MESSAGE = """\
**개인 실명이 포함된 질문에는 답변드릴 수 없어요.**

감사보고서에 이름이 실려 있더라도, 이 서비스는 개인을 특정하는 질문에 답하지 않아요. 이름 대신 **직책이나 기구명**으로 물어봐 주세요.

- 예: "총학생회장이 받은 처분은 무엇인가요?"
- 예: "사회과학대학 학생회는 어떤 지적을 받았나요?"\n"""


async def general_node(state: AgentState) -> AgentState:
    # 도메인 전용 챗봇이므로 범위 밖 질문은 LLM 호출 없이 고정 안내문으로 응답한다.
    # (오프토픽 답변 원천 차단 + 비용 절감)
    if MOCK_MODE:
        await asyncio.sleep(0.3)
    if state.get("guard") == "private_name":
        return {"final_markdown": PERSON_QUERY_MESSAGE}
    return {"final_markdown": OUT_OF_SCOPE_MESSAGE}


# ---------------------------------------------------------------- 그래프 구성

def _route_fanout(state: AgentState):
    if state.get("route") == "general":
        return "general"
    return "retrieve"


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("router", route_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("coordinator", coordinator_node)
    workflow.add_node("general", general_node)

    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", _route_fanout, ["retrieve", "general"])
    # 검색 결과를 공유한 뒤 두 에이전트를 병렬 실행 (fan-out)
    workflow.add_edge("retrieve", "reviewer")
    workflow.add_edge("retrieve", "auditor")
    # reviewer와 auditor가 모두 끝나야 coordinator 실행 (join)
    workflow.add_edge(["reviewer", "auditor"], "coordinator")
    workflow.add_edge("coordinator", END)
    workflow.add_edge("general", END)
    return workflow.compile()


# 서버 기동 시 1회 컴파일해 재사용한다
graph = build_graph()
