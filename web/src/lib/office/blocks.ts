// 문서 블록 — 복사용 글과 Word 파일이 같은 구조에서 나온다 (기획 도우미는 서버 api/app/plan/build.py to_blocks와 같은 모양).
// 네트워크·DOM 없음 — 단위 테스트가 바로 불러 쓴다.

/** distribute: 칸 너비에 글자를 고르게 벌린다 (공문의 수 신 자·제 목 칸) */
export type Align = "left" | "center" | "right" | "distribute";
/** lines: 손으로 채울 칸의 최소 높이(줄 수) — Word에서만 쓰고 복사용 글은 무시한다. shade: 이름 칸 음영 */
export type Cell = { text: string; bold?: boolean; align?: Align; span?: number; table?: TableBlock | null; lines?: number; shade?: boolean };
/** rowLines: 본문 줄마다 최소 높이(줄 수) — 서명 받을 줄처럼 넉넉해야 할 때.
 *  plain: 선 없는 정렬용 표(공문 머리·끝 칸) — sep는 복사용 글에서 칸을 잇는 문자 */
export type TableBlock = { t: "table"; widths: number[]; header: string[]; rows: Cell[][]; rowLines?: number; plain?: boolean; sep?: string };
export type Block =
  /** 문서 머리: 인하대 마크 + 기관명(가운데 크게) */
  | { t: "masthead"; org: string }
  | { t: "title"; text: string }
  | { t: "heading" | "subheading"; text: string }
  /** big: 발신 명의처럼 크게 가운데. hang: '1. ' 뒤로 둘째 줄을 들여 맞춘다 */
  | { t: "para"; text: string; bold?: boolean; align?: Align; small?: boolean; big?: boolean; hang?: boolean }
  | { t: "gap"; lines?: number }
  | { t: "rule" }
  /** 총회 자료 표지(한 쪽): 인 하 대 학 교 / 기구 — 아래쪽에 회의·문서 이름, 명의, 날짜 */
  | { t: "cover"; org: string; lines: string[]; signer: string; date: string }
  /** - 목차 - : level 1은 Ⅰ·Ⅱ, level 2는 1.·2. — page는 쪽 번호(본문 첫 쪽이 1) */
  | { t: "toc"; items: TocItem[] }
  /** 다음 쪽에서 시작 */
  | { t: "pagebreak" }
  /** 여기서부터 쪽 번호를 1로 다시 센다(앞쪽 표지·목차에는 번호를 달지 않는다) */
  | { t: "section" }
  | TableBlock;

export type TocItem = { text: string; level: 1 | 2; page: number };

export const cell = (text: string | number = "", o: Omit<Cell, "text"> = {}): Cell => ({ text: String(text), ...o });

/** 칸은 문자열이나 Cell. 너비는 비율(합이 100이 아니어도 된다) */
export function table(header: string[], rows: (string | number | Cell)[][], widths: number[]): TableBlock {
  return { t: "table", widths, header, rows: rows.map((r) => r.map((c) => (typeof c === "object" ? c : cell(c)))) };
}

/** 왼쪽 칸 이름 + 오른쪽 내용 (양식의 '시기 | …' 같은 표) */
export function labelTable(rows: [string, string | Cell][], labelWidth = 18): TableBlock {
  return table(
    [],
    rows.map(([label, value]) => [cell(label, { bold: true, align: "center", shade: true }), typeof value === "object" ? value : cell(value)]),
    [labelWidth, 100 - labelWidth],
  );
}

/** 선 없는 '이름  내용' 줄들 — 이름 칸은 글자를 고르게 벌려 콜론 없이도 줄이 맞는다. 복사용 글은 '이름 : 내용' */
export function fields(rows: [string, string][], labelWidth = 14): TableBlock {
  return {
    ...table([], rows.map(([label, value]) => [cell(label, { align: "distribute" }), cell(value)]), [labelWidth, 100 - labelWidth]),
    plain: true,
    sep: " : ",
  };
}

/** 블록 → 복사용 글. 표는 칸을 ' | '로 잇고 안쪽 표는 들여 쓴다 (서버 render_text와 같은 규칙) */
export function blocksText(blocks: Block[]): string {
  const cellText = (c: Cell) => c.text.replaceAll("\n", " / ");
  const tableLines = (t: TableBlock, indent = ""): string[] => {
    const out = t.header.length ? [indent + t.header.join(" | ")] : [];
    for (const row of t.rows) {
      out.push(
        indent +
          row
            .filter((c) => !c.table && (!t.plain || c.text.trim()))
            .map(cellText)
            .join(t.sep ?? " | "),
      );
      for (const c of row) if (c.table) out.push(...tableLines(c.table, indent + "    "));
    }
    return out;
  };
  const out: string[] = [];
  for (const b of blocks) {
    if (b.t === "table") out.push(...tableLines(b));
    else if (b.t === "masthead") out.push(b.org);
    else if (b.t === "gap") out.push("");
    else if (b.t === "rule") out.push("─".repeat(30));
    else if (b.t === "cover") out.push("인하대학교", b.org, "", ...b.lines, "", b.signer, b.date);
    else if (b.t === "toc") out.push("", "- 목차 -", ...b.items.map((i) => `${i.level === 2 ? "   " : ""}${i.text}  ${i.page}p`));
    else if (b.t === "pagebreak" || b.t === "section") out.push("");
    else {
      if (b.t === "heading" && out.length) out.push("");
      out.push(b.text);
    }
  }
  return out.join("\n");
}

/** A4 본문 높이(twip, 위 3cm·아래 2cm 여백)와 블록의 대략 높이 — 서명·시행 칸을 쪽 아래로 내릴 빈 줄 수를 정할 때만 쓴다.
 *  넘치면 안 되므로 글자 수는 한 줄 42자로 넉넉히 센다(실제 약 45자). */
export const PAGE_BODY = 14000;
export const LINE = 330; // 11pt 한 줄 + 줄 간격 (Word 렌더러 docx.ts도 이 값을 쓴다)
export const ROW_MIN = 454; // 0.8cm — 표 한 줄의 최소 높이

const textLines = (text: string, perLine = 42) =>
  text.split("\n").reduce((n, line) => n + Math.max(1, Math.ceil([...line].length / perLine)), 0);

export function roughHeight(blocks: Block[]): number {
  let h = 0;
  for (const b of blocks) {
    if (b.t === "masthead") h += 1500;
    else if (b.t === "title") h += 1350;
    else if (b.t === "heading") h += 850;
    else if (b.t === "subheading") h += 650;
    else if (b.t === "rule") h += 330;
    else if (b.t === "cover" || b.t === "toc") h += PAGE_BODY;
    else if (b.t === "gap") h += LINE * (b.lines ?? 1);
    else if (b.t === "para") h += textLines(b.text) * (b.small ? 270 : b.big ? 480 : LINE) + (b.big ? 400 : 100);
    else if (b.t === "table") {
      const sum = b.widths.reduce((x, y) => x + y, 0) || 1;
      h += (b.plain ? 60 : 160) + (b.header.length ? ROW_MIN : 0);
      for (const row of b.rows) {
        let col = 0;
        const pad = b.plain ? 40 : 160;
        let tallest = Math.max(b.rowLines ?? 1, 1) * LINE + pad;
        for (const c of row) {
          const share = b.widths.slice(col, col + (c.span ?? 1)).reduce((x, y) => x + y, 0) / sum;
          col += c.span ?? 1;
          const inner = c.table ? roughHeight([c.table]) : textLines(c.text, Math.max(4, Math.floor(42 * share))) * LINE + pad;
          tallest = Math.max(tallest, inner, (c.lines ?? 1) * LINE + pad, b.plain ? 0 : ROW_MIN);
        }
        h += tallest;
      }
    }
  }
  return h;
}

/** 앞뒤 블록이 한 쪽에 들어가면 남는 만큼(두 줄 여유) 빈 줄을 넣어 뒤 블록(서명·시행 칸)을 쪽 아래로 보낸다. 자리가 없으면 0줄 */
export function fillGap(before: Block[], after: Block[]): Block {
  const left = PAGE_BODY - roughHeight(before) - roughHeight(after);
  return { t: "gap", lines: Math.max(0, Math.floor(left / LINE) - 2) }; // 두 줄은 Word와 미리보기 차이의 여유
}
