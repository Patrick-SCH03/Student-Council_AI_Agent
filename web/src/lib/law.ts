// 법령 점검표 '더 물어보기' — 서버가 법제처 법령 MCP로 조문을 찾아 답하고, 인용 조문을 원문과 대조해 돌려준다 (유료, 하루 한도)

import { postJson } from "./http";

export type LawCitation = { text: string; url: string; effective: string };
export type LawAnswer = { answer: string; citations: LawCitation[]; verified: boolean };
export type LawTurn = { q: string; a: string };

export const askLaw = (question: string, topic: string, history: LawTurn[]) =>
  postJson<LawAnswer>(
    "/api/law/ask",
    // 직전 3턴만, 답은 서버 길이 제한(1800자)에 맞춰 자른다
    { question: question.trim(), topic, history: history.slice(-3).map((t) => ({ q: t.q.slice(0, 500), a: t.a.slice(0, 1800) })) },
    "법령을 찾지 못했어요. 잠시 뒤 다시 시도해 주세요.",
  );

/** 주제별로 점검표에 없지만 자주 나올 만한 질문 — 빈 칸에서 눌러 바로 물어본다 */
export const SAMPLE_QUESTIONS: Record<string, string[]> = {
  fee: ["외부 강사에게 교통비만 따로 주면 그것도 세금을 떼야 하나요?", "상품권으로 상금을 주면 원천징수는 어떻게 하나요?"],
  privacy: ["행사 사진을 인스타그램에 올리려면 동의를 받아야 하나요?", "참가 신청서 개인정보는 행사 끝나고 언제까지 지워야 하나요?"],
  liquor: ["축제 주점에서 학생에게 술을 팔려면 어떤 신고가 필요한가요?", "먹거리 부스에서 직접 조리한 음식을 팔아도 되나요?"],
  sponsor: ["외부 업체 협찬금을 받으면 세금 문제가 있나요?", "협찬 대가로 업체 로고를 현수막에 넣어도 되나요?"],
  copyright: ["축제에서 유튜브 음원을 틀어도 되나요?", "학과 굿즈에 캐릭터 그림을 넣으려면 무엇을 확인해야 하나요?"],
  groupbuy: ["과잠 공동구매 대금을 학생회 계좌로 받아도 되나요?", "공동구매 물품이 불량이면 환불 책임은 누구에게 있나요?"],
  safety: ["야외 공연에 관객이 1,000명 넘으면 신고해야 하나요?", "축제 부스에서 가스버너를 써도 되나요?"],
};
