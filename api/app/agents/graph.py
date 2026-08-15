"""LangGraph 1.0 멀티에이전트 파이프라인.

구조:
    router ─┬─(regulation)─> retrieve ─┬─> reviewer ─┐
            │                          └─> auditor  ─┴─> coordinator ─> END
            └─(general)───> general ─────────────────────────────────> END
    (reviewer/auditor 병렬 실행, 검색은 retrieve에서 한 번만)

v1 대비 개선:
- 규정 검토/감사 에이전트가 실제로 병렬 실행된다 (v1은 이름만 병렬).
- 위험도는 키워드 카운팅이 아니라 각 에이전트의 enum 필드에서 결정론적으로 계산.
- 라우팅도 문자열 비교가 아닌 구조화 출력.
- MOCK_MODE에서는 LLM 호출 없이 canned 응답으로 전체 플로우를 검증할 수 있다.
"""

import asyncio
import operator
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
from app.config import GEMINI_API_KEY, GEMINI_MODEL, MOCK_MODE
from app.rag import store

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
    # 검색 노드가 한 번만 채우고 두 에이전트가 나눠 쓴다
    reg_hits: list[dict]
    audit_brief: list[dict]
    audit_full: list[dict]
    reviewer: ReviewerResult | None
    auditor: AuditorResult | None
    # 병렬 노드가 동시에 기록하므로 리듀서 필요
    citations: Annotated[list[Citation], operator.add]
    final_markdown: str


_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        from langchain_google_genai import ChatGoogleGenerativeAI

        _llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL, google_api_key=GEMINI_API_KEY, temperature=0.1
        )
    return _llm


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

    if MOCK_MODE:
        keywords = ("학생회", "규정", "예산", "감사", "회계", "회비", "지원금", "선거")
        text = query + " ".join(h.get("question", "") for h in history)
        route = "regulation" if any(k in text for k in keywords) else "general"
        return {"route": route, "standalone_query": query}

    llm = _get_llm().with_structured_output(RouteDecision)
    decision: RouteDecision = await llm.ainvoke(
        [
            ("system", prompts.ROUTER_SYSTEM),
            ("user", prompts.ROUTER_USER.format(
                history=_format_history(history), query=query
            )),
        ]
    )
    route = decision.route if decision.route in ("regulation", "general") else "regulation"
    standalone = (decision.standalone_query or "").strip() or query
    return {"route": route, "standalone_query": standalone}


async def retrieve_node(state: AgentState) -> AgentState:
    """두 에이전트가 쓸 검색을 한 번에 수행한다.

    이전에는 검토·감사 노드가 같은 질의로 규정 검색을 각각 돌렸다. 평가셋
    8건으로 확인했을 때 결과가 전부 동일했는데도 임베딩 호출과 BM25 순회가
    그대로 중복됐다. 검색을 앞단으로 빼서 한 번만 계산한다.
    """
    query = state.get("standalone_query") or state["query"]
    reg_hits, audit_brief, audit_full = await asyncio.gather(
        asyncio.to_thread(store.search, query, K_REGULATION, "regulation"),
        # 검토 에이전트가 참고할 감사 선례 (실제 적용 사례 확인용)
        asyncio.to_thread(store.search, query, 2, "audit"),
        asyncio.to_thread(store.search, f"{query} 감사 처분 사례", K_AUDIT, "audit"),
    )
    # 한 사안에 대한 처분이 여러 건이면 보고서에 연속으로 나열된다.
    # 인접 청크를 붙여야 목록 일부만 답변되는 일을 막을 수 있다.
    audit_full = await asyncio.to_thread(
        store.expand_neighbors, audit_full, 1, NEIGHBOR_TOP_N
    )
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
    response = await _get_llm().ainvoke(
        [("system", prompts.COORDINATOR_SYSTEM), ("user", user_prompt)]
    )
    return {"final_markdown": content_to_text(response.content)}


OUT_OF_SCOPE_MESSAGE = """\
안녕하세요! 저는 **인하대학교 학생회 규정·재정·감사 전용 AI 어시스턴트**입니다.

질문해주신 내용은 학생회 업무 범위를 벗어나 답변드리기 어렵습니다. 아래와 같은 질문을 도와드릴 수 있어요:

- 학생회비·예산 집행이 규정에 맞는지 (예: "학생회비로 회식비 사용이 가능한가요?")
- 감사 기준과 처분 가능성 (예: "예산 초과 집행 시 어떤 처분을 받나요?")
- 회칙·세칙의 절차 확인 (예: "예산 변경 시 승인 절차는 무엇인가요?")"""


async def general_node(state: AgentState) -> AgentState:
    # 도메인 전용 챗봇이므로 범위 밖 질문은 LLM 호출 없이 고정 안내문으로 응답한다.
    # (오프토픽 답변 원천 차단 + 비용 절감)
    if MOCK_MODE:
        await asyncio.sleep(0.3)
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


# 서버 기동 시 1회 컴파일하여 재사용 (v1은 질의마다 재컴파일)
graph = build_graph()
