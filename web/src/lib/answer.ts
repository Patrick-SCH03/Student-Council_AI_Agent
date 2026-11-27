// 답변 머리표(위험도 배지 / 질문 유형) 판단 — 배지·복사 문구·스크린리더 알림·분석 카드가 같은 규칙을 쓴다.

import type { ChatResult, ReviewerResult } from "./api";

// 위험도는 사용자의 행위를 평가한 값이다. 기준·절차나 과거 기록만 묻는 질문은 늘 '낮음'이라
// 배지가 정보를 주지 못하고, 단순 문의를 위험 평가처럼 보이게 한다 — 그때는 질문 유형을 보여준다.
const QUESTION_TYPE_LABEL: Record<string, string> = {
  "기준·절차": "규정 안내",
  "기록 조회": "감사 기록 조회",
};

/**
 * 위험도 대신 보여줄 질문 유형 라벨. 위험도를 보여줘야 하면 null —
 * 유형이 없는 옛 답변, 행위 질문, 알 수 없는 유형, 그리고 감사 분석이 처분 가능성을 높게 봐
 * 위험도가 '낮음'이 아닌 답변(질문 유형과 관계없이 숨기지 않는다).
 */
export function questionTypeLabel(
  reviewer: Pick<ReviewerResult, "question_type"> | null | undefined,
  riskLevel: string | null | undefined,
): string | null {
  const label = QUESTION_TYPE_LABEL[reviewer?.question_type ?? ""];
  return label && riskLevel === "낮음" ? label : null;
}

/** 답변 머리표: "위험도 높음" 또는 "규정 안내" 같은 질문 유형. 위험도가 없는 답(범위 밖 안내)은 null. */
export function answerLabel(result: Pick<ChatResult, "risk_level" | "reviewer">): string | null {
  if (!result.risk_level) return null;
  return questionTypeLabel(result.reviewer, result.risk_level) ?? `위험도 ${result.risk_level}`;
}
