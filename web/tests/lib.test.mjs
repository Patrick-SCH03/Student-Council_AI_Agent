// 서버·브라우저 없이 도는 프론트 순수 로직 테스트 (Node 내장 테스트 러너 + 타입 제거 실행)
import assert from "node:assert/strict";
import { test } from "node:test";

import { ChatBlockedError, streamChat } from "../src/lib/api.ts";
import { fmt, usd } from "../src/lib/format.ts";
import { answerLabel, questionTypeLabel } from "../src/lib/answer.ts";
import { LIMIT_MAX, parseLimit } from "../src/lib/limits.ts";

test("parseLimit: 빈 값·소수·음수·문자·상한 초과는 저장하지 않는다 (빈 칸이 0=무제한이 되지 않게)", () => {
  for (const bad of ["", "  ", "1.5", "-1", "abc", "1e3", String(LIMIT_MAX.daily_limit_total + 1)]) {
    assert.equal(parseLimit(bad, LIMIT_MAX.daily_limit_total), null, JSON.stringify(bad));
  }
  assert.equal(parseLimit(" 300 ", LIMIT_MAX.daily_limit_total), 300);
  assert.equal(parseLimit("0", LIMIT_MAX.daily_limit_total), 0);
  assert.equal(parseLimit(String(LIMIT_MAX.cache_ttl_hours), LIMIT_MAX.cache_ttl_hours), 720);
});

/** 주어진 조각 그대로 흘려보내는 SSE 응답으로 fetch를 바꿔 끼운다. */
function withFetch(response, fn) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => response;
  return fn().finally(() => {
    globalThis.fetch = original;
  });
}

function sseResponse(chunks) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

async function collect(gen) {
  const out = [];
  for await (const e of gen) out.push(e);
  return out;
}

test("streamChat: 조각 경계·한글 멀티바이트가 잘려 와도 이벤트를 온전히 복원하고, 깨진 이벤트는 건너뛴다", async () => {
  const event = 'data: {"type": "token", "content": "규정 검토"}\n\n';
  const bytes = new TextEncoder().encode(event);
  // 한글 글자 중간에서 바이트를 자른다
  const cut = bytes.findIndex((b) => b >= 0x80) + 1; // '규'(3바이트)의 첫 바이트 뒤
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(bytes.slice(0, cut));
      controller.enqueue(bytes.slice(cut));
      controller.enqueue(encoder.encode('data: {깨진 JSON\n\n: keep-alive\n\ndata: {"type": "result", "risk_level": "낮음"}\n\n'));
      controller.close();
    },
  });
  const events = await withFetch(new Response(body, { status: 200 }), () => collect(streamChat("질문")));
  assert.deepEqual(events, [
    { type: "token", content: "규정 검토" },
    { type: "result", risk_level: "낮음" },
  ]);
});

test("streamChat: 마지막 이벤트가 여러 조각으로 나뉘어 와도 하나로 합친다", async () => {
  const events = await withFetch(
    sseResponse(['data: {"type": "st', 'age", "label": "분석 중"}', "\n", "\n"]),
    () => collect(streamChat("질문")),
  );
  assert.deepEqual(events, [{ type: "stage", label: "분석 중" }]);
});

test("streamChat: 429는 서버가 준 사유로 ChatBlockedError, 그 밖의 실패는 상태 코드를 알린다", async () => {
  const blocked = new Response(JSON.stringify({ detail: "오늘 한도를 다 썼어요." }), { status: 429 });
  await assert.rejects(
    withFetch(blocked, () => collect(streamChat("질문"))),
    (e) => e instanceof ChatBlockedError && e.message === "오늘 한도를 다 썼어요.",
  );
  await assert.rejects(
    withFetch(new Response("x", { status: 502 }), () => collect(streamChat("질문"))),
    /서버 오류 \(502\)/,
  );
});

test("usd: 달러로만 표기하고, 1달러 미만은 소수 넷째 자리까지 보인다", () => {
  assert.equal(usd(0), "$0");
  assert.equal(usd(0.0053), "$0.0053");
  assert.equal(usd(9.1311), "$9.13");
  assert.equal(usd(1234.5), "$1,234.50");
  assert.equal(fmt(12345), "12,345");
});

test("answerLabel: 행위 질문·옛 답변은 위험도, 규정 안내·기록 조회는 질문 유형 — 단 위험도가 낮음이 아니면 숨기지 않는다", () => {
  const label = (question_type, risk_level) =>
    answerLabel({ risk_level, reviewer: question_type === undefined ? null : { question_type } });
  assert.equal(label(undefined, "낮음"), "위험도 낮음"); // question_type 없는 옛 답변
  assert.equal(label("행위", "보통"), "위험도 보통");
  assert.equal(label("기준·절차", "낮음"), "규정 안내");
  assert.equal(label("기록 조회", "낮음"), "감사 기록 조회");
  // 규정 검토는 기준·절차로 봤지만 감사 분석이 처분 가능성을 높게 본 경우 (운영 실제 사례)
  assert.equal(label("기준·절차", "높음"), "위험도 높음");
  assert.equal(label("알 수 없음", "낮음"), "위험도 낮음");
  assert.equal(answerLabel({ risk_level: null, reviewer: null }), null); // 범위 밖 안내
  assert.equal(questionTypeLabel({ question_type: "기준·절차" }, "보통"), null);
  assert.equal(questionTypeLabel({ question_type: "기록 조회" }, "낮음"), "감사 기록 조회");
});

import { MAX_CONTENT_FILES, QUESTIONS, contentTargets, matchSubmissions, nameWarnings, riskyQuestions } from "../src/lib/audit.ts";
import { consentText } from "../src/lib/checklists.ts";
import { fileProblem, parseWon, reportText } from "../src/lib/review-model.ts";

test("감사 자가진단: 제출자료 13종을 파일 이름으로 찾고, 위험한 답만 고른다", () => {
  const names = "0. 기구표.pdf\n1. 사업계획서.pdf\n2. 사업평가서.pdf\n3. 정산서.xlsx\n4. 회의록 모음.pdf\n5. 영수증철.pdf\n6. 금전출납부.xlsx\n7. 통장 사본.pdf\n8. 대관 계약서.pdf\n9. 공약평가서.pdf\n10. 간행물.pdf\n11. 발송공문철.pdf\n12. 수령공문철.pdf\n13. 기타.zip\n".split("\n").filter(Boolean);
  const matched = matchSubmissions(names);
  for (const [id, hits] of Object.entries(matched)) assert.ok(hits.length > 0, `${id} 못 찾음`);
  assert.deepEqual(matchSubmissions(["사업계획서.pdf"]).settle, []);
  const risky = riskyQuestions({ appoint: "no", "personal-card": "no", "own-money": "yes", deadline: "na" });
  assert.deepEqual(risky.map((q) => q.id).sort(), ["appoint", "own-money"]);
  assert.equal(new Set(QUESTIONS.map((q) => q.id)).size, QUESTIONS.length, "질문 id 중복");
});

test("파일 이름 위생: 비속어·비밀번호·전화·학번·계좌는 잡고, 날짜·일반 이름은 지나간다", () => {
  const bad = ["현금영수증 (ㅆㅂ).pdf", "경품 pw 1234.xlsx", "연락처 010-1234-5678.txt", "12201234 결의서.pdf", "환불 110-123-456789.png"];
  for (const f of bad) assert.ok(nameWarnings([f]).length > 0, f);
  const good = ["2025-11-13 회의록.pdf", "20250713 정산서.xlsx", "5. 영수증철.pdf", "사업계획서(최종).pdf"];
  for (const f of good) assert.deepEqual(nameWarnings([f]), [], f);
});

test("동의 문구: 개인정보 보호법 제15조 제2항의 네 가지가 모두 들어간다", () => {
  const t = consentText({ org: "가나다학과 학생회", purpose: "MT 신청", items: "이름, 학과", keep: "행사 후 파기", refuse: "참가가 어렵습니다" });
  for (const part of ["목적: MT 신청", "항목: 이름, 학과", "보관 기간: 행사 후 파기", "거부할 수 있으며"]) assert.ok(t.includes(part), part);
});

test("문서 검토 화면 도우미: 파일 거르기·금액 입력·결과 글", () => {
  const file = (name, size = 10) => ({ name, size });
  assert.equal(fileProblem(file("사업안.hwp")), null);
  assert.equal(fileProblem(file("사업안.HWPX")), null);
  assert.equal(fileProblem(file("a.docx")), null);
  assert.match(fileProblem(file("a.xls")), /예전 형식/);
  assert.match(fileProblem(file("a.zip")), /PDF·한글·워드·엑셀/);
  assert.match(fileProblem(file("a.pdf", 20 * 1024 * 1024)), /15MB/);
  assert.equal(fileProblem(file("예산안.XLSX")), null);
  assert.equal(parseWon("1,200,000원"), 1200000);
  assert.equal(parseWon(""), null);
  assert.equal(parseWon("-50,000"), -50000);
  const text = reportText("일일호프", [{ code: "reserve", level: "위반 소지", title: "예비비 초과", detail: "", basis: "「재정·회계 세칙」 제16조", where: "" }]);
  assert.match(text, /1\. \[위반 소지\] 예비비 초과/);
  assert.match(text, /근거: 「재정·회계 세칙」 제16조/);
});

import { changeChecks, changeNumbers, incidentChecks, letterChecks, paymentChecks, rowsTotal } from "../src/lib/writer.ts";

test("문서 작성 검산: 예비비 잔액(실제 1원 오류 사례)·경위서 금액표·현금 한도·공문 연도", () => {
  // 드라이브의 예산 변경 사유서: 초과 113,735원 → 예비비 250,000 − 113,735 = 136,265 (문서에는 136,264로 적힘)
  const c = { item: "숙박", approved: 39_440, spent: 153_175, reserve: 250_000, budgetTotal: 0, reason: "" };
  assert.deepEqual(changeNumbers(c), { over: 113_735, reserveLeft: 136_265 });
  assert.ok(changeChecks({ ...c, reserve: 100_000 }).some((x) => !x.ok && /예비비를/.test(x.text)));
  // 환불 경위서 금액표: 37,850 + 47,200×4 + 18,960×4 = 302,490
  const rows = [{ name: "a", qty: 1, unit: 37_850 }, { name: "b", qty: 4, unit: 47_200 }, { name: "c", qty: 4, unit: 18_960 }];
  assert.equal(rowsTotal(rows), 302_490);
  assert.ok(incidentChecks({ date: "", what: "", causes: [], rows, stated: 302_000, followUp: "x" }).some((x) => !x.ok));
  assert.ok(paymentChecks({ event: "", reason: "심판 수당", method: "현금", people: 2, unit: 200_000, times: 1 }).some((x) => !x.ok && /제31조/.test(x.text)));
  const letter = { number: "가나다-2025-0003", date: "2026-03-09", to: "", cc: "", title: "자료 제출", body: "2025. 3. 9. 회의 결과", attachments: "", from: "" };
  const msgs = letterChecks(letter).filter((x) => !x.ok).map((x) => x.text).join(" ");
  assert.match(msgs, /문서번호 연도/);
  assert.match(msgs, /지난 연도/);
});

import { localToday } from "../src/lib/writer.ts";

test("오늘 날짜는 브라우저 시간대 기준이다 (UTC로 하루 밀리지 않게)", () => {
  assert.equal(localToday(new Date(2026, 10, 28, 1, 30)), "2026-11-28");
  assert.equal(localToday(new Date(2026, 0, 5)), "2026-01-05");
});

import { draftTotal, inputProblem, toEdit } from "../src/lib/plan-model.ts";

test("기획 도우미: 고친 안에는 계산 결과를 빼고 보내며, 입력 문제를 먼저 알려 준다", () => {
  const plan = {
    request: { title: "간식", purpose: "응원", start: "2026-04-20", end: null },
    intent: "의도",
    steps: [],
    expected: [],
    cautions: [],
    lines: [{ item: "기프티콘", unit_price: 7700, qty: 50, unit: "개", basis: "", amount: 385000, evidence_kind: "x", evidence: [], checklist: null }],
    reserve: 15000,
    expense_total: 400000,
    over_cap: 0,
    method: "ai",
  };
  const edit = toEdit(plan);
  assert.deepEqual(edit.lines, [{ item: "기프티콘", unit_price: 7700, qty: 50, unit: "개", basis: "" }]);
  assert.equal("expense_total" in edit || "over_cap" in edit, false);
  assert.equal(draftTotal(edit.lines, edit.reserve), 400000);
  const input = { title: "간식", purpose: "응원", start: "2026-04-20", end: "2026-04-19" };
  assert.match(inputProblem(input), /시작일보다 빨라요/);
  assert.equal(inputProblem({ ...input, end: null }), null);
  assert.match(inputProblem({ ...input, title: " " }), /사업명/);
});

import { parseBudgets, parseMonthDay, parseSpends, settle, settleIssues, settleTsv } from "../src/lib/settle.ts";

test("정산 도우미: 붙여 넣은 표를 읽어 사업별로 묶고, 영수증 번호를 단위-사업-순서로 매긴다", () => {
  assert.deepEqual(parseMonthDay("2025-05-28"), [5, 28]);
  assert.deepEqual(parseMonthDay("25.05.28"), [5, 28]);
  assert.deepEqual(parseMonthDay("5/3"), [5, 3]);
  assert.deepEqual(parseMonthDay("5월 3일"), [5, 3]);
  assert.equal(parseMonthDay("13/40"), null);

  const { spends, bad } = parseSpends(
    [
      "날짜\t사업명\t상세내용\t금액",
      "5/28\t간식드리미\t싸이버거 11개\t80,300원",
      "5/20\t간식드리미\t싸이버거 39개\t284,700",
      "5/30\t체육대회\t공 구매\t30,000",
      "5/30\t체육대회\t공 구매\t30,000",
      "날짜없음\t체육대회\t\t1000",
    ].join("\n"),
  );
  assert.equal(spends.length, 4);
  assert.deepEqual(bad, [6]);

  const parsed = parseBudgets("사업명\t금액\n간식드리미\t385,000\n체육대회,50,000\n멘토링 100,000원\n금액없음\t");
  const budgets = parsed.budgets;
  assert.deepEqual(budgets.map((b) => [b.project, b.amount]), [["간식드리미", 385000], ["체육대회", 50000], ["멘토링", 100000]]);
  assert.deepEqual(parsed.bad, [5]); // 빈 금액을 0원짜리 사업으로 만들지 않는다
  // 탭으로 열이 나뉘었는데 금액이 비면 사업명 끝 숫자를 금액으로 읽지 않는다
  assert.deepEqual(parseBudgets("사업명\t금액\n축제 2026\t"), { budgets: [], bad: [2] });
  const summary = settle("컴공", spends, budgets);
  assert.deepEqual(summary.map((p) => p.project), ["간식드리미", "체육대회", "멘토링"]);
  assert.deepEqual(summary[0].rows.map((r) => [r.day, r.receipt]), [[20, "컴공-1-1"], [28, "컴공-1-2"]]);
  assert.equal(summary[0].diff, 20_000);
  assert.equal(summary[1].diff, -10_000);

  const issues = settleIssues(summary, spends).map((i) => i.text).join("\n");
  assert.match(issues, /'간식드리미'는 예산보다 20,000원 적게/);
  assert.match(issues, /'체육대회' 지출이 예산보다 10,000원 많아요/);
  assert.match(issues, /'멘토링' 지출 기록이 없어요/);
  assert.match(issues, /5\.30 30,000원 지출이 2번/);

  const tsv = settleTsv(summary).split("\n");
  assert.equal(tsv[0], "계정\t월\t일\t사업명\t상세내용\t금액\t영수증번호");
  assert.equal(tsv[1], "사업비\t5\t20\t간식드리미\t싸이버거 39개\t284700\t컴공-1-1");
});

import { josa } from "../src/lib/format.ts";

test("조사: 받침 있으면 '은', 없으면 '는' (따옴표 건너뜀)", () => {
  assert.equal(josa("'간식드리미'", "은", "는"), "'간식드리미'는");
  assert.equal(josa("'멘토링'", "은", "는"), "'멘토링'은");
  assert.equal(josa("MT", "은", "는"), "MT는");
});

import { minutesChecks, todoTopic } from "../src/lib/minutes-model.ts";
import { topicFor } from "../src/lib/review-model.ts";

test("회의록 정리: 담당·기한 빈칸을 알리고, 개인정보·주류 할 일은 점검표로 잇는다 ('기술'은 주류가 아님)", () => {
  const base = { title: "회의", held_on: "2026-02-11", place: "", attendees: null, agenda: [], decisions: [], next_agenda: [] };
  const todos = [
    { task: "신청 폼 개인정보 동의 문구 수정", owner: "", due: null },
    { task: "견적 받기", owner: "재무팀장", due: "2026-02-13" },
  ];
  const checks = minutesChecks({ ...base, todos }).map((c) => c.text);
  assert.deepEqual(checks, ["담당이 정해지지 않은 할 일이 1건 있어요.", "기한이 없는 할 일이 1건 있어요."]);
  assert.equal(minutesChecks({ ...base, todos: [todos[1]] })[0].ok, true);
  assert.equal(todoTopic(todos[0]), "privacy");
  assert.equal(topicFor("뒤풀이 맥주 예산"), "liquor");
  assert.equal(topicFor("기술 세미나 준비"), null);
  assert.equal(topicFor("축제 먹거리 부스 조리 인원"), "liquor");
  assert.equal(topicFor("영화 상영회 대관"), "copyright");
  assert.equal(topicFor("과잠 공동구매"), "groupbuy");
});

import { KEEP_DAYS, MAX_ITEMS, deleteWork, listWork, saveWork } from "../src/lib/workspace.ts";

test("내 작업함: 계정별로 따로 남고, 30일이 지나면 안 보이며, 50건까지만 둔다", () => {
  const mem = new Map();
  const store = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  const now = Date.parse("2026-03-01T00:00:00Z");
  const a = saveWork("a@inha.edu", { kind: "plan", title: "간식", text: "초안" }, now, store);
  saveWork("b@inha.edu", { kind: "minutes", title: "회의", text: "회의록" }, now, store);
  assert.equal(listWork("a@inha.edu", now, store).length, 1);
  assert.equal(listWork("a@inha.edu", now + (KEEP_DAYS + 1) * 86_400_000, store).length, 0);
  for (let i = 0; i < MAX_ITEMS + 5; i++) saveWork("a@inha.edu", { kind: "review", title: `t${i}`, text: "" }, now + i, store);
  const items = listWork("a@inha.edu", now + 100, store);
  assert.equal(items.length, MAX_ITEMS);
  assert.equal(items[0].title, `t${MAX_ITEMS + 4}`);
  assert.equal(deleteWork("b@inha.edu", "nope", now, store).length, 1);
  // 만료된 원문은 목록에서만 빠지는 게 아니라 저장소에서도 지워진다
  listWork("b@inha.edu", now + (KEEP_DAYS + 1) * 86_400_000, store);
  assert.equal(JSON.parse(mem.get("workspace:b@inha.edu")).length, 0);
  assert.equal(listWork("a@inha.edu", now, null).length, 0); // 저장소를 못 쓰면 빈 목록
  assert.ok(a?.id);
});

test("정산 도우미: 2학기처럼 해를 넘기면 1·2월 지출을 뒤로 보내 영수증 번호를 날짜순으로 매긴다", () => {
  const { spends } = parseSpends("1/10\t축제\t정산\t10,000\n9/20\t축제\t준비\t20,000\n12/1\t축제\t진행\t30,000");
  const [p] = settle("가", spends, []);
  assert.deepEqual(p.rows.map((r) => [r.month, r.receipt]), [[9, "가-1-1"], [12, "가-1-2"], [1, "가-1-3"]]);
  const withYears = parseSpends("2026-01-10\t축제\t정산\t10,000\n2025-09-20\t축제\t준비\t20,000").spends;
  const rows = settle("", withYears, [])[0].rows;
  assert.deepEqual(rows.map((r) => [r.month, r.receipt]), [[9, "1-1"], [1, "1-2"]]);
  // 다른 사업의 연도 없는 지출이 이 사업의 번호를 바꾸지 않는다
  const mixed = [...withYears, ...parseSpends("5/1\t다른사업\t구매\t3,000").spends];
  assert.deepEqual(settle("", mixed, [])[0].rows.map((r) => r.receipt), ["1-1", "1-2"]);
  assert.equal(settle("", mixed, [])[0].rows[0].month, 9);
});

test("공지: 닫은 공지는 숨기고, 고쳐 다시 올린 공지(새 id)는 다시 보이며, 저장소가 막혀도 공지는 보인다", async () => {
  const { visibleNotice, dismissNotice } = await import("../src/lib/notice.ts");
  const map = new Map();
  const store = { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v) };
  const first = { id: "2026-11-28T01:00:00", text: "방침 변경", href: "/privacy", until: null };
  assert.equal(visibleNotice(first, store), first);
  dismissNotice(first, store);
  assert.equal(visibleNotice(first, store), null);
  const edited = { ...first, id: "2026-11-28T02:00:00" };
  assert.equal(visibleNotice(edited, store), edited);
  assert.equal(visibleNotice(null, store), null);
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(visibleNotice(first, blocked), first);
  dismissNotice(first, blocked); // 던지지 않는다
});

test("감사자료 첨부: 금액 문서(사업계획·예산·정산·결산) 중 읽을 수 있는 형식만, 크기 안, 많아야 8개를 내용 점검한다", () => {
  const f = (path, size = 1000) => ({ path, size });
  const got = contentTargets(
    [
      f("1.사업계획서/간식드리미 사업안.hwp"),
      f("3.정산서/2학기 정산서.xlsx"),
      f("3.정산서/영수증1.png"),
      f("5.영수증철/예산 영수증.jpg"),
      f("결산 보고.HWPX"),
      f("큰 예산안.pdf", 20 * 1024 * 1024),
      f("회의록.pdf"),
    ],
    15 * 1024 * 1024,
  ).map((x) => x.path);
  assert.deepEqual(got, ["1.사업계획서/간식드리미 사업안.hwp", "3.정산서/2학기 정산서.xlsx", "결산 보고.HWPX"]);
  const many = Array.from({ length: 12 }, (_, i) => f(`예산안${i}.pdf`));
  assert.equal(contentTargets(many, 15 * 1024 * 1024).length, MAX_CONTENT_FILES);
});

test("다가오는 일정: D-day·내일·오늘·지난 날, 날짜에 요일을 붙인다", async () => {
  const { dday, dateLabel } = await import("../src/lib/events.ts");
  assert.equal(dday("2026-12-05", "2026-11-28"), "D-7");
  assert.equal(dday("2026-11-29", "2026-11-28"), "내일");
  assert.equal(dday("2026-11-28", "2026-11-28"), "오늘");
  assert.equal(dday("2026-11-25", "2026-11-28"), "3일 전");
  assert.equal(dday("2027-01-01", "2026-12-31"), "내일"); // 해를 넘긴다
  assert.equal(dateLabel("2026-12-05"), "12월 5일 (토)");
});

test("Word 파일: 양식이 열리는 .docx가 되고, 첫 쪽에 인하대 마크·기관명, 공문은 수신자·시행 칸이 맞춰지고, 결재란은 없다", async () => {
  const { Packer } = await import("docx");
  const JSZip = (await import("jszip")).default;
  const { blocksToDocument } = await import("../src/lib/office/docx.ts");
  const f = await import("../src/lib/office/forms.ts");
  const { readFileSync } = await import("node:fs");
  const emblem = new Uint8Array(readFileSync(new URL("../public/emblem.png", import.meta.url)));
  const xml = async (blocks) => {
    const buf = await Packer.toBuffer(blocksToDocument(blocks, { emblem }));
    assert.equal(buf.subarray(0, 2).toString(), "PK");
    const zip = await JSZip.loadAsync(buf);
    assert.ok(Object.keys(zip.files).some((n) => n.startsWith("word/media/")), "마크 이미지");
    return zip.file("word/document.xml").async("string");
  };
  const letter = await xml(
    f.letterBlocks({ number: "컴공-2026-0017", date: "2026-11-28", to: "총대의원회 의장", cc: "", title: "자료 제출", body: "붙임과 같이 제출합니다.", attachments: "사업계획서 1부\n예산안 1부", from: "컴퓨터공학과 학생회장" }),
  );
  for (const want of ["인하대학교 컴퓨터공학과 학생회", "수신자", "총대의원회 의장", "(경유)", "1. 우리 학교의 무궁한 발전을 기원합니다.", "2. 붙임과 같이 제출합니다.", "붙임", "1. 사업계획서 1부", "2. 예산안 1부  끝.", "인하대학교 컴퓨터공학과 학생회장", "시행 컴공-2026-0017 (2026.11.28.)", "접수", "맑은 고딕", 'w:jc w:val="distribute"']) {
    assert.ok(letter.includes(want), want);
  }
  assert.ok(!letter.includes("결재"));
  const pay = await xml(f.paymentBlocks({ event: "체육대회", reason: "심판 수당", method: "계좌이체", people: 5, unit: 20000, times: 3 }, "컴퓨터공학과 학생회"));
  assert.equal((pay.match(/60,000원/g) || []).length, 5 + 1); // 지급 사유의 1인 금액 + 5명 줄 (빈 줄 3개는 금액 없음)
  assert.ok(pay.includes("300,000원 (5명)") && pay.includes("컴퓨터공학과 학생회") && !pay.includes("결재"));
  const minutes = await xml(
    f.minutesBlocks({ title: "정기 회의", held_on: "2026-11-18", place: "학생회실", attendees: 6, agenda: [{ title: "간식드리미", discussion: "60명 선착순", result: "가결" }], decisions: ["진행"], todos: [{ task: "신청서", owner: "기획국장", due: "2026-11-20" }], next_agenda: [] }),
  );
  assert.ok(minutes.includes("기획국장") && minutes.includes("2026. 11. 20."));
  assert.equal(f.orgOf("컴퓨터공학과 학생회장"), "컴퓨터공학과 학생회");
  assert.equal(f.orgOf("총대의원회 의장"), "총대의원회");
  assert.deepEqual(f.letterParagraphs("첫 문단입니다.\n\n- 아 래 -\n가. 일시"), [
    "1. 우리 학교의 무궁한 발전을 기원합니다.",
    "2. 첫 문단입니다.",
    "3. - 아 래 -\n가. 일시",
  ]);
});

test("문서 쪽 채우기: 공문의 시행 칸이 한 쪽 안에서 아래로 내려가고, 넘치면 빈 줄을 두지 않는다 · 복사용 글은 '이름 : 내용'", async () => {
  const { PAGE_BODY, fillGap, roughHeight, blocksText } = await import("../src/lib/office/blocks.ts");
  const f = await import("../src/lib/office/forms.ts");
  const base = { number: "", date: "", to: "의장", cc: "", title: "제출", attachments: "", from: "가나다학과 학생회장" };
  const short = f.letterBlocks({ ...base, body: "붙임과 같이 제출합니다." });
  const gap = short.find((b) => b.t === "gap" && (b.lines ?? 1) > 2);
  assert.ok(gap && gap.lines > 10, "짧은 공문은 빈 줄로 시행 칸을 아래로");
  assert.ok(roughHeight(short) <= PAGE_BODY);
  const long = f.letterBlocks({ ...base, body: Array.from({ length: 40 }, (_, i) => `문단 ${i}`).join("\n\n") });
  assert.ok(long.filter((b) => b.t === "gap").every((b) => (b.lines ?? 1) <= 2), "넘치면 채우지 않는다");
  assert.deepEqual(fillGap([{ t: "gap", lines: 100 }], []), { t: "gap", lines: 0 });
  const text = blocksText(short);
  assert.ok(text.includes("수신자 : 의장") && text.includes("(경유)\n") && !text.includes("(경유) :"), text);
});

test("엑셀 정산표: 사업별 정산서·예산 대비 두 시트, 금액은 숫자 칸(천 단위 서식), 사업 합계 줄", async () => {
  const ExcelJS = (await import("exceljs")).default;
  const { settleWorkbook } = await import("../src/lib/office/xlsx.ts");
  const { parseSpends, settle, settleIssues } = await import("../src/lib/settle.ts");
  const { spends } = parseSpends("10/02\t물품대여\t우산 15개\t37,500\n10/05\t물품대여\t충전기\t30,000\n12/12\t송년회\t다과\t80,000");
  const summary = settle("컴공", spends, [{ project: "물품대여", amount: 121638 }]);
  const wb = await settleWorkbook("컴공", summary, settleIssues(summary, spends));
  const back = new ExcelJS.Workbook();
  await back.xlsx.load(await wb.xlsx.writeBuffer());
  const ws = back.getWorksheet("사업별 정산서");
  assert.deepEqual(ws.getRow(1).values.slice(1), ["계정", "월", "일", "사업명", "상세내용", "금액", "영수증번호"]);
  assert.equal(ws.getRow(2).getCell(6).value, 37500);
  assert.equal(ws.getRow(2).getCell(6).numFmt, "#,##0");
  assert.equal(ws.getRow(2).getCell(7).value, "컴공-1-1");
  assert.equal(ws.getRow(4).getCell(4).value, "물품대여 합계");
  assert.equal(ws.getRow(4).getCell(6).value, 67500);
  const vs = back.getWorksheet("예산 대비");
  assert.deepEqual(vs.getRow(2).values.slice(1, 5), ["물품대여", 121638, 67500, 54138]);
  assert.equal(vs.getRow(3).getCell(2).value, "예산 없음");
});

test("파일 이름: 쓸 수 없는 글자를 빼고 한국 날짜를 붙인다", async () => {
  const { fileName } = await import("../src/lib/office/download.ts");
  assert.equal(fileName('공문 "자료/제출"?', "docx", new Date("2026-11-28T00:30:00Z")), "공문 자료 제출_2026-11-28.docx");
  assert.equal(fileName("   ", "xlsx", new Date("2026-11-28T00:30:00Z")), "문서_2026-11-28.xlsx");
});

test("파일럿 반영: 공문 기관명은 직책에서 바르게, 검증 오류는 한국어, 예산 변경 사유서에 -0원·음수 예비비가 없다", async () => {
  const { orgOf } = await import("../src/lib/office/forms.ts");
  const cases = {
    총학생회장: "총학생회",
    동아리연합회장: "동아리연합회",
    중앙선거관리위원장: "중앙선거관리위원회",
    "공과대학 비상대책위원장": "공과대학 비상대책위원회",
    "컴퓨터공학과 부학생회장": "컴퓨터공학과 학생회",
    "제45대 총학생회장 권한대행": "제45대 총학생회",
    "총대의원회 의장": "총대의원회",
  };
  for (const [from, org] of Object.entries(cases)) assert.equal(orgOf(from), org, from);

  const { validationText } = await import("../src/lib/validation.ts");
  assert.equal(validationText({ type: "string_too_long", loc: ["body", "title"], ctx: { max_length: 60 }, msg: "String should have at most 60 characters" }), "사업명은 60자까지 적을 수 있어요.");
  assert.equal(validationText({ type: "string_too_long", loc: ["body", "org"], ctx: { max_length: 40 } }), "기구는 40자까지 적을 수 있어요.");
  assert.equal(validationText({ type: "value_error", msg: "Value error, 끝나는 날이 시작일보다 빨라요" }), "끝나는 날이 시작일보다 빨라요");
  assert.ok(!/[A-Za-z]/.test(validationText({ type: "weird", msg: "Input should be a valid integer" })));

  const w = await import("../src/lib/writer.ts");
  const base = { item: "MT", approved: 1_000_000, spent: 1_000_000, reserve: 100_000, budgetTotal: 1_100_000, reason: "" };
  assert.ok(w.changeText(base).includes("남은 금액: 0원") && !w.changeText(base).includes("-0"));
  assert.ok(w.changeText({ ...base, spent: 1_270_000 }).includes("예비비 초과 170,000원"));
});

test("교차 리뷰 반영: 띄어 쓴 직책('○○위원회 위원장'·'○○ 학생회 부회장')도 기관명으로, 숫자가 아닌 금액은 —", async () => {
  const { orgOf } = await import("../src/lib/office/forms.ts");
  assert.equal(orgOf("졸업준비위원회 위원장"), "졸업준비위원회");
  assert.equal(orgOf("총학생회 비상대책위원회 위원장"), "총학생회 비상대책위원회");
  assert.equal(orgOf("간호학과 학생회 부회장"), "간호학과 학생회");
  assert.equal(orgOf("학생복지위원회 부위원장"), "학생복지위원회");
  const { won } = await import("../src/lib/format.ts");
  assert.equal(won(Number.NaN), "—");
  assert.equal(won(-0), "0원");
});

test("정산표: '60만원'·'1만 5천원'도 금액으로 읽고, 없는 날짜(11/31)는 읽지 못한 줄로 알린다", async () => {
  const { parseSpends } = await import("../src/lib/settle.ts");
  assert.deepEqual(parseSpends("11/20\t체육대회\t상금\t60만원").spends.map((s) => s.amount), [600_000]);
  assert.deepEqual(parseSpends("11/20\t체육대회\t상금\t1만 5천원").spends.map((s) => s.amount), [15_000]);
  assert.deepEqual(parseSpends("머리글\n11/31\t체육대회\t다과\t1,000").bad, [2]);
  assert.equal(parseSpends("2/29\t체육대회\t다과\t1,000").spends.length, 1);
  // '3만5'는 35,000인지 30,005인지 알 수 없다 — 지어 읽지 않고 못 읽은 줄로 알린다. 세 자리 이상·환불(-)은 읽는다
  assert.deepEqual(parseSpends("11/20\t체육대회\t상금\t3만5").bad, [1]);
  assert.deepEqual(parseSpends("11/20\t체육대회\t상금\t1만500원\n11/21\t체육대회\t환불\t-5만원").spends.map((s) => s.amount), [10_500, -50_000]);
  const { parseBudgets } = await import("../src/lib/settle.ts");
  assert.deepEqual(parseBudgets("간식 60만원").budgets, [{ project: "간식", amount: 600_000 }]);
  // 소수점은 만 앞에서만 — '1.500원'·'5.28'을 2원·5원으로 읽지 않는다
  assert.deepEqual(parseBudgets("사업 예산\n간식 1.500원\n행사 5.28\n축제 2.5만원"), { budgets: [{ project: "축제", amount: 25_000 }], bad: [2, 3] });
});

test("지급확인서: 추첨 경품만 5만 원 원천징수 안내, 대회 시상 경품은 상금 규칙(25만 원)을 따른다", async () => {
  const { paymentChecks } = await import("../src/lib/writer.ts");
  const base = { event: "체육대회", method: "상품권", people: 3, unit: 60_000, times: 1 };
  const says = (reason, unit = 60_000) => paymentChecks({ ...base, reason, unit }).filter((c) => !c.ok).map((c) => c.text).join(" ");
  assert.match(says("경품 추첨"), /추첨으로 주는 경품/);
  assert.match(says("경품"), /추첨으로 주는 경품/);
  assert.match(says("체육대회 경품"), /추첨으로 주는 경품/); // 대회에서 주는 경품도 대부분 추첨
  assert.doesNotMatch(says("대회 시상 경품"), /추첨/);
  assert.match(says("대회 시상 경품", 300_000), /대회 상금/);
  assert.doesNotMatch(says("대회 시상 경품", 300_000), /추첨/);
});

test("사령 공고: 동의가 필요한 직책을 임명하면 근거 조항으로 알리고, 사의수리·일반 직책엔 목록만 보인다", async () => {
  const { appointChecks } = await import("../src/lib/writer.ts");
  const texts = (rows) => appointChecks({ org: "", date: "2026-03-02", head: "", rows }).map((c) => c.text).join("\n");
  const one = (kind, role) => texts([{ kind, role, name: "김인하" }]);
  assert.match(one("임명", "총무국장"), /사전 동의가 필요한 직책: 총학생회 수석집행국장/);
  assert.match(one("임명", "학생복지위원장"), /학생복지위원장은 대의원총회의 동의를 얻어 임명할 수 있어요\(총학생회 조직 구성에 관한 세칙 제17조 제1항\)/);
  assert.match(one("임명", "2학년 과대"), /학년별 과대표는 단과대학 대의원회의 동의를 받아/);
  assert.match(one("임명", "수석집행국장"), /중앙학생회칙 제57조 제2항/);
  assert.doesNotMatch(one("사의수리", "수석집행국장"), /제57조/);
  assert.doesNotMatch(texts([]), /게시한 곳/);
  // 국장: 기구 이름으로 총학생회·단과대학을 가르고, 학과 학생회 국장엔 동의 안내를 띄우지 않는다
  const at = (org, role) => appointChecks({ org, date: "2026-03-02", head: "", rows: [{ kind: "임명", role, name: "김인하" }] }).map((c) => c.text).join("\n");
  assert.match(at("공과대학 학생회", "총무국장"), /단과대학 국장급 임원은 단과대학 대의원총회의 인준을 받아/);
  assert.match(at("총학생회", "총무국장"), /제57조 제2항/);
  assert.doesNotMatch(at("정보통신공학과 학생회", "총무국장"), /인준을 받아|제57조 제2항/);
  assert.match(appointChecks({ org: "", date: "", head: "", rows: [{ kind: "임명", role: "기획국장", name: "김" }] }, "문과대학 학생회").map((c) => c.text).join(), /단과대학 대의원총회/);
});

test("사업계획서 Word: 회의 이름은 총회 공고 꼴로, 파일 이름은 '연도 회의 기구 사업명 사업계획서'", async () => {
  const { meetingTitle, planFileName } = await import("../src/lib/office/forms.ts");
  assert.equal(meetingTitle("2학기 6차 정기총회", "2026-12-03"), "2026년도 2학기 6차 중앙 정기총회");
  assert.equal(meetingTitle("6차  정기 총회", "2026-12-03"), "2026년도 2학기 6차 중앙 정기총회");
  assert.equal(meetingTitle("상임위원회", "2027-01-10"), "2026년도 2학기 상임위원회"); // 1월은 전년도 2학기
  assert.equal(meetingTitle("2026년도 2학기 5차 중앙 정기총회", "2026-11-30"), "2026년도 2학기 5차 중앙 정기총회");
  assert.equal(meetingTitle("1차 정기 대의원총회", "2026-04-01"), "2026년도 1학기 1차 정기 대의원총회"); // 대의원총회엔 '중앙'을 넣지 않는다
  assert.equal(meetingTitle("", "2026-04-01"), "2026년도 1학기");
  assert.equal(
    planFileName({ org: "컴퓨터공학과 학생회", title: "체육대회", meeting: "2학기 6차 정기총회", start: "2026-12-03" }),
    "2026 2학기 6차 중앙 정기총회 컴퓨터공학과 학생회 체육대회 사업계획서",
  );
});

test("사업계획서 Word: 표지 → 목차 → (쪽 번호 1부터) 기구표 → Ⅱ → 세부 → Ⅲ → 세부 예산, 장마다 새 쪽", async () => {
  const { planDocBlocks } = await import("../src/lib/office/forms.ts");
  const server = [
    { t: "heading", text: "Ⅱ. 사업 계획서" },
    { t: "subheading", text: "1. 전체 사업 계획서" },
    { t: "subheading", text: "2. 세부 사업 계획서" },
    { t: "para", text: "체육대회" },
    { t: "heading", text: "Ⅲ. 예산운영 계획서" },
    { t: "subheading", text: "1. 전체 예산 계획서" },
    { t: "subheading", text: "2. 세부 예산 계획서 (예산 세부 내역 판단 자료)" },
  ];
  const req = { org: "컴퓨터공학과 학생회", title: "체육대회", meeting: "2학기 6차 정기총회", start: "2026-12-03", term: "제43대" };
  const out = planDocBlocks(req, server, "2026-11-28");
  const cover = out[0];
  assert.equal(cover.t, "cover");
  assert.deepEqual(cover.lines, ["2026년도 2학기 6차 중앙 정기총회", "(컴퓨터공학과 학생회 「체육대회」 사업안 및 예산안)"]);
  assert.equal(cover.signer, "제43대 컴퓨터공학과 학생회");
  assert.equal(cover.date, "2026. 11. 28");
  const toc = out.find((b) => b.t === "toc");
  assert.deepEqual(toc.items.map((i) => `${i.text}:${i.page}`), [
    "Ⅰ. 기구표:1", "Ⅱ. 사업 계획서:2", "1. 전체 사업 계획서:2", "2. 세부 사업 계획서:3",
    "Ⅲ. 예산운영 계획서:4", "1. 전체 예산 계획서:4", "2. 세부 예산 계획서:5",
  ]);
  const seq = out.map((b) => (b.t === "heading" || b.t === "subheading" ? b.text.slice(0, 7) : b.t));
  const section = seq.indexOf("section");
  assert.ok(section > seq.indexOf("toc") && seq[section + 1] === "Ⅰ. 기구표");
  for (const head of ["Ⅱ. 사업 계", "2. 세부 사", "Ⅲ. 예산운영", "2. 세부 예"]) assert.equal(seq[seq.indexOf(head) - 1], "pagebreak", head);
  // 옛 서버 블록(나눌 곳이 없음)이어도 깨지지 않는다
  const old = planDocBlocks({ org: "", title: "간식" }, [{ t: "heading", text: "Ⅱ. 사업 계획서" }], "2026-04-02");
  assert.equal(old[0].signer, "○○ 학생회");
  assert.deepEqual(old.find((b) => b.t === "toc").items.map((i) => i.page), [1, 2]);
  const { blocksToDocument } = await import("../src/lib/office/docx.ts");
  assert.ok(blocksToDocument(out)); // 표지·목차·구역 나눔이 Word로 만들어진다
});

test("작성자 정보: 계정별로 기구·대수를 기억하고, 빈 값으로 지난 값을 지우지 않는다", async () => {
  const { loadProfile, rememberProfile } = await import("../src/lib/profile.ts");
  const map = new Map();
  const store = { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v) };
  assert.equal(loadProfile("a@inha.edu", store), null);
  rememberProfile("a@inha.edu", { org: " 컴퓨터공학과 학생회 ", term: "제43대" }, store);
  rememberProfile("a@inha.edu", { org: "", term: "" }, store);
  assert.deepEqual(loadProfile("a@inha.edu", store), { org: "컴퓨터공학과 학생회", term: "제43대" });
  assert.equal(loadProfile("b@inha.edu", store), null); // 다른 계정엔 보이지 않는다
  map.set("profile:c@inha.edu", "{broken");
  assert.equal(loadProfile("c@inha.edu", store), null);
});

test("사업계획서 교차 리뷰 반영: 2월의 '1학기'는 그해, 연도를 적은 회의 이름은 그대로, 긴 파일 이름도 '사업계획서'로 끝난다", async () => {
  const { meetingTitle, planFileName } = await import("../src/lib/office/forms.ts");
  assert.equal(meetingTitle("1학기 3차 정기총회", "2026-02-10"), "2026년도 1학기 3차 중앙 정기총회");
  assert.equal(meetingTitle("2학기 1차 정기총회", "2027-01-15"), "2026년도 2학기 1차 중앙 정기총회");
  assert.equal(meetingTitle("1학기 1차 정기총회", "2026-10-01"), "2027년도 1학기 1차 중앙 정기총회");
  assert.equal(meetingTitle("25년 2학기 총회", "2026-12-01"), "25년 2학기 총회");
  const long = planFileName({ org: "소프트웨어융합공학과 학생회", title: "가".repeat(40), meeting: "2학기 6차 정기총회", start: "2026-12-03" });
  assert.ok(long.endsWith("사업계획서") && [...long].length <= 56 + 10, long);
});
