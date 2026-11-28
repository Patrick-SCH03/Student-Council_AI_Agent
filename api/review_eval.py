"""문서 검토 평가: 로컬 표본(review-samples/, git 제외)으로 검출률·오탐·속도·비용을 잰다.

라벨: review-samples/labels.json (expect = 꼭 잡을 검사, forbid = 나오면 오탐, stretch = 잡으면 가점)
비용: 문서당 추출 1회 + 메모 1회 (Haiku, 문서당 약 $0.002~0.005). --no-notes 로 메모를 빼면 절반.
실행: CLAUDE_EFFORT=low .venv/Scripts/python.exe review_eval.py [--no-notes] [--only 이름일부]
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app.config import MOCK_MODE  # noqa: E402
from app.review import service  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "review-samples"


def _codes(findings) -> set[str]:
    return {"note" if f.code.startswith("note:") else f.code for f in findings}


async def run_case(case: dict, with_notes: bool) -> dict:
    data = (SAMPLES / case["path"]).read_bytes()
    started = time.monotonic()
    result = await service.extract(case["filename"], data)
    t_extract = time.monotonic() - started
    findings = service.check(result.doc, service.source_findings(result.file))
    notes, usage_notes, t_notes = [], service.Usage(), 0.0
    if with_notes:
        t0 = time.monotonic()
        notes, usage_notes = await service.notes(result.doc, result.file.text, findings)
        t_notes = time.monotonic() - t0
    codes = _codes(findings) | _codes(notes)
    expect, forbid, stretch = set(case.get("expect", [])), set(case.get("forbid", [])), set(case.get("stretch", []))
    return {
        "name": Path(case["path"]).name,
        "method": result.method,
        "missed": sorted(expect - codes),
        "false": sorted(forbid & codes),
        "stretch_hit": sorted(stretch & codes),
        "findings": [(f.level, f.code, f.title) for f in findings],
        "notes": [(n.level, n.title, n.basis) for n in notes],
        "t_extract": t_extract,
        "t_notes": t_notes,
        "cost": result.usage.cost_usd + usage_notes.cost_usd,
        "expect": len(expect),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-notes", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    labels = json.loads((SAMPLES / "labels.json").read_text(encoding="utf-8"))["cases"]
    cases = [c for c in labels if args.only in c["path"]]
    print(f"모드: {'목업(규칙 기반)' if MOCK_MODE else '실제 모델'} · 문서 {len(cases)}건")
    rows = []
    for case in cases:
        r = await run_case(case, not args.no_notes)
        rows.append(r)
        flag = "OK " if not r["missed"] and not r["false"] else "!! "
        print(f"\n{flag}{r['name']} [{r['method']}] 추출 {r['t_extract']:.1f}s 메모 {r['t_notes']:.1f}s ${r['cost']:.4f}")
        if r["missed"]:
            print(f"   놓침: {r['missed']}")
        if r["false"]:
            print(f"   오탐: {r['false']}")
        if r["stretch_hit"]:
            print(f"   가점: {r['stretch_hit']}")
        for level, code, title in r["findings"]:
            print(f"   - [{level}] {code}: {title}")
        for level, title, basis in r["notes"]:
            print(f"   * [{level}] {title} {('— ' + basis) if basis else ''}")
    expect = sum(r["expect"] for r in rows)
    missed = sum(len(r["missed"]) for r in rows)
    false = sum(len(r["false"]) for r in rows)
    pdf = [r for r in rows if r["name"].endswith(".pdf")]
    print("\n== 요약")
    print(f"검출 {expect - missed}/{expect} · 오탐 {false}건 · 가점 {sum(len(r['stretch_hit']) for r in rows)}")
    if pdf:
        print(f"PDF 평균 추출 {sum(r['t_extract'] for r in pdf) / len(pdf):.1f}s · 메모 {sum(r['t_notes'] for r in pdf) / len(pdf):.1f}s")
    print(f"총비용 ${sum(r['cost'] for r in rows):.4f}")


if __name__ == "__main__":
    asyncio.run(main())
