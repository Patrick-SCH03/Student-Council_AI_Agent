// Word·엑셀 파일 내려받기. 무거운 생성 라이브러리는 버튼을 누를 때만 불러온다(첫 화면 용량을 늘리지 않게).

import { todayKst } from "../format.ts";
import type { Block } from "./blocks.ts";
import type { Issue, ProjectSummary } from "../settle.ts";

export type FileSpec = { label: string; name: string; make: () => Promise<Blob> };

/** 파일 이름에 쓸 수 없는 글자를 빼고 날짜를 붙인다: '간식드리미 사업계획서_2026-11-28.docx' */
export function fileName(base: string, ext: "docx" | "xlsx", today = new Date()): string {
  const day = todayKst(today);
  const safe =
    base
      .replace(/[\\/:*?"<>|]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 60) || "문서";
  return `${safe}_${day}.${ext}`;
}

/** 인하대 마크(public/emblem.png). 못 불러오면 마크 없이 만든다 */
async function emblem(): Promise<Uint8Array | undefined> {
  try {
    const res = await fetch("/emblem.png");
    return res.ok ? new Uint8Array(await res.arrayBuffer()) : undefined;
  } catch {
    return undefined;
  }
}

export async function wordBlob(blocks: Block[]): Promise<Blob> {
  const [{ docxBlob }, mark] = await Promise.all([import("./docx.ts"), emblem()]);
  return docxBlob(blocks, { emblem: mark });
}

export async function excelBlob(unit: string, summary: ProjectSummary[], issues: Issue[]): Promise<Blob> {
  const { settleXlsxBlob } = await import("./xlsx.ts");
  return settleXlsxBlob(unit, summary, issues);
}

export function word(base: string, blocks: () => Block[], label = "Word로 받기"): FileSpec {
  return { label, name: fileName(base, "docx"), make: () => wordBlob(blocks()) };
}

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
