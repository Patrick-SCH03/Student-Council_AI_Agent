"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type AuditorResult,
  type ChatResult,
  type Citation,
  type HistoryItem,
  type ReviewerResult,
  ChatBlockedError,
  fetchHealth,
  sendFeedback,
  streamChat,
} from "@/lib/api";

const EXAMPLES = [
  "행사 물품 구매 시 증빙서류는 무엇을 준비해야 하나요?",
  "동아리 지원금 사용 내역을 공개해야 하나요?",
  "예산 변경 시 필요한 승인 절차는 무엇인가요?",
  "감사에서 어떤 처분을 받을 수 있나요?",
];

// AI Chatbot UI Kit 카드 섀도 토큰
const CARD_SHADOW =
  "shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.08),0px_4px_6px_-2px_rgba(16,24,40,0.03)]";

/* ---------------------------------------------------------------- 아이콘
   이모지 대신 일관된 1.6px 스트로크 아이콘 세트 (Phosphor 스타일) */

function Icon({
  path,
  className = "h-4 w-4",
}: {
  path: React.ReactNode;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden
    >
      {path}
    </svg>
  );
}

const paths = {
  doc: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 16.5h4" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7" />,
  plus: <path d="M12 5v14M5 12h14" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  chevron: <path d="m9 6 6 6-6 6" />,
  alert: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 8v4.5" />
      <path d="M12 15.8v.2" />
    </>
  ),
  send: (
    <path
      d="M4.4 11.05 19.2 4.3c.9-.4 1.8.5 1.4 1.4l-6.75 14.8c-.44.96-1.85.85-2.13-.17l-1.5-5.46a1.2 1.2 0 0 0-.84-.84l-5.46-1.5c-1.02-.28-1.13-1.69-.17-2.13Z"
      fill="currentColor"
      stroke="none"
    />
  ),
  reply: <path d="M9 10 4 15l5 5M4 15h11a5 5 0 0 0 5-5V7" />,
  thumbUp: (
    <path d="M7 10v10H4V10h3Zm3 10V10l4-6a2 2 0 0 1 3 2l-1 4h4.5a2 2 0 0 1 2 2.4l-1.3 6A2 2 0 0 1 17.2 20H10Z" />
  ),
  thumbDown: (
    <path d="M7 14V4H4v10h3Zm3-10v10l4 6a2 2 0 0 0 3-2l-1-4h4.5a2 2 0 0 0 2-2.4l-1.3-6A2 2 0 0 0 17.2 4H10Z" />
  ),
};

function FeedbackButtons({ analysisId, token }: { analysisId: number; token: string }) {
  // 전송이 끝난 뒤에만 감사 표시를 한다. 먼저 바꾸면 실패해도 성공처럼 보이고 재시도할 길이 없다.
  const [status, setStatus] = useState<"idle" | "sending" | "done" | "failed">("idle");
  const [helpfulSent, setHelpfulSent] = useState(true);

  const submit = async (helpful: boolean) => {
    setStatus("sending");
    setHelpfulSent(helpful);
    try {
      await sendFeedback(analysisId, helpful, token);
      setStatus("done");
    } catch {
      setStatus("failed");
    }
  };

  if (status === "done") {
    return (
      <span role="status" className="text-xs font-medium text-slate-500">
        {helpfulSent ? "의견 감사해요" : "의견 감사해요. 개선에 참고할게요"}
      </span>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <span role={status === "failed" ? "alert" : undefined} className="text-xs font-medium text-slate-500">
        {status === "failed" ? "전송하지 못했어요 · 다시 눌러 주세요" : "도움이 되었나요?"}
      </span>
      {[
        { helpful: true, icon: paths.thumbUp, label: "도움됨" },
        { helpful: false, icon: paths.thumbDown, label: "부족함" },
      ].map((b) => (
        <button
          key={b.label}
          type="button"
          onClick={() => submit(b.helpful)}
          disabled={status === "sending"}
          aria-label={b.label}
          title={b.label}
          className="rounded-full border border-slate-200 p-1.5 text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-50"
        >
          <Icon path={b.icon} className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- 컴포넌트 */

type AssistantState = {
  stage: string | null;
  tokens: string;
  reviewer: ReviewerResult | null;
  auditor: AuditorResult | null;
  result: ChatResult | null;
  error: string | null;
  blocked: boolean; // 일일 한도 초과 (오류가 아닌 안내로 표시)
  route: string | null;
};

type Message =
  // at: 질문한 시각 — 브라우저 저장본을 턴 단위로 만료시킨다
  | { id: number; role: "user"; text: string; at?: number }
  | { id: number; role: "assistant"; state: AssistantState };

const emptyAssistant = (): AssistantState => ({
  stage: "질문 분석 중...",
  tokens: "",
  reviewer: null,
  auditor: null,
  result: null,
  error: null,
  blocked: false,
  route: null,
});

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const styles: Record<string, string> = {
    높음: "bg-rose-50 text-rose-700 ring-rose-200",
    보통: "bg-amber-50 text-amber-700 ring-amber-200",
    낮음: "bg-green-50 text-green-700 ring-green-200",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold ring-1 ${
        styles[level] ?? "bg-slate-100 text-slate-600 ring-slate-200"
      }`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      위험도 {level}
    </span>
  );
}

// 한글에는 이탤릭 자족이 없어 브라우저가 글자를 기계적으로 기울인다.
// 획 균형이 무너져 다른 서체처럼 보이므로, 강조는 기울임 대신 옅은 색으로 준다.
const MARKDOWN_STYLE =
  "max-w-none text-[15px] leading-[1.7] text-slate-700 [&_h3]:mt-5 [&_h3]:mb-1.5 [&_h3]:text-[15px] [&_h3]:font-bold [&_h3]:text-slate-900 [&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-indigo-200 [&_blockquote]:pl-3 [&_blockquote]:text-slate-500 [&_strong]:font-bold [&_strong]:text-slate-900 [&_em]:not-italic [&_em]:text-slate-500 [overflow-wrap:anywhere] [&_a]:font-medium [&_a]:text-indigo-700 [&_a]:underline [&_a]:underline-offset-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-slate-50 [&_pre]:p-3 [&_pre]:text-[13px] [&_table]:my-2 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1";

// 입력창 타이핑·스트리밍 때 페이지 전체가 다시 그려져도, 글이 같으면 다시 파싱하지 않는다
const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className={MARKDOWN_STYLE}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]} unwrapDisallowed>{text}</ReactMarkdown>
    </div>
  );
});

function CitationChips({ citations }: { citations: Citation[] }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const snippetId = useId();
  const unique = [
    ...new Map(citations.map((c) => [c.source_file, c])).values(),
  ];
  if (unique.length === 0) return null;
  return (
    <div className="mt-5">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-500">
        근거 문서
      </p>
      <div className="flex flex-wrap gap-1.5">
        {unique.map((c, i) => (
          <button
            key={i}
            type="button"
            onClick={() => setOpenIdx(openIdx === i ? null : i)}
            aria-expanded={openIdx === i}
            aria-controls={snippetId}
            className={`inline-flex max-w-full items-center gap-1.5 truncate rounded-full px-3 py-1.5 text-xs font-medium transition ${
              openIdx === i
                ? "bg-indigo-600 text-white"
                : "bg-indigo-50 text-indigo-600 hover:bg-indigo-100"
            }`}
          >
            <Icon path={paths.doc} className="h-3.5 w-3.5" />
            {c.source_file}
          </button>
        ))}
      </div>
      {openIdx !== null && unique[openIdx] && (
        <div id={snippetId} className="mt-2 rounded-xl border border-indigo-100 bg-indigo-50/50 px-4 py-3 text-[13px] leading-relaxed text-slate-600 [overflow-wrap:anywhere]">
          {unique[openIdx].snippet}
        </div>
      )}
    </div>
  );
}

function AgentDetail({
  icon,
  name,
  verdict,
  children,
}: {
  icon: React.ReactNode;
  name: string;
  verdict: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group rounded-2xl border border-slate-200 bg-slate-50/60 transition hover:border-slate-300">
      <summary className="flex cursor-pointer select-none items-center gap-2.5 px-4 py-3 [&::-webkit-details-marker]:hidden">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-slate-500 ring-1 ring-slate-200">
          {icon}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-bold text-slate-800">{name}</span>
          <span className="block truncate text-xs font-medium text-slate-500">
            {verdict}
          </span>
        </span>
        <Icon
          path={paths.chevron}
          className="h-4 w-4 text-slate-500 transition-transform group-open:rotate-90 motion-reduce:transition-none"
        />
      </summary>
      <div className="border-t border-slate-200 px-4 py-3 text-sm">{children}</div>
    </details>
  );
}

function AssistantBubble({
  state,
  isLast,
  onFollowup,
}: {
  state: AssistantState;
  isLast: boolean;
  onFollowup: (q: string) => void;
}) {
  const { stage, tokens, result, error, blocked, route } = state;
  const [copied, setCopied] = useState(false);
  const reviewer = result?.reviewer ?? state.reviewer;
  const auditor = result?.auditor ?? state.auditor;
  // 스트리밍 중 후속 질문 블록(<followups>)은 표시에서 제외
  const streamingText = (result?.final_markdown || tokens).split("<followups>")[0];

  const copyAnswer = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(
        `${result.risk_level ? `[위험도 ${result.risk_level}]\n\n` : ""}${result.final_markdown}`,
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 클립보드 권한 거부 시 무시
    }
  };

  return (
    <div className="flex items-start gap-2.5">
      <span
        aria-hidden
        className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-extrabold text-white"
      >
        AI
      </span>
      <div
        className={`min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}
      >
        {error ? (
          <p
            role="alert"
            className={`flex items-center gap-2 text-sm ${
              blocked ? "font-medium text-amber-700" : "text-rose-700"
            }`}
          >
            <Icon path={paths.alert} className="h-4 w-4" />
            {error}
          </p>
        ) : (
          <>
            {!result && stage && (
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-500">
                <span aria-hidden className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600 motion-reduce:animate-none" />
                {stage}
                {/* 배포본 규정 질의 응답 중앙값 9.9초 · p90 13초 (2026-09 실측) */}
                <span className="text-xs text-slate-500">보통 10초 안팎</span>
              </div>
            )}

            {route === "regulation" && !result && (
              <div className="mb-4 flex flex-wrap gap-1.5 text-xs font-medium">
                {[
                  { label: "규정 검토", done: !!reviewer },
                  { label: "감사 분석", done: !!auditor },
                  { label: "종합 조정", done: false, active: !!reviewer && !!auditor },
                ].map((step) => (
                  <span
                    key={step.label}
                    className={`inline-flex items-center gap-1 rounded-full px-3 py-1 ring-1 ${
                      step.done
                        ? "bg-green-50 text-green-700 ring-green-200"
                        : "active" in step && step.active
                          ? "bg-indigo-50 text-indigo-700 ring-indigo-200"
                          : "bg-slate-50 text-slate-500 ring-slate-200"
                    }`}
                  >
                    {step.done && <Icon path={paths.check} className="h-3 w-3" />}
                    {step.label}
                  </span>
                ))}
              </div>
            )}

            {result?.risk_level && (
              <div className="mb-3">
                <RiskBadge level={result.risk_level} />
              </div>
            )}

            {streamingText && <Markdown text={streamingText} />}

            {(reviewer || auditor) && route !== "general" && (
              <div className="mt-5 flex flex-col gap-2">
                {reviewer && (
                  <AgentDetail
                    icon={<Icon path={paths.doc} className="h-4 w-4" />}
                    name="규정 검토"
                    verdict={`${reviewer.violation} · 위험도 ${reviewer.risk_level}`}
                  >
                    <Markdown text={reviewer.reasoning} />
                    <p className="mt-2 text-slate-500">
                      <b className="text-slate-700">권고</b> · {reviewer.recommendation}
                    </p>
                  </AgentDetail>
                )}
                {auditor && (
                  <AgentDetail
                    icon={<Icon path={paths.search} className="h-4 w-4" />}
                    name="감사 분석"
                    verdict={`${auditor.compliance} · 처분 가능성 ${auditor.sanction_likelihood}`}
                  >
                    <Markdown text={auditor.reasoning} />
                    <p className="mt-2 text-slate-500">
                      <b className="text-slate-700">권고</b> · {auditor.recommendation}
                    </p>
                  </AgentDetail>
                )}
              </div>
            )}

            {result && <CitationChips citations={result.citations} />}

            {result && isLast && (result.followups?.length ?? 0) > 0 && (
              <div className="mt-5 flex flex-col items-start gap-1.5">
                <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                  이어서 물어보기
                </p>
                {result.followups.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => onFollowup(q)}
                    className="inline-flex items-start gap-2 rounded-xl border border-indigo-100 bg-indigo-50/60 px-3.5 py-2 text-left text-[13px] font-medium text-indigo-700 transition hover:border-indigo-300 hover:bg-indigo-50"
                  >
                    <Icon path={paths.reply} className="mt-0.5 h-3.5 w-3.5 -scale-y-100" />
                    {q}
                  </button>
                ))}
              </div>
            )}

            {result && (
              <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={copyAnswer}
                  className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600"
                >
                  <Icon
                    path={copied ? paths.check : paths.copy}
                    className="h-3.5 w-3.5"
                  />
                  {copied ? "복사됨" : "답변 복사"}
                </button>

                {/* 서명이 없는 옛 저장 답변은 평가할 수 없다 */}
                {result.analysis_id && result.feedback_token && (
                  <FeedbackButtons analysisId={result.analysis_id} token={result.feedback_token} />
                )}

                <span className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-slate-500">
                  <Icon path={paths.clock} className="h-3.5 w-3.5" />
                  {result.cached ? "이전 답변" : `${result.elapsed.toFixed(1)}초`}
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const STORAGE_KEY = "regulation-chat-v1";
// 공용 PC에서 다음 사용자가 지난 대화를 보지 않도록, 질문한 지 7일 지난 턴은 복원하지 않는다.
// 만료는 턴마다 질문 시각으로 판단한다 — 저장 시각으로 판단하면 복원할 때마다 갱신돼
// 읽기만 해도 보존 기간이 끝없이 늘어난다.
const STORAGE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

type SavedChat = { v: 2; messages: Message[] };

/** 저장할 대화만 고른다: 7일 안에 질문한, 답변이 완료된 규정 질의 쌍.
 *  - 범위 밖·실명 거절(route=general)과 오류 턴은 뺀다
 *  - 질문 원문 대신 서버가 마스킹한 질문(result.query)을 저장한다 — 실명이 아니어도
 *    전화번호·이메일이 든 질문이 브라우저에 그대로 남지 않도록 */
function persistable(msgs: Message[], now: number): Message[] {
  const out: Message[] = [];
  for (let i = 0; i < msgs.length - 1; i++) {
    const q = msgs[i];
    const a = msgs[i + 1];
    if (q.role !== "user" || a.role !== "assistant") continue;
    i++;
    const result = a.state.result;
    if (!result || result.route === "general") continue;
    if (!q.at || now - q.at > STORAGE_TTL_MS) continue;
    out.push({ ...q, text: result.query || q.text }, a);
  }
  return out;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // 진행 중 요청. '새 대화'가 이걸 끊어야 이전 답이 사라진 말풍선에 꽂히거나 busy가 남지 않는다
  const abortRef = useRef<AbortController | null>(null);
  const [mockMode, setMockMode] = useState(false);
  // 화면낭독기에 진행·완료를 알리는 문구 (토큰마다가 아니라 단계가 바뀔 때만)
  const [announce, setAnnounce] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(0);
  // 사용자가 위로 올려 이전 답변을 읽는 중이면 자동으로 끌어내리지 않는다
  const followRef = useRef(true);

  useEffect(() => {
    fetchHealth()
      .then((h) => setMockMode(h.mock_mode))
      .catch(() => {});
  }, []);

  // 새로고침해도 대화가 유지되도록 복원한다. localStorage는 서버에 없어
  // 초기 state로 읽으면 하이드레이션이 어긋나므로 마운트 후에 읽는다.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) return;
      const raw = JSON.parse(saved) as SavedChat | Message[];
      // 옛 형식(배열)은 질문 시각이 없어 만료를 판단할 수 없다 — 복원하지 않고 지운다
      const parsed = Array.isArray(raw) ? [] : persistable(raw.messages ?? [], Date.now());
      if (parsed.length === 0) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 하이드레이션 안전을 위한 마운트 후 복원
      setMessages(parsed);
      idRef.current = Math.max(...parsed.map((m) => m.id), 0);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  // 완료된 대화만 저장 (진행 중 스트리밍 상태는 제외)
  useEffect(() => {
    if (busy) return;
    try {
      const done = persistable(messages, Date.now());
      if (done.length > 0) {
        const payload: SavedChat = { v: 2, messages: done.slice(-20) };
        localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      } else if (messages.length > 0) {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // 저장 실패(용량 초과 등)는 무시
    }
  }, [messages, busy]);

  const clearChat = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
  };

  // 사용자가 직접 스크롤했을 때만 '따라가기'를 다시 판단한다. 코드가 일으킨 부드러운
  // 스크롤 도중의 위치로 판단하면 긴 답변 중간에 따라가기가 풀린다.
  useEffect(() => {
    const check = () =>
      setTimeout(() => {
        followRef.current =
          window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160;
      }, 120);
    const onKey = (e: KeyboardEvent) => {
      if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(e.key)) check();
    };
    window.addEventListener("wheel", check, { passive: true });
    window.addEventListener("touchmove", check, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", check);
      window.removeEventListener("touchmove", check);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (!followRef.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    bottomRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
  }, [messages]);

  const updateAssistant = (id: number, patch: Partial<AssistantState>) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id && m.role === "assistant"
          ? { ...m, state: { ...m.state, ...patch } }
          : m,
      ),
    );
  };

  /** 완료된 Q&A 쌍에서 후속 질문 컨텍스트를 구성 (최근 3개) */
  const buildHistory = (msgs: Message[]): HistoryItem[] => {
    const pairs: HistoryItem[] = [];
    for (let i = 0; i < msgs.length - 1; i++) {
      const q = msgs[i];
      const a = msgs[i + 1];
      // 범위 밖·실명 거절 안내는 대화 맥락이 아니다 — 후속 질문 재작성에 섞이지 않게 뺀다
      if (
        q.role === "user" &&
        a.role === "assistant" &&
        a.state.result?.final_markdown &&
        a.state.result.route !== "general"
      ) {
        pairs.push({
          question: q.text,
          answer: a.state.result.final_markdown.slice(0, 1200),
        });
      }
    }
    return pairs.slice(-3);
  };

  const send = async (text: string) => {
    const query = text.trim();
    if (!query || busy) return;
    setBusy(true);
    setInput("");

    const history = buildHistory(messages);
    const controller = new AbortController();
    abortRef.current = controller;
    followRef.current = true; // 방금 보낸 질문의 답은 따라간다
    setAnnounce("질문을 보냈어요. 분석 중이에요.");
    const userId = ++idRef.current;
    const assistantId = ++idRef.current;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", text: query, at: Date.now() },
      { id: assistantId, role: "assistant", state: emptyAssistant() },
    ]);

    try {
      let tokens = "";
      let flushScheduled = false;
      let finished = false; // result 또는 error 이벤트를 받았는지
      for await (const event of streamChat(query, history, controller.signal)) {
        if (event.type === "stage") {
          setAnnounce(event.label);
          updateAssistant(assistantId, {
            stage: event.label,
            ...(event.route ? { route: event.route } : {}),
          });
        } else if (event.type === "agent_done") {
          if (event.agent === "reviewer") {
            updateAssistant(assistantId, { reviewer: event.data });
          } else {
            updateAssistant(assistantId, { auditor: event.data });
          }
        } else if (event.type === "token") {
          tokens += event.content;
          // 토큰마다 렌더하면 마크다운 전체를 매번 다시 파싱한다 — 프레임당 한 번만 반영
          if (!flushScheduled) {
            flushScheduled = true;
            requestAnimationFrame(() => {
              flushScheduled = false;
              updateAssistant(assistantId, { tokens });
            });
          }
        } else if (event.type === "result") {
          finished = true;
          setAnnounce(
            event.route === "general"
              ? "안내를 받았어요."
              : `답변이 도착했어요.${event.risk_level ? ` 위험도 ${event.risk_level}.` : ""}`,
          );
          updateAssistant(assistantId, { result: event, stage: null });
        } else if (event.type === "error") {
          finished = true;
          updateAssistant(assistantId, { error: event.message, stage: null });
        }
      }
      // 서버가 result 없이 스트림을 닫으면(상류 중단·프록시 절단) 분석 중 표시가 남는다
      if (!finished && !controller.signal.aborted) {
        updateAssistant(assistantId, {
          error: "응답이 중간에 끊겼어요. 잠시 후 다시 시도해 주세요.",
          stage: null,
        });
      }
    } catch (e) {
      if (controller.signal.aborted) return; // 새 대화로 취소됨 — 말풍선은 이미 없다
      updateAssistant(assistantId, {
        error:
          e instanceof ChatBlockedError
            ? e.message
            : e instanceof Error
              ? e.message
              : "알 수 없는 오류가 생겼어요.",
        blocked: e instanceof ChatBlockedError,
        stage: null,
      });
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setBusy(false);
      }
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col py-6">
      {mockMode && (
        <div className="mb-4 flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-700">
          <Icon path={paths.alert} className="h-4 w-4" />
          <span>
            API 키(GEMINI_API_KEY)가 없어 <b>목업 모드</b>로 동작 중이에요.
          </span>
        </div>
      )}

      <div className="sr-only" role="status" aria-live="polite">
        {announce}
      </div>

      {/* 대화가 시작돼도 페이지 제목은 남아 있어야 헤딩으로 이동할 수 있다 */}
      {messages.length > 0 && <h1 className="sr-only">학생회 규정 AI 어시스턴트</h1>}

      {messages.length > 0 && (
        <div className="mb-3 flex justify-end">
          <button
            type="button"
            onClick={clearChat}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-medium text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600"
          >
            <Icon path={paths.plus} className="h-3.5 w-3.5" />
            새 대화
          </button>
        </div>
      )}

      <div className="flex-1 space-y-5">
        {messages.length === 0 && (
          <div className="mt-16 text-center">
            <p className="text-[13px] font-bold uppercase tracking-[0.2em] text-indigo-500">
              INHA Student Council
            </p>
            <h1 className="mt-2 text-[32px] font-extrabold tracking-tight text-slate-900">
              무엇을 도와드릴까요?
            </h1>
            <p className="mt-2 text-[15px] font-medium text-slate-500">
              규정 검토 · 감사 분석 · 종합 권고를 AI 에이전트가 동시에 분석해요
            </p>
            <div className="mx-auto mt-9 grid max-w-xl gap-2.5 sm:grid-cols-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => send(ex)}
                  className={`group flex items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3.5 text-left text-sm font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 ${CARD_SHADOW}`}
                >
                  {ex}
                  <Icon
                    path={paths.chevron}
                    className="h-4 w-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-indigo-400"
                  />
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-indigo-600 px-4 py-3 text-[15px] font-medium leading-snug text-white [overflow-wrap:anywhere]">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={m.id} className="max-w-full">
              <AssistantBubble
                state={m.state}
                isLast={m.id === messages[messages.length - 1]?.id}
                onFollowup={send}
              />
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <div className="sticky bottom-0 mt-6 bg-slate-50 pb-4 pt-2">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className={`flex items-center gap-2 rounded-[24px] border border-slate-200 bg-white p-2 pl-5 transition focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-500/20 ${CARD_SHADOW}`}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="질문 입력"
            placeholder="학생회 규정·재정·감사에 대해 물어보세요"
            maxLength={1000}
            className="min-w-0 flex-1 bg-transparent py-2.5 text-[15px] font-medium text-slate-700 placeholder-slate-500 outline-none"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            aria-label="질문 보내기"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white transition hover:bg-indigo-700 disabled:opacity-40"
          >
            {busy ? (
              <span aria-hidden className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-white motion-reduce:animate-none" />
            ) : (
              <Icon path={paths.send} className="h-5 w-5" />
            )}
          </button>
        </form>
        <p className="mt-2.5 text-center text-xs font-medium text-slate-500">
          AI 분석은 참고용이에요. 최종 판단은 감사위원회와 관련 규정을 따라 주세요.
        </p>
      </div>
    </div>
  );
}
