"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type AuditorResult,
  type ChatResult,
  type Citation,
  type HistoryItem,
  type ReviewerResult,
  fetchHealth,
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
};

/* ---------------------------------------------------------------- 컴포넌트 */

type AssistantState = {
  stage: string | null;
  tokens: string;
  reviewer: ReviewerResult | null;
  auditor: AuditorResult | null;
  result: ChatResult | null;
  error: string | null;
  route: string | null;
};

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; state: AssistantState };

const emptyAssistant = (): AssistantState => ({
  stage: "질문 분석 중...",
  tokens: "",
  reviewer: null,
  auditor: null,
  result: null,
  error: null,
  route: null,
});

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const styles: Record<string, string> = {
    높음: "bg-rose-50 text-rose-600 ring-rose-200",
    보통: "bg-amber-50 text-amber-600 ring-amber-200",
    낮음: "bg-green-50 text-green-600 ring-green-200",
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

function Markdown({ text }: { text: string }) {
  return (
    <div className="max-w-none text-[15px] leading-[1.7] text-slate-700 [&_h3]:mt-5 [&_h3]:mb-1.5 [&_h3]:text-[15px] [&_h3]:font-bold [&_h3]:text-slate-900 [&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-indigo-200 [&_blockquote]:pl-3 [&_blockquote]:text-slate-500 [&_strong]:font-bold [&_strong]:text-slate-900">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function CitationChips({ citations }: { citations: Citation[] }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const unique = [
    ...new Map(citations.map((c) => [c.source_file, c])).values(),
  ];
  if (unique.length === 0) return null;
  return (
    <div className="mt-5">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-400">
        근거 문서
      </p>
      <div className="flex flex-wrap gap-1.5">
        {unique.map((c, i) => (
          <button
            key={i}
            type="button"
            onClick={() => setOpenIdx(openIdx === i ? null : i)}
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
        <div className="mt-2 rounded-xl border border-indigo-100 bg-indigo-50/50 px-4 py-3 text-[13px] leading-relaxed text-slate-600">
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
          className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-90"
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
  const { stage, tokens, result, error, route } = state;
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
          <p className="flex items-center gap-2 text-sm text-rose-600">
            <Icon path={paths.alert} className="h-4 w-4" />
            {error}
          </p>
        ) : (
          <>
            {!result && stage && (
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-500">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
                {stage}
                <span className="text-xs text-slate-400">보통 30–40초</span>
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
                        ? "bg-green-50 text-green-600 ring-green-200"
                        : "active" in step && step.active
                          ? "bg-indigo-50 text-indigo-600 ring-indigo-200"
                          : "bg-slate-50 text-slate-400 ring-slate-200"
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
                <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">
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
              <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
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
                <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
                  <Icon path={paths.clock} className="h-3.5 w-3.5" />
                  {result.elapsed.toFixed(1)}초
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

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mockMode, setMockMode] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(0);

  useEffect(() => {
    fetchHealth()
      .then((h) => setMockMode(h.mock_mode))
      .catch(() => {});
  }, []);

  // 새로고침해도 대화가 유지되도록 localStorage에서 복원.
  // localStorage는 서버에 없으므로 초기 state로 읽으면 하이드레이션 불일치가 난다.
  // 마운트 후 복원이 유일한 안전한 방법이라 set-state-in-effect 규칙을 의도적으로 예외 처리한다.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) return;
      const parsed = JSON.parse(saved) as Message[];
      if (!Array.isArray(parsed) || parsed.length === 0) return;
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
      const done = messages.filter(
        (m) => m.role === "user" || m.state.result || m.state.error,
      );
      if (done.length > 0) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(done.slice(-20)));
      }
    } catch {
      // 저장 실패(용량 초과 등)는 무시
    }
  }, [messages, busy]);

  const clearChat = () => {
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY);
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
      if (
        q.role === "user" &&
        a.role === "assistant" &&
        a.state.result?.final_markdown
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
    const userId = ++idRef.current;
    const assistantId = ++idRef.current;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", text: query },
      { id: assistantId, role: "assistant", state: emptyAssistant() },
    ]);

    try {
      let tokens = "";
      for await (const event of streamChat(query, history)) {
        if (event.type === "stage") {
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
          updateAssistant(assistantId, { tokens });
        } else if (event.type === "result") {
          updateAssistant(assistantId, { result: event, stage: null });
        } else if (event.type === "error") {
          updateAssistant(assistantId, { error: event.message, stage: null });
        }
      }
    } catch (e) {
      updateAssistant(assistantId, {
        error: e instanceof Error ? e.message : "알 수 없는 오류",
        stage: null,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col py-6">
      {mockMode && (
        <div className="mb-4 flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-700">
          <Icon path={paths.alert} className="h-4 w-4" />
          <span>
            GEMINI_API_KEY가 설정되지 않아 <b>목업 모드</b>로 동작 중입니다.
          </span>
        </div>
      )}

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
              규정 검토 · 감사 분석 · 종합 권고를 AI 에이전트가 병렬로 수행합니다
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
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-3 text-[15px] font-medium leading-snug text-white">
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
          className={`flex items-center gap-2 rounded-[24px] border border-slate-200 bg-white p-2 pl-5 transition focus-within:border-indigo-300 ${CARD_SHADOW}`}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="학생회 규정·재정·감사에 대해 물어보세요"
            maxLength={1000}
            className="min-w-0 flex-1 bg-transparent py-2.5 text-[15px] font-medium text-slate-700 placeholder-slate-400 outline-none"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            aria-label="질문 보내기"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white transition hover:bg-indigo-700 disabled:opacity-40"
          >
            {busy ? (
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-white" />
            ) : (
              <Icon path={paths.send} className="h-5 w-5" />
            )}
          </button>
        </form>
        <p className="mt-2.5 text-center text-xs font-medium text-slate-400">
          AI 분석은 참고용입니다. 최종 판단은 감사위원회 및 관련 규정을 따릅니다.
        </p>
      </div>
    </div>
  );
}
