// FastAPI 백엔드 클라이언트: 타입 정의 + SSE 스트리밍 파서

// 미설정 → 로컬 개발(백엔드 직접 호출), "/" 또는 "" → same-origin 상대 경로
// (프로덕션에서 Next rewrites 또는 Caddy가 /api를 백엔드로 프록시)
const _raw = process.env.NEXT_PUBLIC_API_URL;
export const API_BASE =
  _raw === undefined ? "http://localhost:8000" : _raw.replace(/\/+$/, "");

/* --- 관리자 인증 (운영 대시보드 전용) --------------------------------- */

const ADMIN_TOKEN_KEY = "admin-token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

export function clearAdminToken(): void {
  localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export class AuthError extends Error {}

/** 관리자 토큰을 붙여 요청하고, 인증 실패는 AuthError로 구분한다. */
export async function adminFetch(path: string): Promise<Response> {
  const token = getAdminToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (res.status === 401 || res.status === 503) {
    const body = await res.json().catch(() => null);
    throw new AuthError(body?.detail ?? "관리자 인증이 필요합니다.");
  }
  return res;
}

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
  followups: string[];
  reviewer: ReviewerResult | null;
  auditor: AuditorResult | null;
  citations: Citation[];
  elapsed: number;
};

export type ChatEvent =
  | { type: "stage"; label: string; route?: string }
  | { type: "token"; content: string }
  | {
      type: "agent_done";
      agent: "reviewer";
      data: ReviewerResult | null;
    }
  | {
      type: "agent_done";
      agent: "auditor";
      data: AuditorResult | null;
    }
  | ({ type: "result" } & ChatResult)
  | { type: "error"; message: string };

export type HistoryItem = { question: string; answer: string };

export type HealthInfo = {
  status: string;
  mock_mode: boolean;
  model: string;
  indexed_chunks: number;
};

/** POST /api/chat 의 SSE 응답을 이벤트 단위로 yield */
export async function* streamChat(
  query: string,
  history: HistoryItem[] = [],
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, history }),
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

