"""LangGraph 1.0 멀티에이전트 파이프라인.

구조:
    router ─┬─(regulation)─> retrieve ─┬─> reviewer ─┐
            │                          └─> auditor  ─┴─> coordinator ─> END
            └─(general)───> general ─────────────────────────────────> END
    (reviewer/auditor 병렬 실행, 검색은 retrieve에서 한 번만)

모든 LLM 단계는 Claude(app/agents/claude_agents.py)가 맡는다. 라우팅과 각 에이전트의 판정은
구조화 출력으로 받아 위험도를 코드에서 계산한다. MOCK_MODE에서는 LLM 호출 없이 고정 응답으로
전체 플로우를 검증할 수 있다.
"""

import asyncio
import operator
import os
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph

from app.agents import claude_agents, prompts
from app.agents.schemas import (
    AuditorResult,
    Citation,
    ReviewerResult,
    RiskLevel,
    RouteDecision,
)
from app.config import MOCK_MODE
from app.privacy import find_private_name, mask_text
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
    # 종합 조정이 중간에 끊겨 받은 데까지만 담았다 — 캐시하지 않고 지표에 따로 남긴다
    partial: bool


def _report_fallback(stage: str) -> None:
    """요청이 낮춘 경로로 이어졌음을 지표에 남긴다 (로그만 남기면 대시보드엔 정상으로 보인다)."""
    claude_agents._writer()({"fallback": stage})


# 인용문(snippet)은 원문 복사가 아니라 에이전트가 실명 금지 규칙 아래에서 쓴다.
# 번호 인용으로 출력 토큰을 아끼는 방안을 시도했으나, 코드가 원문을 그대로 옮기면
# 감사보고서 곳곳(명단·의결 의견·서명)의 실명이 근거 패널에 노출된다 — 평가셋
# forbid_names 검사에 걸려 되돌렸다. 질의당 1~3원 절감과 바꿀 수 있는 위험이 아니다.
def _format_hits(hits: list[dict]) -> str:
    """검색 결과를 문서 태그로 감싼다 — Claude는 긴 근거를 XML 태그로 구분할 때 출처를 덜 섞는다."""
    if not hits:
        return "<documents>(검색된 문서가 없습니다. 문서가 색인되어 있는지 확인이 필요합니다.)</documents>"
    body = "\n".join(
        f"<document index=\"{i}\">\n<source>{h['source_file']}</source>\n<content>\n{h['text']}\n</content>\n</document>"
        for i, h in enumerate(hits, 1)
    )
    return f"<documents>\n{body}\n</documents>"


# ---------------------------------------------------------------- 노드 정의

def _format_history(history: list[dict]) -> str:
    """이전 대화를 프롬프트용 텍스트로 변환. 없으면 빈 문자열."""
    if not history:
        return ""
    lines = ["<history>"]
    for item in history[-3:]:
        # 이력은 클라이언트가 보내는 값이다. 거절된 이전 질문의 이름이 여기 남아 있으므로
        # 마스킹해서 넣는다 — 라우터(LLM)에도 실명이 닿지 않게.
        lines.append(f"- 질문: {mask_text(item.get('question', ''))}")
        answer = mask_text((item.get("answer") or "")[:500])
        lines.append(f"  답변 요약: {answer}")
    lines.append("</history>")
    return "\n".join(lines) + "\n\n"


def _fallback_query(query: str, history: list[dict]) -> str:
    """라우터 재작성이 실패했을 때 판정 에이전트에 넘길 질의.

    판정 에이전트는 대화 이력을 받지 않고 이 질의만 본다. 후속 질문("증빙은 뭐가 필요해?")을
    맥락 없이 넘기면, 앞 턴에서 설명한 위반 행위가 빠진 채 '절차 문의'로 판정된다.
    직전 질문을 마스킹해 붙여 최소한의 맥락을 지킨다.
    """
    if not history:
        return query
    previous = mask_text(history[-1].get("question", "")).strip()
    return f"(이전 질문: {previous}) {query}" if previous else query


def _refuse_private_name(query: str) -> AgentState:
    return {
        "route": "general",
        "guard": "private_name",
        "standalone_query": query,
        "needs_precedents": False,
    }


async def route_node(state: AgentState) -> AgentState:
    query = state["query"]
    history = state.get("history") or []

    # 등록된 실명이 질문에 있으면 LLM을 부르지 않고 입구에서 거절한다.
    # 프롬프트 규칙·출력 마스킹은 답변 단계의 방어다. 이름으로 특정인의 처분을
    # 캐묻는 질문은 받지 않는 편이 맞고, 비용도 판단 여지도 0이다.
    #
    # 검사 범위: 현재 질문 + 이력의 '답변'. 이전 '질문'은 보지 않는다 — 거절된 턴의
    # 질문에 이름이 남아 있어, 안내대로 직책으로 고쳐 물어도 또 거절되기 때문이다.
    # 답변은 서버가 만든 것이라 실명이 있을 수 없으므로, 있으면 클라이언트가 위조한 것이다.
    # 이력의 이름이 라우터 재작성을 타고 들어오는 경로는 아래 standalone_query 검사가 막는다.
    if find_private_name(query) or any(find_private_name(h.get("answer", "")) for h in history):
        return _refuse_private_name(query)

    if MOCK_MODE:
        keywords = ("학생회", "규정", "예산", "감사", "회계", "회비", "지원금", "선거")
        text = query + " ".join(h.get("question", "") for h in history)
        route = "regulation" if any(k in text for k in keywords) else "general"
        precedents = any(k in query for k in ("사례", "판례", "처분 내역", "이력"))
        return {"route": route, "standalone_query": query, "needs_precedents": precedents}

    user = prompts.ROUTER_USER.format(history=_format_history(history), query=query)
    try:
        # 분류 + 한 문장 재작성뿐이라 출력이 짧다 — max_tokens를 낮게 둬 지연 상한을 묶는다
        decision: RouteDecision = await claude_agents.structured(
            prompts.ROUTER_SYSTEM, user, RouteDecision, max_tokens=1024
        )
    except Exception as e:  # noqa: BLE001 - 라우터 실패가 전체 응답을 막지 않도록
        # 분류가 안 되면 규정 경로로 보낸다. 규정 질문을 잘라내는 것보다
        # 범위 밖 질문에 한 번 성실히 답하는 쪽이 덜 해롭다.
        print(f"라우터 호출 실패, regulation 경로로 폴백: {type(e).__name__}: {mask_text(str(e))[:200]}")
        _report_fallback("router_failed")
        return {
            "route": "regulation",
            "standalone_query": _fallback_query(query, history),
            "needs_precedents": False,
        }
    route = decision.route if decision.route in ("regulation", "general") else "regulation"
    standalone = (decision.standalone_query or "").strip() or _fallback_query(query, history)
    # 재작성이 이력에서 이름을 끌어왔으면("그 사람의 처분은?" → "○○○의 처분") 여기서 막는다
    if find_private_name(standalone):
        return _refuse_private_name(query)
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
    try:
        query_vec = await asyncio.to_thread(store.embed_query, query)
        keyword_only = False
    except Exception as e:  # noqa: BLE001 - 임베딩 장애에도 키워드 검색으로 답한다
        # 2026-10-24 임베딩 API가 막히자 답변까지 전부 실패했다. 키워드(BM25)만으로도
        # 조항 번호·용어가 맞는 근거는 찾으므로, 응답을 멈추기보다 낮춰서 이어간다.
        print(f"질의 임베딩 실패, 키워드 검색만으로 진행: {type(e).__name__}: {mask_text(str(e))[:200]}")
        _report_fallback("retrieve")
        query_vec, keyword_only = None, True
    reg_hits, audit_brief, audit_full = await asyncio.gather(
        asyncio.to_thread(
            store.search, query, K_REGULATION, "regulation", 3, query_vec, keyword_only
        ),
        # 검토 에이전트가 참고할 감사 선례 (실제 적용 사례 확인용)
        asyncio.to_thread(store.search, query, 2, "audit", 3, query_vec, keyword_only),
        # 접미사는 키워드 검색 쪽에만 붙는다 — 벡터는 같은 질의 임베딩을 재사용해 질의당 임베딩 호출을 1회로 묶는다
        # (Voyage 무료 한도가 분당 3요청이라, 호출을 2회로 두면 동시 질문 하나에도 한도를 넘는다)
        asyncio.to_thread(
            store.search, f"{query} 감사 처분 사례", K_AUDIT, "audit", 3, query_vec, keyword_only
        ),
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
        try:
            expanded = await asyncio.to_thread(citation_graph.expand, reg_hits + audit_full)
        except Exception as e:  # noqa: BLE001 - 판례 확장은 보강일 뿐, 실패해도 기본 검색으로 답한다
            print(f"인용 그래프 확장 실패, 확장 없이 진행: {type(e).__name__}: {e}")
            expanded = []
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

    user = prompts.REVIEWER_USER.format(query=query, regulations=_format_hits(hits))
    result: ReviewerResult = await claude_agents.structured(prompts.REVIEWER_SYSTEM, user, ReviewerResult)
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

    user = prompts.AUDITOR_USER.format(
        query=query,
        regulations=_format_hits(reg_hits),
        audit_records=_format_hits(audit_hits),
    )
    result: AuditorResult = await claude_agents.structured(prompts.AUDITOR_SYSTEM, user, AuditorResult)
    return {"auditor": result, "citations": result.citations}


async def coordinator_node(state: AgentState) -> AgentState:
    reviewer = state.get("reviewer")
    auditor = state.get("auditor")

    if MOCK_MODE:
        await asyncio.sleep(0.5)
        markdown = (
            "### 핵심 요약\n(목업 응답) 규정 검토와 감사 분석 모두 위반 가능성이 높다고 판단했습니다.\n\n"
            "### 최종 권고\n회식비 대신 공식 활동비 항목으로 집행하고, 사전에 감사위원회 서면 확인을 받으십시오.\n\n"
            "> ⚠️ CLAUDE_API_KEY·VOYAGE_API_KEY가 설정되지 않아 목업 모드로 동작 중입니다.\n\n"
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
    try:
        markdown = await claude_agents.coordinate(prompts.COORDINATOR_SYSTEM, user_prompt)
    except claude_agents.StreamStarted as e:
        # 이미 화면에 나간 글을 지우고 다시 쓸 수는 없다. 받은 데까지에 안내를 붙여 끝내고,
        # 두 분석·근거·위험도는 그대로 결과로 보낸다 (요청 전체를 오류로 버리지 않는다).
        print(f"Claude 종합 조정이 중간에 끊김: {e}")
        # 후속 질문 블록 도중에 끊기면 닫는 태그가 없어 화면이 안내문까지 잘라 버린다 — 블록 앞에서 자른다
        body = e.partial.split("<followups>")[0].rstrip()
        return {"final_markdown": body + PARTIAL_ANSWER_NOTICE, "partial": True}
    return {"final_markdown": markdown}


PARTIAL_ANSWER_NOTICE = (
    "\n\n> 답변을 만드는 중에 연결이 끊겨 여기까지만 보여드려요. "
    "아래 규정 검토·감사 분석 내용을 참고하시고, 필요하면 다시 질문해 주세요."
)

OUT_OF_SCOPE_MESSAGE = """\
안녕하세요! 저는 **인하대학교 학생회 규정·재정·감사 전용 AI 어시스턴트**예요.

질문하신 내용은 학생회 업무 범위를 벗어나 답변드리기 어려워요. 아래와 같은 질문을 도와드릴 수 있어요:

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
