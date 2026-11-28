// 문서 작성 탭의 입력 → 문서 블록 (Word 파일용). 양식은 2026-2 총회 자료에서 단위들이 실제로 쓰는 모양을 따른다:
// 공문은 '기관명 → 수신자·(경유)·제목 → 1. 2. → 붙임 … 끝. → 발신 명의 → 학생회장·협조자 / 시행·접수' 순서,
// 손으로 채울 칸은 줄 높이를 두어 A4 한 쪽이 비어 보이지 않게 한다.

import type { Minutes } from "../minutes-model.ts";
import type { AppointInput, ChangeInput, IncidentInput, LetterInput, PaymentInput } from "../writer.ts";
import { josa, won } from "../format.ts";
import { changeNumbers, reserveUse, rowsTotal } from "../writer.ts";
import { type Block, type Cell, PAGE_BODY, type TocItem, cell, fields, fillGap, labelTable, roughHeight, table } from "./blocks.ts";

const blankDate = "20    .     .     .";
const dotDate = (iso: string) => (iso ? `${iso.replaceAll("-", ". ")}.` : blankDate);

const withSchool = (s: string) => (s.startsWith("인하대학교") ? s : `인하대학교 ${s}`);
/** 문서 머리(인하대 마크 + 기관명). 기구 이름을 안 적었으면 '인하대학교'만 */
const masthead = (org = ""): Block => ({ t: "masthead", org: org.trim() ? withSchool(org.trim()) : "인하대학교" });
/** 맺음: 확인 문장·날짜는 가운데, 서명은 오른쪽 */
const signOff = (statement: string, who: string): Block[] => [
  { t: "gap" },
  { t: "para", text: statement, align: "center" },
  { t: "para", text: blankDate, align: "center" },
  { t: "gap" },
  { t: "para", text: `${who}                    (서명)`, align: "right" },
];

/** 지급 확인서 — 받는 사람 수만큼 번호·금액 줄을 채우고, 8줄이 안 되면 빈 줄을 더해 손으로 더 적을 수 있게 한다 */
export function paymentBlocks(p: PaymentInput, org = ""): Block[] {
  const per = p.unit * p.times;
  const people = Math.max(p.people, 1);
  const sheet = table(
    ["번호", "성명", "학과(소속)", "연락처", "금액", "서명"],
    [
      ...Array.from({ length: people }, (_, i) => [cell(i + 1, { align: "center" }), "", "", "", cell(won(per), { align: "right" }), ""]),
      ...Array.from({ length: Math.max(0, 8 - people) }, () => ["", "", "", "", "", ""]),
    ],
    [8, 16, 22, 20, 16, 18],
  );
  sheet.rowLines = 1.3;
  return [
    masthead(org),
    { t: "title", text: "지 급 확 인 서" },
    labelTable([
      ["행사명", p.event || "○○ 행사"],
      ["지급 사유", `${p.reason || "○○"} (1인 ${won(p.unit)}${p.times > 1 ? ` × ${p.times}회 = ${won(per)}` : ""})`],
      ["지급 방법", p.method],
      ["지급일", blankDate],
      ["합계", cell(`${won(per * p.people)} (${p.people}명)`, { bold: true })],
    ]),
    sheet,
    ...signOff("위 금액을 정히 수령하였음을 확인합니다.", "확인자 : [직책] [이름]"),
    {
      t: "para",
      text: `※ 감사 제출 때 지급 확인서 원본과 함께 ${p.method === "현금" ? "수령증(성명·연락처)" : p.method === "상품권" ? "상품권 구매 확인서" : "계좌이체 확인증"}을 붙여요.`,
      small: true,
    },
  ];
}

export function incidentBlocks(c: IncidentInput, org = ""): Block[] {
  const rows = c.rows.filter((r) => r.name.trim());
  const money = table(
    ["품목", "수량", "단가", "금액"],
    [
      ...(rows.length ? rows : [{ name: "○○", qty: 0, unit: 0 }]).map((r) => [
        r.name,
        cell(r.qty.toLocaleString("ko-KR"), { align: "right" }),
        cell(won(r.unit), { align: "right" }),
        cell(won(r.qty * r.unit), { align: "right" }),
      ]),
      [cell("합계", { bold: true, span: 3 }), cell(won(rowsTotal(c.rows)), { bold: true, align: "right" })],
    ],
    [40, 15, 20, 25],
  );
  return [
    masthead(org),
    { t: "title", text: "경 위 서" },
    labelTable([
      ["작성자", "[소속] [직책] [이름]"],
      ["발생일", c.date || blankDate],
      ["경위", cell(c.what || "○○", { lines: 8 })],
      ["원인", cell(c.causes.length ? c.causes.join(", ") : "○○", { lines: 2 })],
      ["관련 금액", cell("", { table: money })],
      ["후속 조치", cell(c.followUp || "○○", { lines: 6 })],
    ]),
    ...signOff("위와 같이 경위를 보고합니다.", "작성자 : [직책] [이름]"),
  ];
}

export function changeBlocks(c: ChangeInput, org = ""): Block[] {
  const { over } = changeNumbers(c);
  const rows: [string, string | Cell][] = [
    ["항목", c.item || "○○"],
    ["인준 금액", won(c.approved)],
    ["실제 집행 금액", won(c.spent)],
    over > 0 ? ["초과 금액", won(over)] : ["남은 금액", won(-over)],
  ];
  if (over > 0) rows.push(["예비비 사용", reserveUse(c)]);
  rows.push(["변경 사유", cell(c.reason || "○○", { lines: 15 })], ["첨부 서류", cell("영수증·견적서 등 [   ]", { lines: 2 })]);
  return [
    masthead(org),
    { t: "title", text: "예 산 변 경 사 유 서" },
    labelTable(rows, 22),
    ...signOff("위와 같은 사유로 예산 변경을 보고합니다.", "작성자 : [직책] [이름]"),
  ];
}

/** 발신 명의(○○학과 학생회장)에서 기관명(○○학과 학생회)을 뽑는다 */
export function orgOf(from: string): string {
  // 직책 → 기구 (순서대로): 권한대행 떼기 → 띄어 쓴 직책 떼기('○○위원회 위원장') → (부)학생회장→학생회 → 위원장→위원회
  // → ○○회장→○○회 → 의장·대표 떼기
  const name = from
    .trim()
    .replace(/\s*(?:권한|직무)\s*대행$/, "")
    .replace(/\s+(?:부?위원장|부?회장|의장|대표)$/, "")
    .replace(/부?학생회장$/, "학생회")
    .replace(/위원장$/, "위원회")
    .replace(/(\S)회장$/, "$1회")
    .replace(/\s*(?:의장|대표|회장)$/, "")
    .trim();
  return name ? (/회$/.test(name) ? name : `${name} 학생회`) : "○○ 학생회";
}

/** 본문: 빈 줄로 나눈 문단마다 2., 3. 번호를 붙인다 (1.은 인사 문장). 문단 안의 줄바꿈(아래 목록)은 그대로 둔다 */
export function letterParagraphs(body: string): string[] {
  const parts = body
    .split(/\r?\n\s*\r?\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  return ["우리 학교의 무궁한 발전을 기원합니다.", ...(parts.length ? parts : ["○○에 관하여 아래와 같이 요청드립니다."])].map(
    (p, i) => `${i + 1}. ${p}`,
  );
}

/** 공문 — 인하대학교 총학생회 발신공문 양식(행정 기안문 꼴):
 *  마크·기관명 → 수신자·(경유)·참조·제목 → 가로줄 → 1. 2. … → 붙임 … 끝. → 발신 명의 → (쪽 아래) 기안자·결재권자 → 협조 → 시행·접수 → 연락처 */
export function letterBlocks(l: LetterInput): Block[] {
  const attachments = l.attachments
    .split(/\r?\n/)
    .map((a) => a.trim())
    .filter(Boolean);
  const day = l.date ? `${l.date.replaceAll("-", ".")}.` : "20  .  .  .";
  const head = fields(
    [
      ["수신자", l.to || "○○"],
      ["(경유)", ""],
      ["참조", l.cc.trim()],
      ["제목", l.title || "○○"],
    ],
    11,
  );
  head.rows[3][1].bold = true;
  const blocks: Block[] = [
    masthead(orgOf(l.from)),
    head,
    { t: "rule" },
    ...letterParagraphs(l.body).map((text): Block => ({ t: "para", text, hang: true })),
  ];
  if (attachments.length) {
    const list = attachments.map((a, i) => `${i + 1}. ${a}${i === attachments.length - 1 ? "  끝." : ""}`);
    blocks.push(fields([["붙임", list.join("\n")]], 7));
  } else {
    blocks.push({ t: "para", text: "끝." });
  }
  const sender = withSchool(l.from.trim() || "○○ 학생회장");
  const signer: Block = { t: "para", text: sender, big: true };
  // 기안자·결재권자 / 협조 / 시행·접수를 두 칸으로 맞춘다
  const sign = table(
    [],
    [
      [l.drafter?.trim() || "[기안자 직위] [이름]", `${sender.replace(/^인하대학교\s*/, "")} [이름]`],
      ["협조", ""],
      [`시행 ${l.number || "○○-20  -0000"} (${day})`, "접수"],
    ],
    [50, 50],
  );
  const foot: Block[] = [
    { t: "rule" },
    { ...sign, plain: true, sep: "        " },
    { t: "para", text: l.contact?.trim() || "우편 [우편번호] 주소 [주소] / [홈페이지]\n전화 [전화] 전송 / [이메일] / 공개", small: true },
  ];
  // 행정 기안문처럼 발신 명의는 아래 가로줄 바로 위, 기안자·시행·연락처는 쪽 맨 아래에 둔다
  return [...blocks, fillGap(blocks, [signer, ...foot]), signer, ...foot];
}

export function appointBlocks(a: AppointInput, org = ""): Block[] {
  const rows = a.rows.filter((r) => r.role.trim() || r.name.trim());
  const unit = a.org.trim() || org.trim();
  const roster = table(
    ["구분", "직책", "성명"],
    (rows.length ? rows : [{ kind: "임명", role: "○○", name: "○○○" }]).map((r) => [
      cell(r.kind, { align: "center" }),
      cell(r.role || "○○", { align: "center" }),
      cell(r.name || "○○○", { align: "center" }),
    ]),
    [20, 40, 40],
  );
  roster.rowLines = 1.4;
  const top: Block[] = [
    masthead(unit),
    { t: "title", text: "사    령" },
    { t: "para", text: `${josa(unit || "○○ 학생회", "은", "는")} 아래와 같이 임면하였음을 공고합니다.` },
    { t: "gap" },
    roster,
    { t: "para", text: `효력 발생일 : ${dotDate(a.date)}`, align: "center" },
  ];
  const sign: Block[] = [
    { t: "para", text: dotDate(a.date), align: "center" },
    { t: "para", text: `${withSchool(a.head.trim() || "○○ 학생회장")}  (직인)`, big: true },
  ];
  // 남는 줄은 명의 위에 6줄까지만 둔다(쪽의 2/3쯤) — 명의가 쪽 맨 아래로 떨어져 가운데가 텅 비지 않게
  const spare = fillGap(top, sign);
  const lines = spare.t === "gap" ? (spare.lines ?? 1) : 1;
  return [...top, { t: "gap", lines: Math.min(lines, 6) }, ...sign];
}

/** 회의록 — 한 쪽에 들어가게 촘촘히: 회의 정보는 네 칸 표(일시·장소, 참석·작성자를 한 줄씩), 안건 줄은 내용만큼, 확인 서명은 맨 아래 */
export function minutesBlocks(m: Minutes, org = ""): Block[] {
  const label = (text: string) => cell(text, { bold: true, align: "center", shade: true });
  const info = table(
    [],
    [
      [label("회의명"), cell(m.title || "○○ 회의", { span: 3 })],
      [label("일    시"), m.held_on ? dotDate(m.held_on) : blankDate, label("장    소"), m.place || "-"],
      [label("참    석"), m.attendees ? `${m.attendees}명` : "-", label("작 성 자"), "[직책] [이름]        (서명)"],
    ],
    [14, 36, 14, 36],
  );
  const blocks: Block[] = [
    masthead(org),
    { t: "title", text: "회 의 록" },
    info,
    { t: "subheading", text: "1. 안건" },
    table(
      ["번호", "안건", "논의 내용", "결과"],
      m.agenda.map((a, i) => [cell(i + 1, { align: "center" }), a.title, a.discussion, cell(a.result, { align: "center" })]),
      [6, 24, 60, 10],
    ),
  ];
  let n = 1;
  if (m.decisions.length)
    blocks.push({ t: "subheading", text: `${++n}. 결정사항` }, { t: "para", text: m.decisions.map((d) => `- ${d}`).join("\n") });
  if (m.todos.length) {
    blocks.push(
      { t: "subheading", text: `${++n}. 할 일` },
      table(
        ["할 일", "담당", "기한"],
        m.todos.map((t) => [t.task, cell(t.owner || "-", { align: "center" }), cell(t.due ? dotDate(t.due) : "-", { align: "center" })]),
        [60, 20, 20],
      ),
    );
  }
  if (m.next_agenda.length)
    blocks.push({ t: "subheading", text: `${++n}. 다음 회의 안건` }, { t: "para", text: m.next_agenda.map((a) => `- ${a}`).join("\n") });
  const sign: Block = { t: "para", text: "확인자 : [직책] [이름]                    (서명)", align: "right" };
  return [...blocks, fillGap(blocks, [sign]), sign];
}

/* ---------------------------------------------------------------- 기획 도우미 사업계획서 */
// 학생회 총회 자료(한컴 양식) 꼴: 표지 → - 목차 - → Ⅰ. 기구표 → Ⅱ. 사업 계획서 → Ⅲ. 예산운영 계획서.
// 표지·목차에는 쪽 번호를 달지 않고 Ⅰ. 기구표가 1쪽. 큰 장과 '2. 세부 …'는 새 쪽에서 시작한다(총회 자료가 그렇게 나눈다).

export type PlanDocReq = { org: string; title: string; meeting?: string; meeting_date?: string | null; start?: string; term?: string };

/** 3~8월 1학기, 9~2월 2학기(1·2월은 전년도 2학기) — 서버 build._semester와 같다 */
export function semesterOf(iso: string): { year: number; term: 1 | 2 } {
  const [y, m] = iso.split("-").map(Number);
  if (m >= 3 && m <= 8) return { year: y, term: 1 };
  return { year: m >= 9 ? y : y - 1, term: 2 };
}

/** 회의 이름을 총회 공고 꼴로: '2학기 6차 정기총회' → '2026년도 2학기 6차 중앙 정기총회'. 비었으면 '2026년도 2학기' */
export function meetingTitle(meeting: string, dateIso: string): string {
  const { year, term } = semesterOf(dateIso);
  let m = meeting.replace(/\s+/g, " ").trim().replace(/(정기|임시)\s+총회/, "$1총회");
  if (!m) return `${year}년도 ${term}학기`;
  if (!/중앙|대의원/.test(m)) m = m.replace(/(\d+차)\s*(정기|임시)총회/, "$1 중앙 $2총회");
  if (/\d{4}|\d{2}\s*년/.test(m)) return m; // 연도를 이미 적었으면('2026년도', '26년') 그대로
  const said = m.match(/^([12])\s*학기/);
  if (!said) return `${year}년도 ${term}학기 ${m}`;
  // 적은 학기가 날짜의 학기와 다르면 가까운 쪽 연도로: 2월에 '1학기' → 그해 1학기, 9월 이후 '1학기' → 다음 해
  const [y, mon] = dateIso.split("-").map(Number);
  const sayYear = said[1] === "1" ? (mon >= 9 ? y + 1 : y) : mon <= 2 ? y - 1 : y;
  return `${sayYear}년도 ${m}`;
}

/** 내려받는 파일 이름 — 총회 자료 파일처럼 '연도 회의 기구 사업명 사업계획서'. 길면(56자) 회의·기구부터 빼서 사업명·'사업계획서'는 남긴다 */
export function planFileName(req: PlanDocReq): string {
  const when = meetingTitle(req.meeting ?? "", req.meeting_date || req.start || todayIso()).replace(/^(\d{4})년도 /, "$1 ");
  const year = when.match(/^\d{4}/)?.[0] ?? "";
  const title = req.title.trim();
  const tries = [[when, req.org.trim(), title], [when, title], [year, title], [title]];
  const names = tries.map((t) => [...t, "사업계획서"].filter(Boolean).join(" "));
  return names.find((n) => [...n].length <= 56) ?? names[names.length - 1];
}

const todayIso = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
const coverDate = (iso: string) => iso.replaceAll("-", ". ");

// 어림 높이(roughHeight)는 표 글을 11pt 줄로 세는데 총회 자료 꼴 표 글은 10pt라 이미 넉넉하다 — 더 키우면 목차 쪽이 한 쪽씩 밀린다(교차 리뷰 72개 모의 기획서)
const heightOf = (blocks: Block[]) => roughHeight(blocks);
const pagesOf = (blocks: Block[]) => Math.max(1, Math.ceil(heightOf(blocks) / PAGE_BODY));

/** 세부 사업 계획서: 사업명을 표 첫 줄(회색, 가운데)로 올리고 이름 칸을 회색으로, 남는 자리는 '사업내용' 칸을 늘려 쪽 끝까지 채운다(표본 꼴) */
function detailPage(seg: Block[]): Block[] {
  const i = seg.findIndex((b, k) => b.t === "para" && seg[k + 1]?.t === "table" && !(seg[k + 1] as { header: string[] }).header.length);
  if (i < 0) return seg;
  const title = seg[i] as Extract<Block, { t: "para" }>;
  const src = seg[i + 1] as Extract<Block, { t: "table" }>;
  const rows: Cell[][] = [
    [cell(title.text, { span: 2, shade: true, align: "center" })],
    ...src.rows.map(([label, ...rest]) => [{ ...label, shade: true, bold: true, align: "center" as const }, ...rest]),
  ];
  const merged = { ...src, widths: [19, 81], rows };
  const head = seg.slice(0, i);
  const left = PAGE_BODY - heightOf([...head, merged]);
  const k = rows.findIndex((r) => r[0].text === "사업내용");
  if (k > 0 && left > 0) {
    const body = rows[k][1];
    const now = body.text.split("\n").length;
    rows[k] = [rows[k][0], { ...body, lines: now + Math.floor(left / 330) - 3 }]; // 세 줄은 Word와 어림의 차이 여유
  }
  return [...head, merged, ...seg.slice(i + 2)];
}

/** 서버 블록(Ⅱ. 사업 계획서 …) 앞에 표지·목차·기구표 자리를 붙이고, 장마다 쪽을 나눈다. today는 테스트용 */
export function planDocBlocks(req: PlanDocReq, blocks: Block[], today = todayIso()): Block[] {
  const org = req.org.trim() || "○○ 학생회";
  const at = (pred: (b: Block) => boolean) => blocks.findIndex(pred);
  const isSub = (prefix: string) => (b: Block) => b.t === "subheading" && b.text.startsWith(prefix);
  const cuts = [at(isSub("2. 세부 사업")), at((b) => b.t === "heading" && b.text.startsWith("Ⅲ")), at(isSub("2. 세부 예산"))];
  // 서버가 옛 모양(나눌 곳이 없음)이면 나누지 않고 한 덩어리로 둔다
  const marks = cuts.every((c) => c > 0) && cuts[0] < cuts[1] && cuts[1] < cuts[2] ? cuts : [];
  const raw = [0, ...marks, blocks.length].slice(0, -1).map((from, k, all) => blocks.slice(from, k + 1 < all.length ? all[k + 1] : blocks.length));
  const segs = marks.length ? raw.map((seg, k) => (k === 1 ? detailPage(seg) : seg)) : raw;

  const orgChart: Block[] = [
    { t: "heading", text: "Ⅰ. 기구표" },
    { ...table([], [[cell("기구표(조직도)를 여기에 넣어 주세요.", { align: "center", lines: 30 })]], [100]) },
  ];
  // 쪽 번호: 기구표 1쪽, Ⅱ는 2쪽부터. 뒤쪽은 앞 덩어리 높이로 어림한다(넘칠 만하면 한 쪽 더 센다)
  const items: TocItem[] = [{ text: "Ⅰ. 기구표", level: 1, page: 1 }];
  if (marks.length) {
    const [p2, p3] = [2, 2 + pagesOf(segs[0])];
    const p4 = p3 + pagesOf(segs[1]);
    const p5 = p4 + pagesOf(segs[2]);
    items.push(
      { text: "Ⅱ. 사업 계획서", level: 1, page: p2 },
      { text: "1. 전체 사업 계획서", level: 2, page: p2 },
      { text: "2. 세부 사업 계획서", level: 2, page: p3 },
      { text: "Ⅲ. 예산운영 계획서", level: 1, page: p4 },
      { text: "1. 전체 예산 계획서", level: 2, page: p4 },
      { text: "2. 세부 예산 계획서", level: 2, page: p5 },
    );
  } else {
    items.push({ text: "Ⅱ. 사업 계획서", level: 1, page: 2 });
  }

  const meeting = meetingTitle(req.meeting ?? "", req.meeting_date || req.start || today);
  return [
    {
      t: "cover",
      org,
      lines: [meeting, `(${org} 「${req.title.trim()}」 사업안 및 예산안)`],
      signer: [req.term?.trim(), org].filter(Boolean).join(" "),
      date: coverDate(today),
    },
    { t: "pagebreak" },
    { t: "toc", items },
    { t: "section" },
    ...orgChart,
    { t: "pagebreak" },
    ...segs.flatMap((seg, k) => (k ? [{ t: "pagebreak" } satisfies Block, ...seg] : seg)),
  ];
}
