// 감사 대비 자가진단 — 모두 브라우저 안에서 계산한다 (파일 이름·답변을 서버로 보내지 않음).
// 근거: 중앙감사특별위원회 제출자료 13종 요청 공문(2024), 2024-1 중앙 정기감사 결과보고서의 반복 처분 유형.
// 조항 번호는 확인하지 못한 것은 적지 않고, '규정 질문'으로 원문을 찾게 한다.

export type Question = { id: string; text: string; risky: "yes" | "no"; why: string; todo: string; ask: string };

/** 예/아니오 질문. risky가 위험한 답이다. */
export const QUESTIONS: Question[] = [
  {
    id: "appoint",
    text: "새 임원·국장 임명을 사령으로 공개했나요?",
    risky: "no",
    why: "사령공개를 하지 않아 정직 건의를 받은 단위가 한 학기에 4곳 있었어요.",
    todo: "임면 사항을 공고문으로 게시하고 게시 날짜를 남겨요.",
    ask: "임원을 임명하면 사령공개를 해야 하나요?",
  },
  {
    id: "resolution",
    text: "급대표·부장 결의서를 총회 자료에 빠짐없이 넣었나요?",
    risky: "no",
    why: "결의서를 총회 자료에서 빠뜨려 처분을 받은 사례가 있어요.",
    todo: "임명된 사람 전원의 결의서가 인준 자료에 있는지 대조해요.",
    ask: "급대표 결의서는 어디에 제출해야 하나요?",
  },
  {
    id: "personal-card",
    text: "임원 개인카드로 먼저 결제하고 공금에서 돌려받은 적이 있나요?",
    risky: "yes",
    why: "개인카드 결제 뒤 이체한 2개 단위가 처분을 받았어요.",
    todo: "앞으로는 학생회 카드·계좌로만 결제하고, 이미 있었다면 경위서를 준비해요.",
    ask: "개인카드로 결제하고 학생회비로 돌려받아도 되나요?",
  },
  {
    id: "receipt-owner",
    text: "공금 결제 때 개인 현금영수증·포인트·스탬프를 적립했나요?",
    risky: "yes",
    why: "공금 결제에 개인 혜택을 적립해 처분받은 단위가 3곳 있었어요.",
    todo: "현금영수증은 지출증빙(사업자)으로, 포인트는 적립하지 않아요.",
    ask: "학생회비로 결제할 때 개인 포인트를 적립해도 되나요?",
  },
  {
    id: "account-mix",
    text: "학생회 돈을 개인 통장에 넣거나, 기금 통장과 개인 통장을 섞어 쓴 적이 있나요?",
    risky: "yes",
    why: "통장을 섞어 쓰거나 직무대행 시기에 전임자 통장으로 환불해 처분받은 사례가 있어요.",
    todo: "모든 수입·지출을 공금전용계좌로 모으고 거래내역서를 남겨요.",
    ask: "학생회비를 개인 통장으로 받아도 되나요?",
  },
  {
    id: "reserve-over",
    text: "예비비보다 더 쓰거나, 인준받은 금액을 넘겨 쓴 사업이 있나요?",
    risky: "yes",
    why: "380원·13,040원처럼 적은 금액 초과도 처분 사유가 됐어요.",
    todo: "초과분은 예산 변경 사유서를 쓰고 대의원회 승인을 받아요.",
    ask: "예비비를 초과해서 집행하면 어떤 처분을 받나요?",
  },
  {
    id: "no-plan",
    text: "사업안 인준 없이 진행한 사업이 있나요?",
    risky: "yes",
    why: "인준 전 집행은 예산집행정지 같은 처분으로 이어질 수 있어요.",
    todo: "사후라도 경위를 정리하고 다음 총회에 보고해요.",
    ask: "인준 전에 사업 예산을 집행하면 어떻게 되나요?",
  },
  {
    id: "own-money",
    text: "사비로 낸 뒤 나중에 처리하려는 지출이 있나요?",
    risky: "yes",
    why: "사비 처리 허가를 요청했다가 '허가 대상이 아니며 감사처분 사유가 될 수 있다'는 회신을 받은 사례가 있어요.",
    todo: "사비 지출은 만들지 않는 게 원칙이에요. 이미 있었다면 경위서를 준비해요.",
    ask: "사비로 결제한 금액을 학생회비로 돌려받을 수 있나요?",
  },
  {
    id: "minutes",
    text: "회의록·운영일지를 회의할 때마다 남겼나요?",
    risky: "no",
    why: "감사 직전에 몰아서 쓰면 날짜·내용이 어긋나기 쉬워요.",
    todo: "남은 회의는 그날 바로 기록하고, 빠진 회의는 참석자 확인을 받아 정리해요.",
    ask: "감사 때 회의록은 어떤 형식으로 내야 하나요?",
  },
  {
    id: "contract",
    text: "업체·대관 계약서와 견적서를 보관하고 있나요?",
    risky: "no",
    why: "계약서는 감사 제출자료 13종에 들어가요.",
    todo: "계약서·견적서·거래명세서를 사업별로 모아 둬요.",
    ask: "학생회 계약서는 얼마나 보관해야 하나요?",
  },
  {
    id: "deadline",
    text: "감사자료 제출 기한을 알고 있나요?",
    risky: "no",
    why: "기한을 3주 넘겨 정직 42일 건의를 받은 사례가 있어요.",
    todo: "감사특별위원회 공문에서 기한을 확인하고 일주일 전까지 모아 둬요.",
    ask: "감사자료 제출 기한을 넘기면 어떤 처분을 받나요?",
  },
];

export type Answer = "yes" | "no" | "na";

export function riskyQuestions(answers: Record<string, Answer>): Question[] {
  return QUESTIONS.filter((q) => answers[q.id] === q.risky);
}

/** 감사 제출자료 13종과 파일 이름에서 찾을 낱말 */
export const SUBMISSIONS: { id: string; name: string; keywords: string[] }[] = [
  { id: "plan", name: "사업계획서", keywords: ["사업계획", "사업안", "계획서"] },
  { id: "eval", name: "사업평가서", keywords: ["평가서", "사업평가", "결과보고"] },
  { id: "settle", name: "정산서", keywords: ["정산", "결산"] },
  { id: "minutes", name: "회의록·운영일지", keywords: ["회의록", "운영일지", "업무일지", "회의"] },
  { id: "receipts", name: "영수증철", keywords: ["영수증", "전표", "거래명세", "카드매출"] },
  { id: "ledger", name: "금전출납부", keywords: ["출납", "장부", "가계부"] },
  { id: "bank", name: "통장 원본·사본", keywords: ["통장", "거래내역", "계좌", "잔고"] },
  { id: "contract", name: "계약서", keywords: ["계약", "견적"] },
  { id: "pledge", name: "공약평가서", keywords: ["공약"] },
  { id: "publication", name: "간행물", keywords: ["간행물", "카드뉴스", "포스터", "자료집"] },
  { id: "sent", name: "발송공문철", keywords: ["발송", "발신"] },
  { id: "received", name: "수령공문철", keywords: ["수령", "수신", "접수"] },
  { id: "etc", name: "기타", keywords: ["기타", "기구표"] },
];

export function matchSubmissions(fileNames: string[]): Record<string, string[]> {
  const found: Record<string, string[]> = Object.fromEntries(SUBMISSIONS.map((s) => [s.id, []]));
  for (const raw of fileNames) {
    const name = raw.replace(/\s+/g, "");
    if (!name) continue;
    for (const s of SUBMISSIONS) {
      if (s.keywords.some((k) => name.includes(k))) found[s.id].push(raw.trim());
    }
  }
  return found;
}

export type NameWarning = { file: string; reason: string };

const NAME_RULES: [RegExp, string][] = [
  [/ㅅㅂ|ㅆㅂ|시발|씨발|ㅈㄹ|지랄|병신|ㅂㅅ|존나|ㅈㄴ|개새/, "비속어가 있어요 — 감사 처분으로 이어진 전례가 있어요"],
  [/비번|비밀번호|password|passwd|\bpw\b|\bpwd\b/i, "비밀번호로 보이는 내용이 있어요"],
  [/01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}/, "전화번호가 있어요"],
  [/(?<!\d)1\d{7}(?!\d)/, "학번으로 보이는 8자리 숫자가 있어요"],
  [/(?<![\d-])\d{2,6}-\d{2,6}-\d{2,8}(?![\d-])/, "계좌번호로 보이는 숫자가 있어요"],
  [/주민|\d{6}-[1-4]\d{6}/, "주민등록번호로 보이는 내용이 있어요"],
];

export function nameWarnings(fileNames: string[]): NameWarning[] {
  const out: NameWarning[] = [];
  for (const raw of fileNames) {
    const file = raw.trim();
    if (!file) continue;
    // 날짜(2025-11-13, 20251113)는 계좌·학번처럼 보이므로 지우고 검사한다
    const body = file.replace(/(?:19|20)\d{2}[-.]?\d{2}[-.]?\d{2}/g, " ");
    for (const [re, reason] of NAME_RULES) {
      if (re.test(body)) out.push({ file, reason });
    }
  }
  return out;
}

/** 내용까지 점검할 문서: 금액이 들어가는 사업계획서·예산·정산·결산 문서 중 문서 검토가 읽는 형식만, 많아야 8개 */
export const CONTENT_KEYWORDS = ["사업계획", "사업안", "계획서", "예산", "정산", "결산"];
const CONTENT_EXT = [".pdf", ".hwp", ".hwpx", ".docx", ".xlsx"];
export const MAX_CONTENT_FILES = 8;

export function contentTargets<T extends { path: string; size: number }>(files: T[], maxBytes: number): T[] {
  return files
    .filter((f) => {
      const name = f.path.toLowerCase();
      const base = name.split("/").pop() ?? name;
      return (
        CONTENT_EXT.some((e) => base.endsWith(e)) &&
        f.size <= maxBytes &&
        CONTENT_KEYWORDS.some((k) => name.replace(/\s+/g, "").includes(k))
      );
    })
    .slice(0, MAX_CONTENT_FILES);
}
