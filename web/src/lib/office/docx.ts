// 블록 → Word(.docx). 총대의원회 작성 안내대로 맑은 고딕 11pt, A4. 브라우저 안에서 만들어 바로 내려받는다(서버로 보내지 않음).
// 공문서 꼴: 여백 위 3cm·왼쪽 2cm·오른쪽·아래 1.5cm, 첫 쪽 머리에 인하대 마크와 기관명, 쪽 번호 '- 1 -' (머리글 없음).
// 표는 바깥 굵은 선·안쪽 가는 선, 머리·이름 칸 음영, 줄 최소 높이를 두어 손으로 채울 칸이 A4에서 비어 보이지 않게 한다.

import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  LineRuleType,
  HeightRule,
  ImageRun,
  Packer,
  PageBreak,
  PageNumber,
  Paragraph,
  SectionType,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} from "docx";

import { type Align, type Block, type Cell, LINE as LINE_TWIPS, ROW_MIN, type TableBlock, type TocItem } from "./blocks.ts";

/** preset 'assembly': 총회 자료(사업계획서) 꼴 — 컴퓨터공학과 학생회 2025-2 상임위원회 자료(한컴)에서 잰 글자 크기·정렬을 따른다.
 *  큰 제목 18pt 굵게(밑줄 없음) · '1.' 제목 15pt 보통(들여 씀) · '1)' 제목 15pt 굵게 · 표 머리 13pt 굵게·회색 · 표 본문 10pt 가운데 · 이름 칸 11pt 굵게·회색 */
export type DocOptions = { emblem?: Uint8Array; preset?: "assembly" };

const FONT = "맑은 고딕";
const SIZE = 22; // 반 포인트 단위 — 11pt
const INK = "000000";
const MUTED = "595959";
const ACCENT = "1F3864"; // 머리 띠 — 인하대 마크의 남색과 맞춘다
const HEAD_FILL = "E7E6E6";
const LABEL_FILL = "F2F2F2";

const PAGE = { width: 11906, height: 16838 }; // A4 (twip)
const MARGIN = { top: 1701, bottom: 1134, left: 1134, right: 851, header: 851, footer: 567 };
const CONTENT = PAGE.width - MARGIN.left - MARGIN.right;
/** 줄 높이는 글자 크기의 1.5배로 '고정'한다 — '배수'로 두면 Word가 맑은 고딕의 큰 기본 줄 높이에 곱해 미리보기보다 30%쯤 길어진다 */
const lineFor = (halfPoints: number) => halfPoints * 15;
/** 글자 크기(반 포인트)와 표 꼴. 표 칸 안 글의 줄 높이는 크기의 1.3배 — 칸 여백이 있어 공문서 표처럼 촘촘하고 읽기 좋다 */
type Style = { heading: number; headingRule: boolean; sub: number; subNumbered: boolean; head: number; body: number; label: number; rowMin: number; center: boolean };
const BASE: Style = { heading: 28, headingRule: true, sub: 24, subNumbered: false, head: SIZE, body: SIZE, label: SIZE, rowMin: ROW_MIN, center: false };
const ASSEMBLY: Style = { heading: 36, headingRule: false, sub: 30, subNumbered: true, head: 26, body: 20, label: 22, rowMin: 620, center: true };
let style: Style = BASE; // blocksToDocument가 문서마다 정한다 (동기 실행이라 겹치지 않는다)

const OUTER = { style: BorderStyle.SINGLE, size: 12, color: INK };
const INNER = { style: BorderStyle.SINGLE, size: 4, color: "7F7F7F" };
const NONE = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const GRID = { top: OUTER, bottom: OUTER, left: OUTER, right: OUTER, insideHorizontal: INNER, insideVertical: INNER };
const NO_GRID = { top: NONE, bottom: NONE, left: NONE, right: NONE, insideHorizontal: NONE, insideVertical: NONE };
const ALIGN = { left: AlignmentType.LEFT, center: AlignmentType.CENTER, right: AlignmentType.RIGHT, distribute: AlignmentType.DISTRIBUTE } as const;

type RunOpts = { bold?: boolean; size?: number; color?: string; spacing?: number };

function run(text: string, o: RunOpts = {}): TextRun {
  return new TextRun({
    text,
    bold: o.bold,
    size: o.size ?? SIZE,
    color: o.color,
    characterSpacing: o.spacing,
    font: { ascii: FONT, eastAsia: FONT, hAnsi: FONT },
  });
}

/** hang: 첫 줄 번호('2. ') 뒤로 둘째 줄부터 들여 맞춘다 */
type ParaOpts = RunOpts & { align?: Align; before?: number; after?: number; hang?: boolean; line?: number; keepNext?: boolean };
const HANG = 300;

function paragraphs(text: string, o: ParaOpts = {}): Paragraph[] {
  return (text || "")
    .split("\n")
    .map(
      (line, i, all) =>
        new Paragraph({
          children: [run(line, o)],
          alignment: ALIGN[o.align ?? "left"],
          indent: o.hang ? { left: HANG, hanging: HANG } : undefined,
          keepNext: o.keepNext,
          keepLines: o.keepNext,
          spacing: {
            before: i === 0 ? (o.before ?? 0) : 0,
            after: i === all.length - 1 ? (o.after ?? 0) : 0,
            line: o.line ?? lineFor(o.size ?? SIZE),
            lineRule: LineRuleType.EXACT,
          },
        }),
    );
}

const empty = (after = 0) => new Paragraph({ children: [], spacing: { after, line: 240, lineRule: LineRuleType.EXACT } });

function twips(widths: number[], total: number): number[] {
  const sum = widths.reduce((a, b) => a + b, 0) || 1;
  return widths.map((w) => Math.round((w / sum) * total));
}

const rowHeight = (lines: number) => Math.max(style.rowMin, Math.round(lines * LINE_TWIPS + 160));

/** 이 줄 수 이하인 표는 쪽을 넘기지 않고 통째로 다음 쪽으로 보낸다 (Word: 마지막 행 빼고 모든 문단에 '다음 문단과 함께').
 *  더 긴 표는 행 단위로만 나뉘고 머리 행이 다음 쪽에 반복된다. */
const KEEP_ROWS = 18;

function tableOf(t: TableBlock, total: number): Table {
  const cols = twips(t.widths, total);
  const keep = t.rows.length + (t.header.length ? 1 : 0) <= KEEP_ROWS;
  const cellOf = (c: Cell, i: number, header: boolean, keepNext = false): TableCell => {
    const span = c.span ?? 1;
    const width = cols.slice(i, i + span).reduce((a, b) => a + b, 0);
    const label = !header && !!c.shade;
    const size = header ? style.head : label ? style.label : style.body;
    // 총회 자료 꼴: 짧은 칸은 가운데, 여러 줄 글은 왼쪽 (정렬을 정해 둔 칸은 그대로)
    const long = c.text.includes("\n") || [...c.text].length > 40;
    // 총회 자료 꼴은 금액까지 가운데에 둔다(표본 그대로) — 서버 칸은 정렬을 늘 실어 오므로 글 길이로만 정한다
    const align = header ? "center" : style.center && !t.plain && c.align !== "distribute" ? (long ? "left" : "center") : c.align;
    const children: (Paragraph | Table)[] = c.table
      ? [tableOf(c.table, width - 240), empty()]
      : paragraphs(c.text, { bold: header || c.bold || label, size, align, line: Math.round(size * 13), keepNext });
    const tall = (c.lines ?? 0) > 2;
    return new TableCell({
      children,
      columnSpan: span > 1 ? span : undefined,
      width: { size: width, type: WidthType.DXA },
      verticalAlign: (tall && !style.center) || t.plain ? VerticalAlign.TOP : VerticalAlign.CENTER, // 총회 자료 꼴은 늘린 칸도 가운데(표본)
      margins: t.plain
        ? { top: 20, bottom: 20, left: 0, right: 160 }
        : { top: c.table ? 120 : 70, bottom: c.table ? 60 : 70, left: 120, right: 120 },
      shading: header || c.shade ? { type: ShadingType.CLEAR, color: "auto", fill: header ? HEAD_FILL : LABEL_FILL } : undefined,
    });
  };
  const rows: TableRow[] = [];
  if (t.header.length)
    rows.push(
      new TableRow({
        tableHeader: true,
        height: { value: style.rowMin, rule: HeightRule.ATLEAST },
        children: t.header.map((h, i) => cellOf({ text: h }, i, true, keep && t.rows.length > 0)),
      }),
    );
  t.rows.forEach((row, r) => {
    const keepNext = keep && r < t.rows.length - 1;
    let col = 0;
    const lines = Math.max(t.rowLines ?? 1, ...row.map((c) => c.lines ?? 1));
    rows.push(
      new TableRow({
        cantSplit: true,
        height: t.plain ? undefined : { value: rowHeight(lines), rule: HeightRule.ATLEAST },
        children: row.map((c) => {
          const out = cellOf(c, col, false, keepNext);
          col += c.span ?? 1;
          return out;
        }),
      }),
    );
  });
  return new Table({ rows, width: { size: total, type: WidthType.DXA }, columnWidths: cols, borders: t.plain ? NO_GRID : GRID });
}

const emblemRun = (data: Uint8Array, px: number) => new ImageRun({ type: "png", data, transformation: { width: px, height: px } });

/** 첫 쪽 머리(모든 문서 같은 꼴): [마크 | 기관명 | 빈칸]으로 기관명이 정확히 가운데 크게 오고, 아래 남색 겹줄 */
function masthead(org: string, emblem?: Uint8Array): (Paragraph | Table)[] {
  const markWidth = 1300;
  const nameWidth = CONTENT - markWidth * 2;
  const cells = [
    new TableCell({
      width: { size: markWidth, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({ children: emblem ? [emblemRun(emblem, 62)] : [], spacing: { line: 240, lineRule: LineRuleType.AUTO } })],
    }),
    new TableCell({
      width: { size: nameWidth, type: WidthType.DXA },
      verticalAlign: VerticalAlign.CENTER,
      children: paragraphs(org, { bold: true, size: 36, align: "center", spacing: 20 }),
    }),
    new TableCell({ width: { size: markWidth, type: WidthType.DXA }, children: [empty()] }),
  ];
  return [
    new Table({
      rows: [new TableRow({ children: cells })],
      width: { size: CONTENT, type: WidthType.DXA },
      columnWidths: [markWidth, nameWidth, markWidth],
      borders: NO_GRID,
    }),
    new Paragraph({
      children: [],
      border: { bottom: { style: BorderStyle.THICK_THIN_MEDIUM_GAP, size: 18, color: ACCENT, space: 1 } },
      spacing: { after: 240, line: 120, lineRule: LineRuleType.EXACT },
    }),
  ];
}

const gapLines = (lines: number) => new Paragraph({ children: [], spacing: { after: 0, line: LINE_TWIPS * lines, lineRule: LineRuleType.EXACT } });

const wraps = (text: string, perLine: number) => Math.max(0, Math.ceil([...text].length / perLine) - 1);

/** 총회 자료 표지 — 학생회 한컴 양식 그대로: 위쪽 두 줄 사이 '인 하 대 학 교 / 기구', 아래쪽 회의·문서 이름, 명의, 날짜 */
function cover(b: Extract<Block, { t: "cover" }>): Paragraph[] {
  const inset = { left: 740, right: 1020 }; // 선이 쪽 가운데 14.4cm (표본: 3.3~17.7cm)
  const rule = { style: BorderStyle.SINGLE, size: 8, color: INK, space: 10 };
  const center = (text: string, size: number, after = 0) => paragraphs(text, { bold: true, size, align: "center", after, line: Math.round(lineFor(size) * 1.05) });
  return [
    gapLines(1),
    new Paragraph({
      children: [run("인하대학교", { bold: true, size: 96, spacing: 160 })],
      alignment: AlignmentType.CENTER,
      indent: inset,
      border: { top: rule },
      spacing: { before: 0, after: 120, line: lineFor(96), lineRule: LineRuleType.EXACT },
    }),
    new Paragraph({
      children: [run(b.org, { bold: true, size: 70, spacing: 85 })],
      alignment: AlignmentType.CENTER,
      indent: inset,
      border: { bottom: rule },
      spacing: { after: 0, line: lineFor(70), lineRule: LineRuleType.EXACT },
    }),
    // 기구 35pt는 한 줄 10자, 회의·문서 줄 26pt는 19자쯤 — 넘쳐 줄이 늘면 그만큼 가운데 빈 줄을 줄인다(빈 줄 1 = 330)
    gapLines(Math.max(4, 17 - Math.ceil((wraps(b.org, 10) * 1050 + b.lines.reduce((n, l) => n + wraps(l, 19), 0) * 820) / 330))),
    ...b.lines.flatMap((l) => center(l, 52)),
    gapLines(2),
    ...center(b.signer, 36, 200),
    ...center(b.date, 30),
  ];
}

/** - 목차 - : 선 없는 두 칸 표(제목 | 쪽) — 탭 위치를 무시하는 뷰어(한글 등)에서도 쪽 번호가 오른쪽 끝에 맞는다 */
function toc(items: TocItem[]): (Paragraph | Table)[] {
  const pageWidth = 900;
  const textWidth = CONTENT - 600 - pageWidth;
  const rows = items.map((i) => {
    const size = i.level === 1 ? 36 : 28;
    const para = (text: string, align: "left" | "right") =>
      new Paragraph({
        children: [run(text, { bold: i.level === 1, size })],
        alignment: ALIGN[align],
        indent: align === "left" ? { left: i.level === 1 ? 0 : 400 } : undefined,
        spacing: { before: i.level === 1 ? 220 : 40, after: 40, line: lineFor(size) + 60, lineRule: LineRuleType.EXACT },
      });
    return new TableRow({
      children: [
        new TableCell({ width: { size: textWidth, type: WidthType.DXA }, children: [para(i.text, "left")] }),
        new TableCell({ width: { size: pageWidth, type: WidthType.DXA }, children: [para(`${i.page}p`, "right")] }),
      ],
    });
  });
  return [
    gapLines(2),
    ...paragraphs("- 목차 -", { bold: true, size: 48, align: "center", after: 360 }),
    new Table({
      rows,
      width: { size: textWidth + pageWidth, type: WidthType.DXA },
      columnWidths: [textWidth, pageWidth],
      borders: NO_GRID,
      alignment: AlignmentType.CENTER,
    }),
  ];
}

function body(blocks: Block[], emblem?: Uint8Array): (Paragraph | Table)[] {
  const out: (Paragraph | Table)[] = [];
  for (const b of blocks) {
    if (b.t === "masthead") out.push(...masthead(b.org, emblem));
    else if (b.t === "cover") out.push(...cover(b));
    else if (b.t === "toc") out.push(...toc(b.items));
    else if (b.t === "pagebreak") out.push(new Paragraph({ children: [new PageBreak()], spacing: { after: 0, line: 240, lineRule: LineRuleType.EXACT } }));
    else if (b.t === "section") continue;
    else if (b.t === "table") out.push(tableOf(b, CONTENT), empty(b.plain ? 60 : 160));
    else if (b.t === "title") out.push(...paragraphs(b.text, { bold: true, align: "center", size: 40, before: 120, after: 360, spacing: 40 }));
    else if (b.t === "heading") {
      out.push(
        new Paragraph({
          children: [run(b.text, { bold: true, size: style.heading })],
          spacing: { before: 280, after: 140, line: lineFor(style.heading), lineRule: LineRuleType.EXACT },
          border: style.headingRule ? { bottom: { style: BorderStyle.SINGLE, size: 6, color: ACCENT, space: 2 } } : undefined,
          keepNext: true,
        }),
      );
    } else if (b.t === "subheading") {
      // 총회 자료 꼴: '1. 전체 사업 계획서'는 보통 굵기로 들여 쓰고, '1) 수입'은 굵게 왼쪽 끝에서
      const numbered = style.subNumbered && /^\d+\.\s/.test(b.text);
      out.push(
        new Paragraph({
          children: [run(b.text, { bold: !numbered, size: style.sub })],
          indent: numbered ? { left: 500 } : undefined,
          spacing: { before: numbered ? 0 : 160, after: numbered ? 200 : 100, line: lineFor(style.sub), lineRule: LineRuleType.EXACT },
          keepNext: true,
        }),
      );
    } else if (b.t === "rule") {
      out.push(
        new Paragraph({
          children: [],
          border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: INK, space: 1 } },
          spacing: { after: 200, line: 120, lineRule: LineRuleType.EXACT },
        }),
      );
    } else if (b.t === "gap") {
      if (b.lines === 0) continue;
      out.push(new Paragraph({ children: [], spacing: { after: 0, line: LINE_TWIPS * (b.lines ?? 1), lineRule: LineRuleType.EXACT } }));
    } else if (b.t === "para" && b.big) {
      out.push(...paragraphs(b.text, { bold: true, align: "center", size: 32, before: 240, after: 160, spacing: 20 }));
    } else if (b.t === "para") {
      out.push(
        ...paragraphs(b.text, {
          bold: b.bold,
          align: b.align,
          size: b.small ? 18 : SIZE,
          color: b.small ? MUTED : undefined,
          hang: b.hang,
          after: 100,
        }),
      );
    }
  }
  return out;
}

const pageFooter = () =>
  new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ children: ["- ", PageNumber.CURRENT, " -"], size: 18, color: MUTED, font: FONT })],
      }),
    ],
  });

export function blocksToDocument(blocks: Block[], o: DocOptions = {}): Document {
  style = o.preset === "assembly" || blocks.some((b) => b.t === "cover") ? ASSEMBLY : BASE; // 표지가 있으면 총회 자료다
  try {
    return build(blocks, o);
  } finally {
    style = BASE;
  }
}

function build(blocks: Block[], o: DocOptions): Document {
  const cov = blocks.find((b) => b.t === "cover");
  const title = (blocks.find((b) => b.t === "title")?.text ?? (cov?.t === "cover" ? cov.lines.at(-1) : "") ?? "").replace(/\s+/g, "");
  // 'section' 앞(표지·목차)은 쪽 번호 없이, 뒤는 1쪽부터 센다. 없으면 한 구역에 번호를 단다
  const cut = blocks.findIndex((b) => b.t === "section");
  const parts =
    cut < 0
      ? [{ blocks, numbered: true }]
      : [
          { blocks: blocks.slice(0, cut), numbered: false },
          { blocks: blocks.slice(cut + 1), numbered: true },
        ];
  return new Document({
    creator: "학생회 업무 AI",
    title,
    styles: { default: { document: { run: { font: FONT, size: SIZE }, paragraph: { spacing: { line: LINE_TWIPS, lineRule: LineRuleType.EXACT } } } } },
    // 머리글은 두지 않는다 (2026-11-28 사용자 결정) — 첫 쪽 본문의 마크·기관명(또는 표지)이 머리 역할, 쪽 번호만 바닥글에
    sections: parts.map((p) => ({
      properties: { type: SectionType.NEXT_PAGE, page: { size: PAGE, margin: MARGIN, ...(p.numbered && cut >= 0 ? { pageNumbers: { start: 1 } } : {}) } },
      ...(p.numbered ? { footers: { default: pageFooter() } } : {}),
      children: body(p.blocks, o.emblem),
    })),
  });
}

export const docxBlob = (blocks: Block[], o: DocOptions = {}): Promise<Blob> => Packer.toBlob(blocksToDocument(blocks, o));
