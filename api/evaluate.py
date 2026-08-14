"""답변 품질 회귀 테스트.

evalset.json의 질문을 실행해 라우팅·근거 문서·핵심 키워드·개인정보 보호를 검사한다.
프롬프트나 검색 설정을 바꾼 뒤 실행해 품질 저하를 조기에 발견하는 용도다.

사용법:
    python evaluate.py                              # 로컬 파이프라인 직접 호출
    python evaluate.py --url https://<배포주소>      # 배포 서버 대상
    python evaluate.py --case vat-case              # 특정 케이스만

주의: 실제 LLM을 호출하므로 비용이 발생한다 (전체 20건 기준 수백 원).
"""

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

EVALSET = Path(__file__).resolve().parent / "evalset.json"

# 색인 문서에 등장하는 실명 — 답변에 노출되면 안 된다.
KNOWN_NAMES = ["○○○", "○○○", "○○○", "○○○", "○○○"]


def _check(case: dict, result: dict) -> list[str]:
    """케이스별 기대치와 실제 응답을 비교해 실패 사유 목록을 반환한다."""
    failures: list[str] = []
    answer = result.get("final_markdown", "") or ""
    sources = " ".join(c["source_file"] for c in result.get("citations", []))
    blob = json.dumps(result, ensure_ascii=False)

    if (expected := case.get("expect_route")) and result.get("route") != expected:
        failures.append(f"라우팅 {result.get('route')} (기대 {expected})")

    # 기대 근거 문서는 하나라도 인용되면 통과 (질문에 따라 관련 문서가 여럿일 수 있음)
    if wanted := case.get("expect_sources"):
        if not any(w in sources for w in wanted):
            failures.append(f"근거 문서 미검색 (기대 {wanted[0]} 등)")

    for kw in case.get("expect_keywords", []):
        if kw not in answer:
            failures.append(f"키워드 '{kw}' 누락")

    if allowed := case.get("expect_risk"):
        if result.get("risk_level") not in allowed:
            failures.append(f"위험도 {result.get('risk_level')} (기대 {allowed})")

    if case.get("forbid_names"):
        if leaked := [n for n in KNOWN_NAMES if n in blob]:
            failures.append(f"실명 노출 {leaked}")

    if (cap := case.get("max_tokens")) and (tokens := result.get("_tokens")):
        if tokens > cap:
            failures.append(f"토큰 {tokens} > {cap} (범위 밖 질문에 과다 호출)")

    return failures


def _run_remote(url: str, query: str) -> dict:
    body = json.dumps({"query": query}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as res:
        for raw in res.read().decode("utf-8").splitlines():
            raw = raw.strip()
            if raw.startswith("data:"):
                event = json.loads(raw[5:])
                if event.get("type") == "result":
                    return event
    return {}


async def _run_local(query: str) -> dict:
    from langchain_core.callbacks import UsageMetadataCallbackHandler

    from app.agents.graph import content_to_text, graph
    from app.agents.schemas import overall_risk

    usage = UsageMetadataCallbackHandler()
    state = await graph.ainvoke(
        {"query": query, "history": [], "citations": []},
        config={"callbacks": [usage]},
    )
    reviewer, auditor = state.get("reviewer"), state.get("auditor")
    markdown = content_to_text(state.get("final_markdown", ""))
    return {
        "route": state.get("route", ""),
        "risk_level": overall_risk(reviewer, auditor).value if (reviewer or auditor) else None,
        "final_markdown": re.sub(r"<followups>.*?</followups>", "", markdown, flags=re.DOTALL),
        "citations": [
            {"source_file": c.source_file, "snippet": c.snippet}
            for c in state.get("citations", [])
        ],
        "reviewer": reviewer.model_dump() if reviewer else None,
        "auditor": auditor.model_dump() if auditor else None,
        "_tokens": sum(
            u.get("input_tokens", 0) + u.get("output_tokens", 0)
            for u in (usage.usage_metadata or {}).values()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="답변 품질 회귀 테스트")
    parser.add_argument("--url", help="배포 서버 주소 (생략 시 로컬 파이프라인 직접 실행)")
    parser.add_argument("--case", help="특정 케이스 id만 실행")
    args = parser.parse_args()

    cases = json.loads(EVALSET.read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"케이스를 찾을 수 없습니다: {args.case}")
            sys.exit(1)

    print(f"평가셋 {len(cases)}건 실행 ({'원격 ' + args.url if args.url else '로컬'})\n")
    passed, failed_cases = 0, []
    start_all = time.time()

    for i, case in enumerate(cases, 1):
        started = time.time()
        try:
            result = _run_remote(args.url, case["query"]) if args.url else asyncio.run(
                _run_local(case["query"])
            )
        except Exception as e:  # noqa: BLE001 - 한 건 실패가 전체를 멈추지 않도록
            print(f"[{i:2d}/{len(cases)}] ERROR {case['id']}: {type(e).__name__}: {e}")
            failed_cases.append((case["id"], [f"실행 실패: {e}"]))
            continue

        failures = _check(case, result)
        elapsed = time.time() - started
        if failures:
            failed_cases.append((case["id"], failures))
            print(f"[{i:2d}/{len(cases)}] FAIL  {case['id']} ({elapsed:.1f}s)")
            for f in failures:
                print(f"          - {f}")
        else:
            passed += 1
            print(f"[{i:2d}/{len(cases)}] PASS  {case['id']} ({elapsed:.1f}s)")

    total = len(cases)
    rate = passed / total * 100 if total else 0
    print(f"\n{'=' * 52}")
    print(f"통과 {passed}/{total} ({rate:.0f}%) · 소요 {time.time() - start_all:.0f}초")
    if failed_cases:
        print("\n실패 케이스:")
        for cid, reasons in failed_cases:
            print(f"  - {cid}: {'; '.join(reasons)}")
    sys.exit(1 if failed_cases else 0)


if __name__ == "__main__":
    main()
