// 정산 도우미 (브라우저 안에서만): 지출 목록 → 사업별 정산서 + 영수증 번호 + 예산 대비 차액.
// 근거: 총대 재무자료 매뉴얼의 영수증 번호 규격 '단위-(사업 순서)-(영수증 순서)', 사업별 정산서 열(계정·월·일·사업명·상세내용·금액·영수증번호),
// 재무 인수인계 메모 "예산보다 지출액이 적으면 사유 적어놓기". 네트워크 없음 — 단위 테스트가 바로 불러 쓴다.

import { josa } from "./format.ts";

export type Spend = { date: string; project: string; detail: string; amount: number; account: string };
export type Budget = { project: string; amount: number };

export type Row = Spend & { month: number; day: number; receipt: string };
export type ProjectSummary = {
  project: string;
  order: number;
  budget: number | null;
  spent: number;
  diff: number | null; // 예산 - 결산 (남으면 +, 넘으면 -)
  rows: Row[];
};
export type Issue = { level: "확인 필요" | "보완 필요"; text: string };

/** 표 붙여넣기 한 줄 → 칸. 엑셀·구글 시트는 탭으로, 손으로 쓴 줄은 쉼표나 두 칸 이상 공백으로 나눈다 */
export function splitCells(line: string): string[] {
  const sep = line.includes("\t") ? /\t/ : line.includes(",") && !/\d,\d{3}/.test(line) ? /,/ : /\s{2,}/;
  return line.split(sep).map((c) => c.trim());
}

const toAmount = (s: string) => {
  // '60만원'·'1만 5천원'·'2.5만원'도 읽는다 (파일럿: 만 단위로 적은 줄이 합계에서 빠졌다)
  // 만 뒤에 단위 없이 붙은 1~2자리('3만5'·'10만50')는 35,000인지 30,005인지 알 수 없어 읽지 않는다 — 못 읽은 줄로 알린다
  const man = s.replace(/[,\s]/g, "").match(/^(-?)(\d+(?:\.\d+)?)만(?:(\d+)천)?(\d*)원?$/);
  if (man) {
    if (man[4] && man[4].length < 3) return NaN;
    const n = Math.round(Number(man[2]) * 10_000 + Number(man[3] ?? 0) * 1_000 + Number(man[4] || 0));
    return man[1] ? -n : n;
  }
  const digits = s.replace(/[원,\s]/g, "");
  if (!digits || digits.includes(".")) return NaN; // 빈 칸을 0원으로, '1.500원'을 2원으로 읽지 않는다 (원은 소수가 없다)
  const n = Number(digits);
  return Number.isFinite(n) ? Math.round(n) : NaN;
};

/** '2025-05-28' · '25.05.28' · '5/28' · '5.28' · '5월 28일' → [월, 일]. 못 읽으면 null */
export function parseMonthDay(s: string): [number, number] | null {
  const t = s.trim();
  const m =
    t.match(/^(?:\d{2,4})[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})\.?$/) ?? t.match(/^(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?\.?$/);
  if (!m) return null;
  const month = Number(m[1]);
  const day = Number(m[2]);
  const days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]; // 없는 날짜(11/31)는 받지 않는다 (2월은 윤년을 모르니 29일까지)
  return month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1] ? [month, day] : null;
}

/** 붙여 넣은 지출 목록: 날짜 | 사업명 | 상세내용 | 금액 | (계정). 읽지 못한 줄 번호도 돌려준다 */
export function parseSpends(text: string): { spends: Spend[]; bad: number[] } {
  const spends: Spend[] = [];
  const bad: number[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    const [date = "", project = "", detail = "", amount = "", account = ""] = splitCells(line);
    const value = toAmount(amount);
    if (i === 0 && Number.isNaN(value) && !parseMonthDay(date)) return; // 머리글 줄
    if (!parseMonthDay(date) || !project || Number.isNaN(value)) {
      bad.push(i + 1);
      return;
    }
    spends.push({ date, project, detail, amount: value, account: account || "사업비" });
  });
  return { spends, bad };
}

/** 붙여 넣은 인준 예산: 사업명 | 금액. 칸이 애매하면('간식,385,000') 줄 끝의 금액을 떼어 읽고, 그래도 못 읽은 줄은 번호로 돌려준다 */
export function parseBudgets(text: string): { budgets: Budget[]; bad: number[] } {
  const budgets: Budget[] = [];
  const bad: number[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    const [project = "", amount = ""] = splitCells(line);
    let budget = { project, amount: toAmount(amount) };
    if (!line.includes("\t") && (!project || Number.isNaN(budget.amount))) {
      // 소수점은 '2.5만'처럼 만 앞에서만 받는다 ('1.500원'을 2원으로 읽지 않게)
      const m = line.trim().match(/^(.+?)[\s,]+(-?\d[\d,]*(?:(?:\.\d+)?만(?:\s*\d+천)?\d*)?)\s*원?$/);
      if (m) budget = { project: m[1].trim(), amount: toAmount(m[2]) };
    }
    if (budget.project && !Number.isNaN(budget.amount)) budgets.push(budget);
    else if (i > 0) bad.push(i + 1); // 첫 줄은 머리글일 수 있어 건너뛴다
  });
  return { budgets, bad };
}

const norm = (s: string) => s.replace(/\s+/g, "");

/** 한 사업 안의 정렬 열쇠: 그 사업의 줄이 모두 연도를 적었으면 연도까지, 아니면 학기가 해를 넘길 때(8월 이후와
 * 2월 이전이 섞임) 1·2월을 뒤로. 사업마다 따로 정해 다른 사업의 입력이 이미 매긴 번호를 바꾸지 않는다 */
function dateKey(spends: Spend[]): (s: Spend) => number {
  const yearOf = (s: Spend) => s.date.trim().match(/^(\d{2,4})[-./]\s*\d{1,2}[-./]/)?.[1];
  const allYears = spends.every((s) => yearOf(s));
  const months = spends.map((s) => parseMonthDay(s.date)?.[0] ?? 0);
  const wraps = months.some((m) => m >= 8) && months.some((m) => m >= 1 && m <= 2);
  return (s) => {
    const [m, d] = parseMonthDay(s.date) as [number, number];
    if (allYears) return (Number(yearOf(s)) % 100) * 10000 + m * 100 + d;
    return (wraps && m <= 2 ? m + 12 : m) * 100 + d;
  };
}

/** 사업 순서는 인준 예산에 적힌 순서, 예산에 없는 사업은 그 뒤에 처음 나온 순서. 영수증은 사업 안에서 날짜순 */
export function settle(unit: string, spends: Spend[], budgets: Budget[]): ProjectSummary[] {
  const names: string[] = [];
  const seen = new Set<string>();
  for (const p of [...budgets.map((b) => b.project), ...spends.map((s) => s.project)]) {
    if (!seen.has(norm(p))) {
      seen.add(norm(p));
      names.push(p);
    }
  }
  const prefix = unit.trim() ? `${unit.trim()}-` : "";
  return names.map((project, i) => {
    const order = i + 1;
    const own = spends.filter((s) => norm(s.project) === norm(project));
    const key = dateKey(own);
    const mine = own
      .sort((a, b) => key(a) - key(b))
      .map((s) => {
        const [month, day] = parseMonthDay(s.date) as [number, number];
        return { ...s, month, day };
      });
    const rows = mine.map((s, j) => ({ ...s, receipt: `${prefix}${order}-${j + 1}` }));
    const budget = budgets.find((b) => norm(b.project) === norm(project))?.amount ?? null;
    const spent = rows.reduce((sum, r) => sum + r.amount, 0);
    return { project, order, budget, spent, diff: budget == null ? null : budget - spent, rows };
  });
}

export function settleIssues(summary: ProjectSummary[], spends: Spend[]): Issue[] {
  const issues: Issue[] = [];
  for (const p of summary) {
    if (p.budget == null && p.rows.length) issues.push({ level: "보완 필요", text: `${josa(`'${p.project}'`, "은", "는")} 인준 예산에 없는 사업이에요. 사업명을 예산과 같게 맞추거나 인준 여부를 확인해 주세요.` });
    else if (p.diff != null && p.diff < 0) issues.push({ level: "보완 필요", text: `'${p.project}' 지출이 예산보다 ${(-p.diff).toLocaleString("ko-KR")}원 많아요. 예비비 사용·추경 인준 근거를 붙여 주세요.` });
    else if (p.diff != null && p.diff > 0 && p.rows.length) issues.push({ level: "확인 필요", text: `${josa(`'${p.project}'`, "은", "는")} 예산보다 ${p.diff.toLocaleString("ko-KR")}원 적게 썼어요. 정산서 비고에 사유를 적어 두세요.` });
    else if (p.budget != null && !p.rows.length) issues.push({ level: "확인 필요", text: `'${p.project}' 지출 기록이 없어요. 사업을 하지 않았다면 사유를 적어 두세요.` });
  }
  const keys = new Map<string, number>();
  for (const s of spends) {
    const key = `${parseMonthDay(s.date)?.join(".")}|${norm(s.project)}|${s.amount}`;
    keys.set(key, (keys.get(key) ?? 0) + 1);
  }
  for (const [key, n] of keys) {
    if (n > 1) {
      const [md, , amount] = key.split("|");
      issues.push({ level: "확인 필요", text: `${md} ${Number(amount).toLocaleString("ko-KR")}원 지출이 ${n}번 있어요. 중복으로 적었는지 확인해 주세요.` });
    }
  }
  if (spends.some((s) => s.amount <= 0)) issues.push({ level: "확인 필요", text: "0원 이하 금액이 있어요. 환불은 지출에서 빼지 말고 수입(환불금)으로 따로 적어요." });
  return issues;
}

/** 엑셀에 붙여 넣을 탭 구분 표 (사업별 정산서 열 순서) */
export function settleTsv(summary: ProjectSummary[]): string {
  const out = [["계정", "월", "일", "사업명", "상세내용", "금액", "영수증번호"].join("\t")];
  for (const p of summary) {
    for (const r of p.rows) out.push([r.account, r.month, r.day, p.project, r.detail, r.amount, r.receipt].join("\t"));
    if (p.rows.length) out.push(["", "", "", `${p.project} 합계`, "", p.spent, ""].join("\t"));
  }
  return out.join("\n");
}
