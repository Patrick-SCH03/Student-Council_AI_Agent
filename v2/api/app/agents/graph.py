"""LangGraph 1.0 멀티에이전트 파이프라인.

구조:
    router ─┬─(regulation)─> reviewer ─┐
            │              > auditor  ─┴─> coordinator ─> END   (reviewer/auditor 병렬)
            └─(general)───> general ──────────────────> END

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

RETRIEVAL_K = 5


class AgentState(TypedDict, total=False):
    query: str
    route: str
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

async def route_node(state: AgentState) -> AgentState:
    if MOCK_MODE:
        keywords = ("학생회", "규정", "예산", "감사", "회계", "회비", "지원금", "선거")
        route = "regulation" if any(k in state["query"] for k in keywords) else "general"
        return {"route": route}

    llm = _get_llm().with_structured_output(RouteDecision)
    decision: RouteDecision = await llm.ainvoke(
        [("system", prompts.ROUTER_SYSTEM), ("user", state["query"])]
    )
    route = decision.route if decision.route in ("regulation", "general") else "regulation"
    return {"route": route}


async def reviewer_node(state: AgentState) -> AgentState:
    hits = await asyncio.to_thread(store.search, state["query"], RETRIEVAL_K)

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
                query=state["query"], regulations=_format_hits(hits)
            )),
        ]
    )
    return {"reviewer": result, "citations": result.citations}


async def auditor_node(state: AgentState) -> AgentState:
    query = state["query"]
    reg_hits, audit_hits = await asyncio.gather(
        asyncio.to_thread(store.search, query, RETRIEVAL_K),
        asyncio.to_thread(store.search, f"{query} 감사 보고서 감사 처분 사례", RETRIEVAL_K),
    )

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
            "### 의견 조정\n두 에이전트의 판단이 일치합니다.\n\n"
            "### 최종 권고\n회식비 대신 공식 활동비 항목으로 집행하고, 사전에 감사위원회 서면 확인을 받으십시오.\n\n"
            "> ⚠️ GEMINI_API_KEY가 설정되지 않아 목업 모드로 동작 중입니다."
        )
        return {"final_markdown": markdown}

    user_prompt = prompts.COORDINATOR_USER.format(
        query=state["query"],
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


async def general_node(state: AgentState) -> AgentState:
    if MOCK_MODE:
        await asyncio.sleep(0.3)
        return {
            "final_markdown": (
                "(목업 응답) 일반 질문으로 분류되었습니다. "
                "학생회 규정·재정·감사 관련 질문을 하시면 문서 기반 정밀 분석을 제공합니다."
            )
        }
    response = await _get_llm().ainvoke(
        [("system", prompts.GENERAL_SYSTEM), ("user", state["query"])]
    )
    return {"final_markdown": content_to_text(response.content)}


# ---------------------------------------------------------------- 그래프 구성

def _route_fanout(state: AgentState):
    if state.get("route") == "general":
        return "general"
    # 리스트 반환 → 두 노드 병렬(fan-out) 실행
    return ["reviewer", "auditor"]


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("router", route_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("coordinator", coordinator_node)
    workflow.add_node("general", general_node)

    workflow.set_entry_point("router")
    workflow.add_conditional_edges(
        "router", _route_fanout, ["reviewer", "auditor", "general"]
    )
    # reviewer와 auditor가 모두 끝나야 coordinator 실행 (join)
    workflow.add_edge(["reviewer", "auditor"], "coordinator")
    workflow.add_edge("coordinator", END)
    workflow.add_edge("general", END)
    return workflow.compile()


# 서버 기동 시 1회 컴파일하여 재사용 (v1은 질의마다 재컴파일)
graph = build_graph()
