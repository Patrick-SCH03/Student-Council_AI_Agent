// FastAPI 백엔드 클라이언트: 타입 정의 + SSE 스트리밍 파서

// 미설정이면 로컬 개발용 주소, "/" 또는 ""이면 same-origin 상대 경로.
// 배포본은 백엔드 주소를 직접 지정한다 (프록시를 거치면 스트리밍이 타임아웃에 걸린다).
const _raw = process.env.NEXT_PUBLIC_API_URL;
export const API_BASE =
  _raw === undefined ? "http://localhost:8000" : _raw.replace(/\/+$/, "");

/* --- 익명 방문자 식별 (일일 한도 계산·트래픽 집계용) ------------------- */

const VISITOR_ID_KEY = "visitor-id";

export function getVisitorId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    let id = localStorage.getItem(VISITOR_ID_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(VISITOR_ID_KEY, id);
    }
    return id;
  } catch {
    return null; // localStorage 차단 환경
  }
}

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
    throw new AuthError(body?.detail ?? "관리자 인증이 필요해요.");
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
  analysis_id: number | null;
  // 이 답변을 평가할 수 있다는 서버 서명 (옛 저장 답변에는 없다)
  feedback_token?: string;
  cached?: boolean;
};

/** 답변 만족도 전송. 실패하면 던져서 호출 쪽이 재시도를 안내하게 한다. */
export async function sendFeedback(
  analysisId: number,
  helpful: boolean,
  token: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis_id: analysisId,
      helpful,
      visitor_id: getVisitorId(),
      token,
    }),
  });
  if (!res.ok) throw new Error(`피드백 전송 실패 (${res.status})`);
}

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
  version?: string;
  mock_mode: boolean;
  model: string;
  indexed_chunks: number;
};

/** 일일 한도 초과 등 서버가 사유를 알려준 경우 */
export class ChatBlockedError extends Error {}

/** 이 시간 동안 아무 이벤트도 오지 않으면 연결을 끊는다 (상류 장애 시 스피너 영구 표시 방지) */
const STREAM_IDLE_TIMEOUT_MS = 90_000;

/** POST /api/chat 의 SSE 응답을 이벤트 단위로 yield */
export async function* streamChat(
  query: string,
  history: HistoryItem[] = [],
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort(); // 이미 취소된 signal이면 요청을 시작하지 않는다
  signal?.addEventListener("abort", abort);
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const resetIdle = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(abort, STREAM_IDLE_TIMEOUT_MS);
  };

  try {
    resetIdle();
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, history, visitor_id: getVisitorId() }),
      signal: controller.signal,
    });
    if (res.status === 429) {
      const body = await res.json().catch(() => null);
      throw new ChatBlockedError(
        body?.detail ?? "오늘 이용 한도에 도달했어요. 내일 다시 이용해 주세요.",
      );
    }
    if (!res.ok || !res.body) {
      throw new Error(`서버 오류 (${res.status})`);
    }

    reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      resetIdle();
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
  } catch (e) {
    if (controller.signal.aborted && !signal?.aborted) {
      throw new Error("응답이 늦어져 연결을 끊었어요. 잠시 후 다시 시도해 주세요.");
    }
    throw e;
  } finally {
    clearTimeout(idleTimer);
    signal?.removeEventListener("abort", abort);
    // 소비자가 순회를 중단해도 서버 연결이 남지 않도록 reader를 닫는다
    reader?.cancel().catch(() => {});
  }
}

export type Limits = {
  daily_limit_total: number;
  daily_limit_per_user: number;
  daily_limit_per_ip: number;
  cache_ttl_hours: number;
  used_today: number;
};

export async function clearAnswerCache(): Promise<{ cleared: number }> {
  const token = getAdminToken();
  const res = await fetch(`${API_BASE}/api/cache/clear`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("캐시를 비우지 못했어요.");
  return res.json();
}

export async function updateLimits(
  values: Pick<
    Limits,
    | "daily_limit_total"
    | "daily_limit_per_user"
    | "daily_limit_per_ip"
    | "cache_ttl_hours"
  >,
): Promise<Limits> {
  const token = getAdminToken();
  const res = await fetch(`${API_BASE}/api/settings`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(values),
  });
  if (res.status === 401 || res.status === 503) {
    throw new AuthError("관리자 인증이 필요해요.");
  }
  if (!res.ok) throw new Error("저장하지 못했어요.");
  return res.json();
}

export async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error("백엔드에 연결할 수 없어요.");
  return res.json();
}

