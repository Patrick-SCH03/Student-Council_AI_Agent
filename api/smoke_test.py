"""목업 모드 스모크 테스트: 벡터 스토어 + LangGraph 파이프라인 + 위험도 계산."""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 실명 목록은 저장소에 없다. 입구 거절은 더미 이름으로 검증한다 (app 모듈 import 전에 설정).
os.environ.setdefault("PRIVATE_NAMES", "홍길동")


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
    print("[1/4] vector store OK:", [h["source_file"] for h in hits])

    # 2) 그래프 실행 (regulation 경로, 병렬 fan-out → join)
    from app.agents.graph import graph
    from app.agents.schemas import overall_risk

    state = await graph.ainvoke({"query": "학생회비로 회식비 사용이 가능한가요?", "citations": []})
    assert state["route"] == "regulation", state.get("route")
    assert state["reviewer"] is not None and state["auditor"] is not None
    assert state["final_markdown"], "final_markdown 비어 있음"
    risk = overall_risk(state["reviewer"], state["auditor"])
    print("[2/4] graph OK: route=regulation, risk =", risk.value, ", citations =", len(state["citations"]))

    # 3) general 경로
    state2 = await graph.ainvoke({"query": "오늘 날씨 어때?", "citations": []})
    assert state2["route"] == "general", state2.get("route")
    assert state2["final_markdown"]
    print("[3/4] general route OK")

    # 4) 실명이 든 질문은 라우터·LLM 없이 입구에서 거절
    state3 = await graph.ainvoke({"query": "홍길동 학생회장이 감사에서 받은 처분 알려줘", "citations": []})
    assert state3["route"] == "general" and state3.get("guard") == "private_name", state3
    assert "실명" in state3["final_markdown"], state3["final_markdown"][:80]
    print("[4/4] private-name guard OK")

    store.delete_doc("testdoc")
    assert store.chunk_count() == baseline, "delete_doc 실패"


def _run_child():
    try:
        from app import config

        if config.MOCK_MODE is not True:
            raise RuntimeError("smoke test refused to run: MOCK_MODE is not True")
        print("MOCK_MODE=True; isolated DATA_DIR:", config.DATA_DIR)
        asyncio.run(main())
    finally:
        store_module = sys.modules.get("app.rag.store")
        chroma_client = getattr(store_module, "_client", None)
        if chroma_client is not None:
            chroma_client.close()


def _run_isolated():
    scratch = tempfile.TemporaryDirectory(prefix="smoke-test-")
    child_env = os.environ.copy()
    child_env.update(GEMINI_API_KEY="", GOOGLE_API_KEY="", DATA_DIR=scratch.name)

    try:
        result = subprocess.run(
            [sys.executable, "-c", "from smoke_test import _run_child; _run_child()"],
            cwd=Path(__file__).resolve().parent,
            env=child_env,
        )
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    finally:
        scratch.cleanup()
        if os.path.exists(scratch.name):
            raise RuntimeError(f"smoke test DATA_DIR was not removed: {scratch.name}")
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    _run_isolated()
