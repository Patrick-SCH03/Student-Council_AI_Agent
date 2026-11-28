// 기획 도우미 데이터 모양과 순수 도우미 (네트워크 없음 — 단위 테스트가 바로 불러 쓴다).
// 금액·예비비·날짜는 서버가 계산한다 — 화면은 고친 값을 보내고 결과를 그대로 그린다.

import type { Block } from "./office/blocks.ts";
import type { BudgetDoc, Finding } from "./review-model";

// 재정·회계 세칙의 재원 구분 (api/app/plan/models.py FUNDS와 같게). 참가비는 재원이 아니라 지출에서 상계하는 사업 수입이다
export const FUNDS = ["학생회비", "교비지원금", "기금"] as const;
/** 지출 줄·단가·수량 상한 — 서버(api/app/plan/models.py)와 같게. 넘으면 서버가 거부한다 */
export const MAX_LINES = 20;
export const MAX_UNIT_PRICE = 10_000_000;
export const MAX_QTY = 10_000;

/** 고친 예산의 범위 문제 (보내기 전에 화면에서 알린다) */
export function budgetProblem(lines: EditLine[]): string | null {
  if (lines.some((l) => l.unit_price > MAX_UNIT_PRICE)) return "단가는 1,000만 원까지 적을 수 있어요.";
  if (lines.some((l) => l.qty > MAX_QTY)) return "수량은 10,000개까지 적을 수 있어요.";
  return null;
}
export type Fund = (typeof FUNDS)[number];

export type PlanInput = {
  title: string;
  org: string;
  purpose: string;
  target: string;
  headcount: number | null;
  start: string;
  end: string | null;
  place: string;
  fund: Fund;
  budget_cap: number | null;
  fee: number | null; // 참가비 1인 금액 — 예상 인원만큼 걷는다
  activities: string;
  meeting: string;
  meeting_date: string | null;
  term: string; // '제43대' — Word 표지 명의
};

export type Phase = "준비" | "진행" | "마무리";
export const PHASES: Phase[] = ["준비", "진행", "마무리"];
export type PlanStep = { phase: Phase; text: string; date: string };
export type EditLine = { item: string; unit_price: number; qty: number; unit: string; basis: string };
export type PlanLine = EditLine & { amount: number; evidence_kind: string; evidence: string[]; checklist: string | null };

export type Plan = {
  request: PlanInput;
  intent: string;
  steps: PlanStep[];
  expected: string[];
  cautions: string[];
  lines: PlanLine[];
  reserve: number;
  expense_total: number;
  over_cap: number;
  method: "ai" | "rule";
};

export type PlanResult = { plan: Plan; doc: BudgetDoc; text: string; findings: Finding[]; blocks: Block[] };

export type PlanEdit = Omit<Plan, "lines" | "expense_total" | "over_cap"> & { lines: EditLine[] };

/** 서버에 보내는 고친 안 — 계산 결과(금액·증빙)는 빼고 사람이 정하는 값만 */
export function toEdit(plan: Plan): PlanEdit {
  const { request, intent, steps, expected, cautions, reserve, method } = plan;
  const lines = plan.lines.map(({ item, unit_price, qty, unit, basis }) => ({ item, unit_price, qty, unit, basis }));
  return { request, intent, steps, expected, cautions, reserve, method, lines };
}

/** 서버 응답을 기다리는 동안 화면에 보일 합계 (서버가 다시 계산해 덮어쓴다) */
export function draftTotal(lines: EditLine[], reserve: number): number {
  return lines.reduce((sum, l) => sum + l.unit_price * l.qty, 0) + reserve;
}

/** 입력 칸 문제 (보내기 전에 화면에서 바로 보인다) */
export function inputProblem(p: PlanInput): string | null {
  if (!p.title.trim()) return "사업명을 적어 주세요.";
  if (!p.purpose.trim()) return "목적을 한 줄 이상 적어 주세요.";
  if (!p.start) return "시작일을 골라 주세요.";
  if (p.end && p.end < p.start) return "끝나는 날이 시작일보다 빨라요.";
  if (p.fee && !p.headcount) return "참가비를 적으면 예상 인원도 적어 주세요.";
  return null;
}
