// 문서 작성 도우미 — 양식 채우기와 숫자 검산. 모두 브라우저 안에서 계산한다(이름·학번·서명 칸은 비워 둔다).
// 근거: 학생회 드라이브의 지급확인서 4종·경위서·예산 변경 사유서·공문 실물(2026-11-28 조사), 「재정·회계 세칙」 제16조·제31조·제32조.

import { josa, won } from "./format.ts";

export type Check = { ok: boolean; text: string };

/** 오늘 날짜 YYYY-MM-DD (브라우저 시간대 기준 — toISOString은 UTC라 한국 자정~오전 9시에 하루 전이 된다) */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}


/* ---------------------------------------------------------------- 지급확인서 */

export type PaymentInput = {
  event: string;
  reason: string; // 심판 수당·상금·사례금·경품
  method: "계좌이체" | "상품권" | "현금";
  people: number;
  unit: number;
  times: number;
};

export function paymentChecks(p: PaymentInput): Check[] {
  const per = p.unit * p.times;
  const out: Check[] = [{ ok: true, text: `1인 ${won(per)} × ${p.people}명 = 합계 ${won(per * p.people)}` }];
  if (p.method === "현금") {
    out.push(
      per > 150_000
        ? { ok: false, text: "1인 15만 원을 넘으면 현금으로 줄 수 없어요(「재정·회계 세칙」 제31조 제3항). 계좌이체로 바꿔요." }
        : { ok: true, text: "현금이면 사전 승인과 수령인 성명·연락처가 적힌 수령증이 필요해요(제32조 제3항 제7호)." },
    );
  }
  if (/사례|강사|멘토|심판|수당/.test(p.reason) && per > 125_000) {
    out.push({ ok: false, text: "1인 125,000원을 넘는 사례금은 원천징수 대상일 수 있어요. 법령 점검표에서 확인해요." });
  }
  if (/상금|시상/.test(p.reason) && per > 250_000) {
    out.push({ ok: false, text: "1인 250,000원을 넘는 대회 상금은 원천징수 대상일 수 있어요. 법령 점검표에서 확인해요." });
  }
  // 대회 시상 경품은 위의 상금 규칙(필요경비 80%)을 따른다 — 추첨으로 주는 경품만
  // ('체육대회 경품'은 대부분 추첨이라 '대회'만으로는 빼지 않는다 — Fable 리뷰)
  if ((/추첨/.test(p.reason) || (/경품/.test(p.reason) && !/상금|시상/.test(p.reason))) && per > 50_000) {
    // 추첨 경품은 필요경비 의제가 없어 5만 원을 넘으면 전액 과세 (소득세법 제21조 제1항 제2호·제84조 제3호·제129조 제1항 제6호 라목)
    out.push({ ok: false, text: "추첨으로 주는 경품이 1인 5만 원을 넘으면 전액의 20%(지방소득세 별도) 원천징수 대상일 수 있어요. 법령 점검표에서 확인해요." });
  }
  return out;
}

export function paymentText(p: PaymentInput): string {
  const per = p.unit * p.times;
  const rows = Array.from(
    { length: Math.max(p.people, 1) },
    (_, i) => `${i + 1} |        |            |              | ${won(per)} |      `,
  );
  return [
    `지급 확인서`,
    ``,
    `행사명: ${p.event || "○○ 행사"}`,
    `지급 사유: ${p.reason || "○○"} (1인 ${won(p.unit)} × ${p.times}회)`,
    `지급 방법: ${p.method}`,
    `합계: ${won(per * p.people)} (${p.people}명)`,
    ``,
    `번호 | 성명 | 학과(소속) | 연락처 | 금액 | 서명`,
    ...rows,
    ``,
    `위 금액을 정히 수령하였음을 확인합니다.`,
    `20  .   .   .`,
  ].join("\n");
}

/* ---------------------------------------------------------------- 경위서 */

export type ItemRow = { name: string; qty: number; unit: number };

export function rowsTotal(rows: ItemRow[]): number {
  return rows.reduce((sum, r) => sum + r.qty * r.unit, 0);
}

export type IncidentInput = { date: string; what: string; causes: string[]; rows: ItemRow[]; stated: number | null; followUp: string };

export const CAUSES = ["가격 변동", "중복 결제", "수량 변경", "담당자 간 전달 누락", "환불·오입금"];

export function incidentChecks(c: IncidentInput): Check[] {
  const total = rowsTotal(c.rows);
  const out: Check[] = [{ ok: true, text: `금액표 합계 ${won(total)}` }];
  if (c.stated != null && c.stated !== total) {
    out.push({ ok: false, text: `적은 금액 ${won(c.stated)}이 금액표 합계와 ${won(Math.abs(c.stated - total))} 달라요.` });
  }
  if (!c.followUp.trim()) out.push({ ok: false, text: "재발 방지·후속 조치를 적어 주세요." });
  return out;
}

export function incidentText(c: IncidentInput): string {
  const lines = c.rows
    .filter((r) => r.name.trim())
    .map((r, i) => `  ${i + 1}) ${r.name}: ${r.qty.toLocaleString("ko-KR")} × ${won(r.unit)} = ${won(r.qty * r.unit)}`);
  return [
    `경위서`,
    ``,
    `1. 발생일: ${c.date || "20  .  .  ."}`,
    `2. 경위: ${c.what || "○○"}`,
    `3. 원인: ${c.causes.length ? c.causes.join(", ") : "○○"}`,
    `4. 관련 금액`,
    ...(lines.length ? lines : ["  1) ○○"]),
    `  합계: ${won(rowsTotal(c.rows))}`,
    `5. 후속 조치: ${c.followUp || "○○"}`,
    ``,
    `위와 같이 경위를 보고합니다.`,
    `20  .   .   .        작성자:            (서명)`,
  ].join("\n");
}

/* ---------------------------------------------------------------- 예산 변경 사유서 */

export type ChangeInput = { item: string; approved: number; spent: number; reserve: number; budgetTotal: number; reason: string };

export function changeNumbers(c: ChangeInput) {
  const over = c.spent - c.approved;
  return { over, reserveLeft: c.reserve - Math.max(over, 0) };
}

/** 예비비 사용 줄: 남으면 '남은 예비비', 모자라면 '예비비 초과' (음수 금액을 적지 않는다) */
export function reserveUse(c: ChangeInput): string {
  const { over, reserveLeft } = changeNumbers(c);
  const left = reserveLeft >= 0 ? `남은 예비비 ${won(reserveLeft)}` : `예비비 초과 ${won(-reserveLeft)}`;
  return `${won(over)} (편성 ${won(c.reserve)}, ${left})`;
}

export function changeChecks(c: ChangeInput): Check[] {
  const { over, reserveLeft } = changeNumbers(c);
  const out: Check[] = [];
  if (over <= 0) {
    out.push({ ok: true, text: `인준 금액 안에서 집행했어요 (남은 금액 ${won(-over)}).` });
    return out;
  }
  out.push({ ok: true, text: `초과 ${won(c.spent)} − ${won(c.approved)} = ${won(over)}` });
  out.push(
    reserveLeft >= 0
      ? { ok: true, text: `예비비 ${won(c.reserve)} − ${won(over)} = 남은 예비비 ${won(reserveLeft)}` }
      : { ok: false, text: `초과액이 예비비를 ${won(-reserveLeft)} 넘어요. 예비비 초과 집행은 처분 사유가 된 사례가 있어요.` },
  );
  if (c.budgetTotal > 0 && c.reserve * 10 > c.budgetTotal) {
    out.push({ ok: false, text: `예비비가 사업 예산의 10%(${won(c.budgetTotal / 10)})를 넘어요(「재정·회계 세칙」 제16조).` });
  }
  return out;
}

export function changeText(c: ChangeInput): string {
  const { over } = changeNumbers(c);
  return [
    `예산 변경 사유서`,
    ``,
    `1. 항목: ${c.item || "○○"}`,
    `2. 인준 금액: ${won(c.approved)}`,
    `3. 실제 집행 금액: ${won(c.spent)}`,
    `4. ${over > 0 ? `초과 금액: ${won(over)}` : `남은 금액: ${won(-over)}`}`,
    ...(over > 0 ? [`5. 예비비 사용: ${reserveUse(c)}`] : []),
    `${over > 0 ? 6 : 5}. 변경 사유: ${c.reason || "○○"}`,
    ``,
    `위와 같은 사유로 예산 변경을 보고합니다.`,
  ].join("\n");
}

/* ---------------------------------------------------------------- 공문 */

export type LetterInput = {
  number: string;
  date: string; // YYYY-MM-DD
  to: string;
  cc: string;
  title: string;
  body: string;
  attachments: string;
  from: string;
  drafter?: string; // 기안자 직위·이름 (예: 수석집행국장 홍길동)
  contact?: string; // 꼬리 연락처 한 줄 (주소·전화·이메일)
};

export function letterChecks(l: LetterInput): Check[] {
  const out: Check[] = [];
  const year = l.date.slice(0, 4);
  const numberYear = l.number.match(/20\d{2}/)?.[0];
  if (year && numberYear && numberYear !== year)
    out.push({ ok: false, text: `문서번호 연도(${numberYear})가 시행일 연도(${year})와 달라요.` });
  const bodyYears = [...l.body.matchAll(/(20\d{2})\s*[.년-]/g)].map((m) => m[1]);
  const odd = bodyYears.filter((y) => year && y < year);
  if (odd.length)
    out.push({ ok: false, text: `본문에 지난 연도(${[...new Set(odd)].join(", ")})가 있어요. 복사하면서 남은 건 아닌지 확인해요.` });
  if (!l.title.trim()) out.push({ ok: false, text: "제목을 적어 주세요." });
  if (/사비/.test(l.title + l.body)) {
    out.push({
      ok: false,
      text: "사비 처리 허가 요청은 '허가 대상이 아니며 감사처분 사유가 될 수 있다'는 회신을 받은 사례가 있어요. 규정 질문으로 먼저 확인해요.",
    });
  }
  if (!out.length) out.push({ ok: true, text: "연도·제목에 문제가 보이지 않아요." });
  return out;
}

/* ---------------------------------------------------------------- 사령 공고 */
// 사령공개를 하지 않아 한 학기에 4개 단위가 처분을 받았다(2024-1 중앙 정기감사). 임면 공고문을 바로 만든다.

export type AppointRow = { kind: "임명" | "사의수리"; role: string; name: string };
export type AppointInput = { org: string; date: string; rows: AppointRow[]; head: string };

export function appointChecks(a: AppointInput, org = ""): Check[] {
  const filled = a.rows.filter((r) => r.role.trim() && r.name.trim());
  const out: Check[] = [];
  if (!filled.length) out.push({ ok: false, text: "임면할 사람을 한 명 이상 적어 주세요." });
  if (!a.date) out.push({ ok: false, text: "효력 발생일을 적어 주세요." });
  const unit = a.org.trim() || org.trim();
  const level: Level = /총학생회|총대의원회/.test(unit) ? "central" : /대학/.test(unit) ? "college" : "other";
  const hits = new Set<Consent>();
  for (const r of filled) if (r.kind === "임명") for (const c of CONSENT) if (c.match(r.role, level)) hits.add(c);
  for (const c of hits) out.push({ ok: false, text: `${josa(c.role, "은", "는")} ${c.need} 임명할 수 있어요(${c.basis}). 동의·인준을 받은 회의록을 함께 보관해요.` });
  if (!hits.size) out.push({ ok: true, text: `사전 동의가 필요한 직책: ${CONSENT.map((c) => `${c.role}(${c.who})`).join(", ")}.` });
  return out;
}

// 임명 전에 의결기구의 동의·인준이 필요한 직책. '국장'은 기구 이름으로 총학생회·단과대학을 가른다(학과 학생회 국장은 해당 없음)
type Level = "central" | "college" | "other";
type Consent = { match: (role: string, level: Level) => boolean; role: string; who: string; need: string; basis: string };
const CONSENT: Consent[] = [
  {
    match: (r, l) => /집행국장/.test(r) || (l === "central" && /국장/.test(r)),
    role: "총학생회 수석집행국장·집행국장", who: "총대의원회", need: "총대의원회의 동의를 얻어", basis: "중앙학생회칙 제57조 제2항",
  },
  {
    // 세칙은 '대의원총회의 임명동의를 받은 집행부 임원'을 전제로 두고, 구체적인 절차는 단과대학 학생회칙에 있다
    match: (r, l) => l === "college" && /국장/.test(r) && !/집행국장/.test(r),
    role: "단과대학 국장급 임원", who: "단과대학 대의원총회 인준", need: "단과대학 대의원총회의 인준을 받아",
    basis: "단과대학 학생회칙, 단과대학ㆍ전공 학생자치에 관한 세칙 제46조 제1항 제2호",
  },
  { match: (r) => /예하기구/.test(r), role: "예하기구의 장", who: "총대의원회", need: "총대의원회의 동의를 얻어", basis: "중앙학생회칙 제62조 제2항" },
  { match: (r) => /복지위원장/.test(r), role: "학생복지위원장", who: "대의원총회", need: "대의원총회의 동의를 얻어", basis: "총학생회 조직 구성에 관한 세칙 제17조 제1항" },
  { match: (r) => /부총학생회장/.test(r), role: "궐위로 지명한 부총학생회장", who: "총대의원회 재적 과반 인준", need: "총대의원회 재적대의원 과반수의 찬성(인준)을 받아야", basis: "중앙학생회칙 제51조 제2항" },
  { match: (r) => /과대|학과\s*대표|급대표/.test(r), role: "학년별 과대표", who: "단과대학 대의원회", need: "단과대학 대의원회의 동의를 받아", basis: "단과대학ㆍ전공 학생자치에 관한 세칙 제48조 제1항" },
];

export function appointText(a: AppointInput): string {
  const date = a.date ? a.date.replaceAll("-", ". ") + "." : "20  .  .  .";
  const rows = a.rows.filter((r) => r.role.trim() || r.name.trim()).map((r) => `  ${r.kind}  ${r.role || "○○"}  ${r.name || "○○○"}`);
  return [
    `사령`,
    ``,
    `${josa(a.org || "○○ 학생회", "은", "는")} 아래와 같이 임면하였음을 공고합니다.`,
    ``,
    ...(rows.length ? rows : ["  임명  ○○  ○○○"]),
    ``,
    `효력 발생일: ${date}`,
    ``,
    a.head || "○○ 학생회장",
  ].join("\n");
}
