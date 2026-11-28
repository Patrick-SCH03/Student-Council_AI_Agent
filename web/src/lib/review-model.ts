// 문서 검토 데이터 모양과 순수 도우미 (네트워크 없음 — 단위 테스트가 바로 불러 쓴다).

export type Level = "위반 소지" | "보완 필요" | "확인 필요";
export const LEVELS: Level[] = ["위반 소지", "보완 필요", "확인 필요"];

export type Line = { item: string; amount: number | null; note: string };
export type Headcount = { label: string; counts: number[]; unit_prices: number[]; stated_amount: number | null };
export type EventDate = { label: string; start: string | null; end: string | null; text: string };

export type BudgetDoc = {
  title: string;
  org: string;
  meeting: string;
  meeting_date: string | null;
  written_date: string | null;
  event_dates: EventDate[];
  income: Line[];
  income_total: number | null;
  expense: Line[];
  expense_total: number | null;
  summary_income: number | null;
  summary_expense: number | null;
  balance: number | null;
  headcounts: Headcount[];
};

export type Finding = { code: string; level: Level; title: string; detail: string; basis: string; where: string };

export type Extracted = {
  doc: BudgetDoc;
  method: "ai" | "rule";
  kind: "pdf" | "xlsx" | "hwp" | "hwpx" | "docx";
  pages: number;
  text: string;
  source: Finding[];
  contribution_id: number | null;
};

// 서버(api/app/review/extract.py)와 같은 목록. 예전 형식 .xls·.doc는 읽지 못한다
const ACCEPT = [".pdf", ".hwp", ".hwpx", ".docx", ".xlsx"];
export const ACCEPT_ATTR = ACCEPT.join(",");
export const MAX_BYTES = 15 * 1024 * 1024;

/** 올리기 전에 화면에서 거른다 (서버도 같은 검사를 한다) */
export function fileProblem(file: File): string | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".xls") || name.endsWith(".doc"))
    return "예전 형식(.xls·.doc)은 읽지 못해요. 새 형식(.xlsx·.docx)이나 PDF로 저장해 올려 주세요.";
  if (!ACCEPT.some((ext) => name.endsWith(ext))) return "PDF·한글·워드·엑셀 파일만 올릴 수 있어요.";
  if (file.size > MAX_BYTES) return "파일이 너무 커요. 15MB 이하로 올려 주세요.";
  return null;
}

export { won } from "./format.ts";

/** "5,698,191원" 같은 입력을 숫자로. 비우면 null */
export function parseWon(text: string): number | null {
  const digits = text.replace(/[^\d]/g, "");
  if (!digits) return null;
  // 차액처럼 음수가 될 수 있는 칸 — 앞의 마이너스는 지키고 나머지 기호만 지운다
  return /^\s*[-−]/.test(text) ? -Number(digits) : Number(digits);
}

/** 점검 결과를 메신저에 붙여 넣기 좋은 글로 */
export function reportText(title: string, findings: Finding[]): string {
  const lines = [`[문서 점검] ${title}`, `점검 사항 ${findings.length}건`, ""];
  findings.forEach((f, i) => {
    lines.push(`${i + 1}. [${f.level}] ${f.title}`);
    if (f.detail) lines.push(`   ${f.detail}`);
    if (f.basis) lines.push(`   근거: ${f.basis}`);
  });
  lines.push("", "AI 점검은 참고용이며 인준·감사 판단을 대신하지 않아요.");
  return lines.join("\n");
}

/** 글에서 이어질 법령 점검표 주제 (없으면 null). '술'만으로는 '기술'도 걸려 주류는 낱말로 본다 */
export function topicFor(text: string): string | null {
  if (/sensitive|개인정보|학번|연락처|질환/.test(text)) return "privacy";
  if (/cash|사례금|상금|수당|원천징수/.test(text)) return "fee";
  if (/주류|주점|소주|맥주|막걸리|먹거리|조리|보건증/.test(text)) return "liquor";
  if (/상영|영화|음원|저작권|폰트/.test(text)) return "copyright";
  if (/공동구매|과잠|단체복|굿즈/.test(text)) return "groupbuy";
  if (/후원|협찬|제휴/.test(text)) return "sponsor";
  return null;
}

/** 점검 사항과 이어지는 법령 점검표 주제 */
export const checklistTopic = (f: Finding) => topicFor(`${f.code} ${f.title}`);
