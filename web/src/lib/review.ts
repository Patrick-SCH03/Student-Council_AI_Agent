// 문서 검토 API 클라이언트. 서버는 파일·결과를 저장하지 않는다 — 확인한 표와 원문 텍스트를 화면이 들고 다닌다.
// 예외: 이용자가 '개선에 쓰도록 허락'하면(contribute) 가명 처리본을 보관하고, 확인 표에서 고친 값을 contributionId로 붙인다.

import { postJson, request } from "./http";
import type { BudgetDoc, Extracted, Finding } from "./review-model";

export * from "./review-model";

export function extractFile(file: File, contribute = false): Promise<Extracted> {
  return request(
    `/api/review/extract?filename=${encodeURIComponent(file.name)}${contribute ? "&contribute=true" : ""}`,
    { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file },
    "문서를 읽지 못했어요. 잠시 후 다시 시도해 주세요.",
  );
}

export async function checkDoc(doc: BudgetDoc, source: Finding[], contributionId: number | null = null): Promise<Finding[]> {
  const out = await postJson<{ findings: Finding[] }>(
    "/api/review/check",
    { doc, source, contribution_id: contributionId },
    "점검하지 못했어요. 잠시 후 다시 시도해 주세요.",
  );
  return out.findings;
}

export async function fetchNotes(doc: BudgetDoc, text: string, findings: Finding[]): Promise<Finding[]> {
  const out = await postJson<{ notes: Finding[] }>("/api/review/notes", { doc, text, findings }, "규정 메모를 만들지 못했어요.");
  return out.notes;
}
