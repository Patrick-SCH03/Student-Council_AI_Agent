"""규정 인용 그래프: 조항 참조를 결정론적으로 추출해 검색을 1-hop 확장한다.

법령류 문서의 참조 표기는 극도로 정형적이라 LLM 없이 정규식으로 그래프를
만들 수 있다 (색인 비용 0원, 재구축 1초 미만 — 색인할 때마다 전체 재생성하므로
LLM 추출 그래프의 '부패' 문제가 없다).

엣지 두 종류:
- cites: 감사보고서 청크 → 근거 조항  ("「재정·회계 세칙」 제32조 위반")
- refers: 규정 청크 → 다른 조항       ("제29조에 따라", 「다른 세칙」 제N조)

검색 확장은 게이트형이다: 검색된 청크에 실제 참조가 있을 때만,
그 엣지를 따라 근거 조항(정방향)과 인용 판례(역방향)를 상한 내에서 더한다.
"""

import json
import re
from collections import defaultdict

import networkx as nx

from app.config import DATA_DIR

GRAPH_PATH = DATA_DIR / "citation_graph.json"

# 규정 청크의 문서 간 참조: 「문서명」 제N조 (규정은 격식 표기가 일관적)
_CROSS = re.compile(
    r"[「『]([^」』]{2,25}?)[」』]\s*(?:中\s*)?제?\s*(\d+)\s*조(?:의\s*(\d+))?"
)
# 감사보고서용 스캐너 — 표기가 제멋대로다: 「」·따옴표·무괄호 명명, 조 번호 없는
# 명명("감사처분에 관한 세칙 감사처분기준 中"), 대명사("동 세칙 제9조").
# 문서명 등장을 전부 추적하고, 각 제N조는 '가장 가까운 선행 명명'에 귀속시킨다.
_NAME = re.compile(r"[가-힣][가-힣·ᆞㆍ\s]{0,18}?(?:세칙|회칙)")
_ANAPHORA = re.compile(r"^(동|같은|위|해당)\s")
_ART_REF = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")
# 같은 문서 안의 조항 참조 — 헤딩(제N조( )과 구분되는, 괄호가 따라오지 않는 본문 참조
_INNER = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?(?!\s*\()")
# 규정 청크가 담고 있는 조항 헤딩
_HEADING = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?\s*\(")

_MIDDLE_DOTS = str.maketrans({"ㆍ": "·", "ᆞ": "·", "･": "·"})


def normalize_doc_name(name: str) -> str:
    """문서명 표기 변형을 정규화한다.

    감사보고서들이 같은 세칙을 '재정·회계 세칙'/'재정·회계에 관한 세칙'/
    '재정ᆞ회계…'처럼 제각각 표기하므로, 공백·가운뎃점·'에 관한'을 걷어내
    같은 키로 만든다 (엔티티 해석).
    """
    n = re.sub(r"\s+", "", name).translate(_MIDDLE_DOTS)
    n = n.replace("에관한", "").removesuffix(".pdf")
    return n


def _art_key(no: str, sub: str | None) -> str:
    return f"제{no}조의{sub}" if sub else f"제{no}조"


def build_graph() -> nx.DiGraph:
    """색인 전체에서 인용 그래프를 만든다. 호출 시마다 처음부터 다시 만든다."""
    from app.rag import store

    data = store._get_collection().get(include=["documents", "metadatas"])

    # 정규화된 문서명 → 실제 파일명 (규정 문서만 참조 대상이 된다)
    canon: dict[str, str] = {}
    for m in data["metadatas"]:
        if m.get("doc_type") == "regulation":
            canon[normalize_doc_name(m["source_file"])] = m["source_file"]

    g = nx.DiGraph()

    def resolve(raw_name: str) -> str | None:
        key = normalize_doc_name(raw_name)
        if key in canon:
            return canon[key]
        # 접미 일치 폴백: "중앙학생회칙" → "인하대학교_중앙학생회칙.pdf" (유일할 때만)
        tails = [v for k, v in canon.items() if k.endswith(key) and len(key) >= 4]
        return tails[0] if len(tails) == 1 else None

    # 대명사("동 세칙") 해석은 문서 내 등장 순서에 의존하므로 청크를 순서대로 처리한다
    by_doc: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for text, m in zip(data["documents"], data["metadatas"]):
        by_doc[m["source_file"]].append((m["chunk_index"], text, m.get("doc_type")))

    for src_doc, chunk_list in by_doc.items():
        last_named: str | None = None  # 이 문서에서 마지막으로 명명된 참조 대상
        for idx, text, dtype in sorted(chunk_list):
            chunk_node = ("chunk", src_doc, idx)
            g.add_node(chunk_node, kind=dtype)

            # 이 청크가 담고 있는 조항 (규정 청크만) — 조항 노드 ↔ 청크 연결
            heads: set[str] = set()
            if dtype == "regulation":
                for no, sub in _HEADING.findall(text):
                    key = _art_key(no, sub)
                    heads.add(key)
                    art_node = ("article", src_doc, key)
                    g.add_node(art_node, kind="article")
                    g.add_edge(art_node, chunk_node, type="contains")

            if dtype == "audit":
                # 명명 위치들을 모아 각 제N조를 가장 가까운 선행 명명에 귀속
                names: list[tuple[int, str]] = []
                for nm in _NAME.finditer(text):
                    raw = nm.group(0).strip()
                    if _ANAPHORA.match(raw):
                        if last_named:
                            names.append((nm.end(), last_named))
                        continue
                    dst = resolve(raw)
                    if dst:
                        names.append((nm.end(), dst))
                        last_named = dst
                for am in _ART_REF.finditer(text):
                    scope = [d for pos, d in names if pos <= am.start()]
                    dst_doc = scope[-1] if scope else last_named
                    if not dst_doc or dst_doc == src_doc:
                        continue
                    art_node = ("article", dst_doc, _art_key(am.group(1), am.group(2)))
                    g.add_node(art_node, kind="article")
                    prev = g.get_edge_data(chunk_node, art_node, {}).get("count", 0)
                    g.add_edge(chunk_node, art_node, type="cites", count=prev + 1)
            else:
                # 규정 문서의 문서 간 참조는 격식 표기(「」)만 신뢰한다
                for raw, no, sub in _CROSS.findall(text):
                    dst_doc = resolve(raw)
                    if not dst_doc or dst_doc == src_doc:
                        continue
                    art_node = ("article", dst_doc, _art_key(no, sub))
                    g.add_node(art_node, kind="article")
                    prev = g.get_edge_data(chunk_node, art_node, {}).get("count", 0)
                    g.add_edge(chunk_node, art_node, type="refers", count=prev + 1)

            # 같은 규정 안의 조항 상호참조
            if dtype == "regulation":
                for no, sub in _INNER.findall(text):
                    key = _art_key(no, sub)
                    if key in heads:  # 자기 자신(헤딩과 같은 조)은 제외
                        continue
                    art_node = ("article", src_doc, key)
                    g.add_node(art_node, kind="article")
                    prev = g.get_edge_data(chunk_node, art_node, {}).get("count", 0)
                    g.add_edge(chunk_node, art_node, type="refers", count=prev + 1)

    return g


def save_graph(g: nx.DiGraph) -> None:
    payload = {
        "nodes": [[list(n), d] for n, d in g.nodes(data=True)],
        "edges": [[list(u), list(v), d] for u, v, d in g.edges(data=True)],
    }
    GRAPH_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    for n, d in payload["nodes"]:
        g.add_node(tuple(n), **d)
    for u, v, d in payload["edges"]:
        g.add_edge(tuple(u), tuple(v), **d)
    return g


_graph: nx.DiGraph | None = None


def get_graph(rebuild: bool = False) -> nx.DiGraph:
    global _graph
    if _graph is None or rebuild:
        if GRAPH_PATH.exists() and not rebuild:
            _graph = load_graph()
        else:
            _graph = build_graph()
            save_graph(_graph)
    return _graph


def _chunk_text(store, doc: str, idx: int) -> dict | None:
    got = store._get_collection().get(
        ids=[f"{did}:{idx}" for did in [None]] if False else None,
        where={"$and": [{"source_file": doc}, {"chunk_index": idx}]},
        include=["documents", "metadatas"],
        limit=1,
    )
    if not got["documents"]:
        return None
    t, m = got["documents"][0], got["metadatas"][0]
    return {
        "text": t,
        "source_file": m["source_file"],
        "doc_id": m.get("doc_id", ""),
        "chunk_index": m["chunk_index"],
        "doc_type": m.get("doc_type", ""),
    }


def expand(hits: list[dict], max_add: int = 10, per_edge: int = 3) -> list[dict]:
    """검색 결과를 인용 그래프로 1-hop 확장한다 (게이트형).

    - 감사 청크 → 그 청크가 인용한 근거 조항의 원문 (정방향 cites)
    - 규정 청크 → 그 조항을 인용한 감사 판례 청크 (역방향 cites; 판례 커버리지 확보)
    - 규정 청크 → 참조하는 다른 조항 원문 (refers)
    인용 빈도가 높은 엣지부터, 전체 상한(max_add) 안에서만 더한다.
    """
    from app.rag import store

    g = get_graph()
    have = {(h["source_file"], h["chunk_index"]) for h in hits}

    def precedent_list(art_node: tuple) -> list[tuple]:
        """이 조항을 인용한 감사 청크(판례)를 문서당 1청크, 인용 빈도순으로."""
        per_doc: dict[str, tuple[int, tuple]] = {}
        for citer, _, rd in g.in_edges(art_node, data=True):
            if rd.get("type") == "cites" and citer[0] == "chunk":
                cnt = rd.get("count", 1)
                if citer[1] not in per_doc or cnt > per_doc[citer[1]][0]:
                    per_doc[citer[1]] = (cnt, citer)
        return [n for _, n in sorted(per_doc.values(), key=lambda x: -x[0])]

    # 조항별 후보 목록을 따로 유지한다. 전역 빈도순으로 뽑으면 한 청크에 여러
    # 조항이 담겼을 때 고빈도 조항의 판례가 예산을 독식해, 정작 질의의 다른
    # 조항 판례가 밀린다. 라운드로빈으로 조항마다 고르게 배분한다.
    core_lists: dict[tuple, list[tuple]] = {}   # 검색된 원문 조항 → 판례들
    cited_articles: list[tuple] = []            # 시드가 인용한 조항의 원문 청크
    fwd_lists: dict[tuple, list[tuple]] = {}    # 인용된 조항 → 다른 판례들

    for h in hits:
        node = ("chunk", h["source_file"], h["chunk_index"])
        if node not in g:
            continue
        # 규정 청크가 담은 조항(contains 역방향)의 판례 — 커버리지의 핵심 경로
        for art, _, cd in g.in_edges(node, data=True):
            if cd.get("type") == "contains" and art not in core_lists:
                core_lists[art] = precedent_list(art)[: per_edge * 2]
        # 시드가 인용한 조항: 원문 청크 + 그 조항의 다른 판례
        for _, art, ed in g.out_edges(node, data=True):
            if ed.get("type") not in ("cites", "refers"):
                continue
            for _, chunk, cd in g.out_edges(art, data=True):
                if cd.get("type") == "contains":
                    cited_articles.append(chunk)
            if art not in fwd_lists:
                fwd_lists[art] = precedent_list(art)[:per_edge]

    def fair_merge(lists: list[list[tuple]]) -> list[tuple]:
        """조항당 1개는 먼저 보장하고(커버리지 하한), 나머지는 목록 순서대로 합친다.

        균등 라운드로빈은 판례가 한 조항에 몰린 질의를 얇게 만들고,
        전역 빈도순은 저빈도 조항을 굶긴다 — 하한 보장 + 잔여 채움이 절충이다.
        """
        out = [lst[0] for lst in lists if lst]
        for lst in lists:
            out.extend(lst[1:])
        return out

    ordered = (
        fair_merge(list(core_lists.values()))
        + cited_articles
        + fair_merge(list(fwd_lists.values()))
    )

    added: list[dict] = []
    for node in ordered:
        if len(added) >= max_add:
            break
        _, doc, idx = node
        if (doc, idx) in have:
            continue
        got = _chunk_text(store, doc, idx)
        if got:
            have.add((doc, idx))
            added.append(got)
    return hits + added
