// 정산표 → 엑셀(.xlsx). 시트 1 '사업별 정산서'(총대 재무자료 매뉴얼의 열 순서), 시트 2 '예산 대비'.
// 금액은 숫자 칸(천 단위 쉼표 서식)이라 받은 사람이 그대로 SUM을 걸 수 있다. 브라우저 안에서만 만든다.

import ExcelJS from "exceljs";

import type { Issue, ProjectSummary } from "../settle.ts";

const MONEY = "#,##0";
const HEAD = { type: "pattern", pattern: "solid", fgColor: { argb: "FFF2F2F2" } } as const;
const THIN = { style: "thin", color: { argb: "FF999999" } } as const;
const BOX = { top: THIN, left: THIN, bottom: THIN, right: THIN };

export async function settleWorkbook(unit: string, summary: ProjectSummary[], issues: Issue[]): Promise<ExcelJS.Workbook> {
  const wb = new ExcelJS.Workbook();
  wb.creator = "학생회 업무 AI";

  const ws = wb.addWorksheet("사업별 정산서", { views: [{ state: "frozen", ySplit: 1 }] });
  ws.columns = [
    { header: "계정", width: 12 },
    { header: "월", width: 6 },
    { header: "일", width: 6 },
    { header: "사업명", width: 24 },
    { header: "상세내용", width: 30 },
    { header: "금액", width: 14 },
    { header: "영수증번호", width: 14 },
  ];
  for (const p of summary) {
    for (const r of p.rows) ws.addRow([r.account, r.month, r.day, p.project, r.detail, r.amount, r.receipt]);
    if (p.rows.length) {
      const total = ws.addRow(["", "", "", `${p.project} 합계`, "", p.spent, ""]);
      total.font = { bold: true };
    }
  }

  const vs = wb.addWorksheet("예산 대비", { views: [{ state: "frozen", ySplit: 1 }] });
  vs.columns = [
    { header: "사업명", width: 24 },
    { header: "인준 예산", width: 14 },
    { header: "결산", width: 14 },
    { header: "차액(예산-결산)", width: 16 },
    { header: "비고", width: 50 },
  ];
  for (const p of summary) {
    const note = issues.find((i) => i.text.includes(`'${p.project}'`))?.text ?? "";
    vs.addRow([p.project, p.budget ?? "예산 없음", p.spent, p.diff ?? "", note]);
  }
  const totalBudget = summary.reduce((s, p) => s + (p.budget ?? 0), 0);
  const totalSpent = summary.reduce((s, p) => s + p.spent, 0);
  vs.addRow(["합계", totalBudget, totalSpent, totalBudget - totalSpent, unit ? `영수증 번호 앞자리: ${unit}` : ""]).font = { bold: true };

  for (const sheet of [ws, vs]) {
    sheet.getRow(1).font = { bold: true };
    sheet.eachRow((row) =>
      row.eachCell({ includeEmpty: true }, (c, col) => {
        c.border = BOX;
        if (row.number === 1) {
          c.fill = HEAD;
          c.alignment = { horizontal: "center" };
        }
        if (typeof c.value === "number" && (sheet === vs ? col > 1 : col === 6)) c.numFmt = MONEY;
      }),
    );
  }
  return wb;
}

export async function settleXlsxBlob(unit: string, summary: ProjectSummary[], issues: Issue[]): Promise<Blob> {
  const wb = await settleWorkbook(unit, summary, issues);
  const buf = await wb.xlsx.writeBuffer();
  return new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}
