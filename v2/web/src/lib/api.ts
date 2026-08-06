// FastAPI 백엔드 클라이언트: 타입 정의 + SSE 스트리밍 파서

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Citation = { source_file: string; snippet: string };

export type ReviewerResult = {
  violation: string;
  risk_level: string;
  reasoning: string;
  recommendation: string;
  citations: Citation[];
};

export type AuditorResult = {
  compliance: string;
  sanction_likelihood: string;
  reasoning: string;
  recommendation: string;
  citations: Citation[];
};

export type ChatResult = {
  query: string;
  route: string;
  risk_level: string | null;
  final_markdown: string;
  reviewer: ReviewerResult | null;
  auditor: AuditorResult | null;
  citations: Citation[];
  elapsed: number;
};

export type ChatEvent =
  | { type: "stage"; label: string; route?: string }
  | { type: "token"; content: string }
  | { type: "agent_done"; agent: "reviewer" | "auditor" }
  | ({ type: "result" } & ChatResult)
  | { type: "error"; message: string };

export type DocumentInfo = {
  doc_id: string;
  filename: string;
  chunks: number;
  created_at: string;
};

export type HealthInfo = {
  status: string;
  mock_mode: boolean;
  model: string;
  indexed_chunks: number;
};

/** POST /api/chat 의 SSE 응답을 이벤트 단위로 yield */
export async function* streamChat(
  query: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`서버 오류 (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE 이벤트는 빈 줄로 구분된다
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep).trim();
      buffer = buffer.slice(sep + 2);
      if (!raw.startsWith("data:")) continue;
      try {
        yield JSON.parse(raw.slice(5).trim()) as ChatEvent;
      } catch {
        // 손상된 이벤트는 무시
      }
    }
  }
}

export async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error("백엔드에 연결할 수 없습니다.");
  return res.json();
}

export async function fetchDocuments(): Promise<{
  documents: DocumentInfo[];
  indexed_chunks: number;
}> {
  const res = await fetch(`${API_BASE}/api/documents`);
  if (!res.ok) throw new Error("문서 목록을 불러오지 못했습니다.");
  return res.json();
}

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `업로드 실패 (${res.status})`);
  }
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/documents/${docId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("삭제에 실패했습니다.");
}
