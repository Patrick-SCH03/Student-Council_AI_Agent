"""목업 모드 스모크 테스트: 벡터 스토어 + LangGraph 파이프라인 + 위험도 계산."""

import asyncio


async def main():
    from app.rag import store

    # 1) 벡터 스토어: 추가/검색/삭제
    # 실제 색인이 들어있는 환경에서도 돌 수 있도록 기준선 대비로 검증한다
    baseline = store.chunk_count()
    added = store.add_chunks("testdoc", "재정·회계 세칙.pdf", ["제10조 학생회비는 공식 활동에만 사용한다.", "제11조 회식비 집행은 금지한다."])
    assert added == 2, f"add_chunks 실패: {added}"
    assert store.chunk_count() == baseline + 2, "청크 수가 예상과 다름"
    hits = store.search("학생회비 회식비", k=2)
    assert hits and any(h["source_file"] == "재정·회계 세칙.pdf" for h in hits), f"search 실패: {hits}"
    print("[1/3] vector store OK:", [h["source_file"] for h in hits])

    # 2) 그래프 실행 (regulation 경로, 병렬 fan-out → join)
    from app.agents.graph import graph
    from app.agents.schemas import overall_risk

    state = await graph.ainvoke({"query": "학생회비로 회식비 사용이 가능한가요?", "citations": []})
    assert state["route"] == "regulation", state.get("route")
    assert state["reviewer"] is not None and state["auditor"] is not None
    assert state["final_markdown"], "final_markdown 비어 있음"
    risk = overall_risk(state["reviewer"], state["auditor"])
    print("[2/3] graph OK: route=regulation, risk =", risk.value, ", citations =", len(state["citations"]))

    # 3) general 경로
    state2 = await graph.ainvoke({"query": "오늘 날씨 어때?", "citations": []})
    assert state2["route"] == "general", state2.get("route")
    assert state2["final_markdown"]
    print("[3/3] general route OK")

    store.delete_doc("testdoc")
    assert store.chunk_count() == baseline, "delete_doc 실패"
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
