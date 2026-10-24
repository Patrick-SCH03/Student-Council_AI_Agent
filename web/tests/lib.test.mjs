// 서버·브라우저 없이 도는 프론트 순수 로직 테스트 (Node 내장 테스트 러너 + 타입 제거 실행)
import assert from "node:assert/strict";
import { test } from "node:test";

import { ChatBlockedError, streamChat } from "../src/lib/api.ts";
import { fmt, usd } from "../src/lib/format.ts";
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
