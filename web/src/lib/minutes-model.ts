// 회의록 정리 데이터 모양과 순수 도우미 (네트워크 없음 — 단위 테스트가 바로 불러 쓴다).

import { topicFor } from "./review-model.ts";

export type AgendaResult = "가결" | "부결" | "결정" | "보류" | "공유";
export type Todo = { task: string; owner: string; due: string | null };
export type Minutes = {
  title: string;
  held_on: string | null;
  place: string;
  attendees: number | null;
  agenda: { title: string; discussion: string; result: AgendaResult }[];
  decisions: string[];
  todos: Todo[];
  next_agenda: string[];
};
export type MinutesResult = { minutes: Minutes; text: string; method: "ai" | "rule" };

export const MIN_CHARS = 20;
export const MAX_CHARS = 20_000;

/** 회의록을 감사에 낼 수 있게 만드는 빈칸 알림 (할 일은 담당·기한이 있어야 다음 회의에서 확인된다) */
export function minutesChecks(m: Minutes): { ok: boolean; text: string }[] {
  const out: { ok: boolean; text: string }[] = [];
  if (!m.held_on) out.push({ ok: false, text: "회의 날짜가 없어요. 감사 제출용 회의록에는 일시가 있어야 해요." });
  const noOwner = m.todos.filter((t) => !t.owner).length;
  const noDue = m.todos.filter((t) => !t.due).length;
  if (noOwner) out.push({ ok: false, text: `담당이 정해지지 않은 할 일이 ${noOwner}건 있어요.` });
  if (noDue) out.push({ ok: false, text: `기한이 없는 할 일이 ${noDue}건 있어요.` });
  if (!out.length) out.push({ ok: true, text: m.todos.length ? "일시·담당·기한이 모두 적혀 있어요." : "일시가 적혀 있어요. 정리된 할 일은 없어요." });
  return out;
}

/** 할 일 중 법령 점검표로 이어지는 것 (개인정보 동의 문구 수정 → 개인정보 점검표) */
export const todoTopic = (t: Todo) => topicFor(t.task);
