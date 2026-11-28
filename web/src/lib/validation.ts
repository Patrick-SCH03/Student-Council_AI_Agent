// 서버 검증 오류(422)를 화면 문구로 — 영어 원문(pydantic msg)은 보이지 않는다. 네트워크 없음, 단위 테스트가 바로 불러 쓴다.

import { josa } from "./format.ts";

/** 칸 이름 — 서버 필드 이름을 화면 이름으로 */
const FIELD_LABEL: Record<string, string> = {
  title: "사업명", org: "기구", purpose: "목적", target: "대상", place: "장소", activities: "주요 활동",
  meeting: "인준 회의", filename: "파일 이름", text: "본문", item: "항목", reason: "사유", to: "수신자",
  start: "시작일", end: "끝나는 날", headcount: "예상 인원", budget_cap: "예산 상한", fee: "참가비", meeting_date: "인준 회의일", term: "대수",
  lines: "지출 항목", note: "비고", held_on: "회의 날짜",
};

export function validationText(err: { type?: string; msg?: string; loc?: unknown[]; ctx?: Record<string, unknown> } | undefined): string | null {
  if (!err) return null;
  if (err.msg?.startsWith("Value error, ")) return err.msg.slice("Value error, ".length); // 서버가 직접 쓴 한국어 안내
  const key = [...(err.loc ?? [])].reverse().find((x) => typeof x === "string" && x !== "body" && x !== "query") as string | undefined;
  const field = (key && FIELD_LABEL[key]) || "입력";
  const max = err.ctx?.max_length;
  if (err.type === "string_too_long" && max) return `${josa(field, "은", "는")} ${max}자까지 적을 수 있어요.`;
  if (err.type === "too_long" && max) return `${josa(field, "은", "는")} ${max}개까지 넣을 수 있어요.`;
  if (err.type === "string_too_short" || err.type === "missing") return `${josa(field, "을", "를")} 채워 주세요.`;
  if (err.type?.startsWith("greater_than") || err.type?.startsWith("less_than")) return `${field}의 숫자 범위를 확인해 주세요.`;
  return "입력한 값을 확인해 주세요.";
}
