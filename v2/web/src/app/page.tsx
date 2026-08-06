"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type ChatResult,
  type Citation,
  fetchHealth,
  streamChat,
} from "@/lib/api";

const EXAMPLES = [
  "학생회비로 회식비 사용이 가능한가요?",
  "동아리 지원금 사용 내역을 공개해야 하나요?",
  "예산 변경 시 필요한 승인 절차는 무엇인가요?",
  "감사에서 어떤 처분을 받을 수 있나요?",
];

// AI Chatbot UI Kit 카드 섀도 토큰
const CARD_SHADOW =
  "shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.08),0px_4px_6px_-2px_rgba(16,24,40,0.03)]";

type AssistantState = {
  stage: string | null;
  agentsDone: { reviewer: boolean; auditor: boolean };
  tokens: string;
  result: ChatResult | null;
  error: string | null;
  route: string | null;
};

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; state: AssistantState };

const emptyAssistant = (): AssistantState => ({
  stage: "질문 분석 중...",
  agentsDone: { reviewer: false, auditor: false },
  tokens: "",
  result: null,
  error: null,
  route: null,
});

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
      <path
        d="M4.4 11.05 19.2 4.3c.9-.4 1.8.5 1.4 1.4l-6.75 14.8c-.44.96-1.85.85-2.13-.17l-1.5-5.46a1.2 1.2 0 0 0-.84-.84l-5.46-1.5c-1.02-.28-1.13-1.69-.17-2.13Z"
        fill="currentColor"
      />
    </svg>
  );
}

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const styles: Record<string, string> = {
    높음: "bg-rose-50 text-rose-600 ring-rose-200",
    보통: "bg-amber-50 text-amber-600 ring-amber-200",
    낮음: "bg-green-50 text-green-600 ring-green-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-bold ring-1 ${
        styles[level] ?? "bg-slate-100 text-slate-600 ring-slate-200"
      }`}
    >
      위험도 {level}
    </span>
  );
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="max-w-none text-[15px] leading-[1.65] text-slate-700 [&_h3]:mt-4 [&_h3]:mb-1 [&_h3]:text-[15px] [&_h3]:font-bold [&_h3]:text-slate-800 [&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-indigo-200 [&_blockquote]:pl-3 [&_blockquote]:text-slate-500 [&_strong]:text-slate-800">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

function CitationChips({ citations }: { citations: Citation[] }) {
  const unique = [
    ...new Map(citations.map((c) => [c.source_file, c])).values(),
  ];
  if (unique.length === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap gap-1.5">
      {unique.map((c, i) => (
        <span
          key={i}
          title={c.snippet}
          className="inline-flex max-w-full cursor-help items-center gap-1.5 truncate rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-600"
        >
          <svg viewBox="0 0 16 16" fill="none" className="h-3.5 w-3.5 shrink-0" aria-hidden>
            <path
              d="M9.5 1.5H4.75c-.69 0-1.25.56-1.25 1.25v10.5c0 .69.56 1.25 1.25 1.25h6.5c.69 0 1.25-.56 1.25-1.25V4.5l-3-3Z"
              stroke="currentColor"
              strokeWidth="1.3"
              strokeLinejoin="round"
            />
            <path d="M9.5 1.5v3h3" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
          </svg>
          {c.source_file}
        </span>
      ))}
    </div>
  );
}

function AgentDetail({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-slate-50/60">
      <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-bold text-slate-700">
        {title}
      </summary>
      <div className="border-t border-slate-200 px-4 py-3 text-sm">{children}</div>
    </details>
  );
}

function AssistantBubble({ state }: { state: AssistantState }) {
  const { stage, agentsDone, tokens, result, error, route } = state;
  const streamingText = result?.final_markdown || tokens;

  return (
    <div className="flex items-start gap-2.5">
      <span
        aria-hidden
        className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-extrabold text-white"
      >
        AI
      </span>
      <div
        className={`min-w-0 flex-1 rounded-2xl border border-slate-200 bg-white p-4 ${CARD_SHADOW}`}
      >
        {error ? (
          <p className="text-sm text-rose-600">❌ {error}</p>
        ) : (
          <>
            {!result && stage && (
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-500">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
                {stage}
              </div>
            )}

            {route === "regulation" && !result && (
              <div className="mb-3 flex flex-wrap gap-1.5 text-xs font-medium">
                {[
                  { label: "규정 검토", done: agentsDone.reviewer },
                  { label: "감사 분석", done: agentsDone.auditor },
                  {
                    label: "종합 조정",
                    done: false,
                    active: agentsDone.reviewer && agentsDone.auditor,
                  },
                ].map((step) => (
                  <span
                    key={step.label}
                    className={`rounded-full px-3 py-1 ring-1 ${
                      step.done
                        ? "bg-green-50 text-green-600 ring-green-200"
                        : "active" in step && step.active
                          ? "bg-indigo-50 text-indigo-600 ring-indigo-200"
                          : "bg-slate-50 text-slate-400 ring-slate-200"
                    }`}
                  >
                    {step.done ? "✓ " : ""}
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

            {result?.reviewer && result?.auditor && (
              <div className="mt-4 flex flex-col gap-2">
                <AgentDetail title="📋 규정 검토 에이전트 상세">
                  <p className="mb-1 text-slate-700">
                    <b>판단:</b> {result.reviewer.violation} · 위험도{" "}
                    {result.reviewer.risk_level}
                  </p>
                  <Markdown text={result.reviewer.reasoning} />
                  <p className="mt-2 text-slate-500">
                    <b>권고:</b> {result.reviewer.recommendation}
                  </p>
                </AgentDetail>
                <AgentDetail title="🔍 감사 에이전트 상세">
                  <p className="mb-1 text-slate-700">
                    <b>판단:</b> {result.auditor.compliance} · 처분 가능성{" "}
                    {result.auditor.sanction_likelihood}
                  </p>
                  <Markdown text={result.auditor.reasoning} />
                  <p className="mt-2 text-slate-500">
                    <b>권고:</b> {result.auditor.recommendation}
                  </p>
                </AgentDetail>
              </div>
            )}

            {result && <CitationChips citations={result.citations} />}

            {result && (
              <p className="mt-3 text-right text-xs font-medium text-slate-400">
                ⏱️ {result.elapsed.toFixed(1)}초
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

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

  const send = async (text: string) => {
    const query = text.trim();
    if (!query || busy) return;
    setBusy(true);
    setInput("");

    const userId = ++idRef.current;
    const assistantId = ++idRef.current;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", text: query },
      { id: assistantId, role: "assistant", state: emptyAssistant() },
    ]);

    try {
      let agentsDone = { reviewer: false, auditor: false };
      let tokens = "";
      for await (const event of streamChat(query)) {
        if (event.type === "stage") {
          updateAssistant(assistantId, {
            stage: event.label,
            ...(event.route ? { route: event.route } : {}),
          });
        } else if (event.type === "agent_done") {
          agentsDone = { ...agentsDone, [event.agent]: true };
          updateAssistant(assistantId, { agentsDone });
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
        <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-700">
          ⚠️ GEMINI_API_KEY가 설정되지 않아 <b>목업 모드</b>로 동작 중입니다.
          실제 분석을 사용하려면 api/.env에 키를 설정하세요.
        </div>
      )}

      <div className="flex-1 space-y-5">
        {messages.length === 0 && (
          <div className="mt-14 text-center">
            <p className="text-[30px] font-extrabold tracking-tight text-slate-800">
              무엇을 도와드릴까요? <span aria-hidden>👋</span>
            </p>
            <p className="mt-2 text-[15px] font-medium text-slate-500">
              규정 검토 · 감사 분석 · 종합 권고를 AI 에이전트가 병렬로 수행합니다
            </p>
            <div className="mx-auto mt-8 grid max-w-xl gap-2.5 sm:grid-cols-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => send(ex)}
                  className={`rounded-2xl border border-slate-200 bg-white px-4 py-3.5 text-left text-sm font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 ${CARD_SHADOW}`}
                >
                  {ex}
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
              <AssistantBubble state={m.state} />
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
          className={`flex items-center gap-2 rounded-[24px] border border-slate-200 bg-white p-2 pl-5 ${CARD_SHADOW}`}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="예: 학생회비로 회식비 사용이 가능한가요?"
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
              <SendIcon />
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
