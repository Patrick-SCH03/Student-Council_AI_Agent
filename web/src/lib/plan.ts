// 기획 도우미 API 클라이언트.

import { postJson } from "./http";
import type { PlanEdit, PlanInput, PlanResult } from "./plan-model";

export * from "./plan-model";

export const draftPlan = (input: PlanInput, contribute = false) =>
  postJson<PlanResult>(
    `/api/plan/draft${contribute ? "?contribute=true" : ""}`,
    input,
    "초안을 만들지 못했어요. 잠시 후 다시 시도해 주세요.",
  );

/** 개요 칸 하나(목적·주요 활동)의 AI 초안. 지금까지 적은 개요를 함께 보낸다 (유료, 하루 한도) */
export const suggestPlanField = async (field: "purpose" | "activities", input: PlanInput): Promise<string> => {
  const { title, org, purpose, target, headcount, place, fund, budget_cap, fee, activities } = input;
  const body = { field, title: title.trim(), org, purpose, target, headcount, place, fund, budget_cap, fee, activities };
  const out = await postJson<{ text: string }>("/api/plan/suggest", body, "AI 초안을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요.");
  return out.text;
};

export const rebuildPlan = (edit: PlanEdit) => postJson<PlanResult>("/api/plan/rebuild", edit, "다시 계산하지 못했어요.");
