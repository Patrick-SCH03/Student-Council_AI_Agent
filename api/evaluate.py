"""답변 품질 회귀 테스트.

evalset.json의 질문을 실행해 라우팅·근거 문서·핵심 키워드·개인정보 보호를 검사한다.
프롬프트나 검색 설정을 바꾼 뒤 실행해 품질 저하를 조기에 발견하는 용도다.

사용법:
    python evaluate.py                              # 로컬 파이프라인 직접 호출
    python evaluate.py --url https://<배포주소>      # 배포 서버 대상
    python evaluate.py --case vat-case              # 특정 케이스만
    python evaluate.py --retrieval                  # 검색 단계만 (LLM 미호출)

주의: --retrieval을 제외하면 실제 LLM을 호출하므로 비용이 발생한다.
검색 설정만 바꿨다면 --retrieval로 먼저 확인하는 편이 빠르고 싸다.
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
    headers = {"Content-Type": "application/json"}
    # 관리자 토큰을 실으면 일일 한도에서 제외된다 (평가 자체가 한도에 막히지 않도록)
    from app.config import ADMIN_TOKEN

    if ADMIN_TOKEN:
        headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"
    req = urllib.request.Request(f"{url.rstrip('/')}/api/chat", data=body, headers=headers)
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


def _run_retrieval(cases: list[dict]) -> int:
    """LLM 없이 검색 단계만 평가한다 (임베딩 비용만 발생).

    답변 품질 평가는 LLM 응답이 섞여 검색 변경의 효과가 묻힌다.
    """
    from app.agents.graph import K_AUDIT, K_REGULATION, NEIGHBOR_TOP_N
    from app.rag import store

    scored = [c for c in cases if c.get("expect_sources")]
    if not scored:
        print("expect_sources가 있는 케이스가 없습니다.")
        return 1

    print(f"검색 평가 {len(scored)}건 (LLM 미호출)\n")
    hits, top3, unique_counts, ranks = 0, 0, [], []
    misses: list[str] = []

    for i, case in enumerate(scored, 1):
        query = case["query"]
        # 실제 파이프라인과 같은 조합으로 검색한다
        found = store.search(query, K_REGULATION, "regulation") + store.expand_neighbors(
            store.search(f"{query} 감사 처분 사례", K_AUDIT, "audit"), 1, NEIGHBOR_TOP_N
        )
        sources = [h["source_file"] for h in found]
        # 적중률은 후보를 넉넉히 보면 쉽게 100%가 되어 변화를 감지하지 못한다.
        # 기대 문서가 몇 번째로 나오는지를 함께 본다.
        rank = next(
            (r for r, s in enumerate(sources, 1) if any(w in s for w in case["expect_sources"])),
            None,
        )
        unique_counts.append(len(set(sources)))
        if rank:
            hits += 1
            ranks.append(rank)
            top3 += rank <= 3
        else:
            misses.append(f"{case['id']}: 기대 {case['expect_sources'][0]}")
        label = f"{rank}위" if rank else "미검색"
        print(f"[{i:2d}/{len(scored)}] {'HIT ' if rank else 'MISS'} {case['id']:<26} {label:>6}")

    n = len(scored)
    # MRR: 기대 문서가 상위에 올수록 1에 가깝다. 상한이 없어 포화되지 않는다.
    mrr = sum(1 / r for r in ranks) / n if n else 0
    print(f"\n{'=' * 52}")
    print(f"적중률   {hits}/{n} ({hits / n * 100:.0f}%)")
    print(f"상위 3위 {top3}/{n} ({top3 / n * 100:.0f}%)")
    print(f"MRR      {mrr:.3f}   (기대 문서 평균 순위 {sum(ranks) / len(ranks):.2f}위)" if ranks else "")
    print(f"평균 근거 문서 {sum(unique_counts) / n:.2f}종")
    if misses:
        print("\n미검색:")
        for m in misses:
            print(f"  - {m}")
    return 1 if misses else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="답변 품질 회귀 테스트")
    parser.add_argument("--url", help="배포 서버 주소 (생략 시 로컬 파이프라인 직접 실행)")
    parser.add_argument("--case", help="특정 케이스 id만 실행")
    parser.add_argument(
        "--retrieval", action="store_true",
        help="LLM 없이 검색 단계만 평가 (로컬 색인 대상, 비용 거의 없음)",
    )
    args = parser.parse_args()

    cases = json.loads(EVALSET.read_text(encoding="utf-8"))["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"케이스를 찾을 수 없습니다: {args.case}")
            sys.exit(1)

    if args.retrieval:
        sys.exit(_run_retrieval(cases))

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
