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

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const styles: Record<string, string> = {
    높음: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
    보통: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    낮음: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        styles[level] ?? "bg-zinc-100 text-zinc-600"
      }`}
    >
      위험도 {level}
    </span>
  );
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-sm max-w-none leading-relaxed [&_h3]:mt-4 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-bold [&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-zinc-300 [&_blockquote]:pl-3 [&_blockquote]:text-zinc-500">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

function CitationChips({ citations }: { citations: Citation[] }) {
  // 칩에는 파일명만 보이므로 파일 단위로 중복 제거
  const unique = [
    ...new Map(citations.map((c) => [c.source_file, c])).values(),
  ];
  if (unique.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {unique.map((c, i) => (
        <span
          key={i}
          title={c.snippet}
          className="inline-flex max-w-full cursor-help items-center gap-1 truncate rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400"
        >
          📄 {c.source_file}
        </span>
      ))}
    </div>
  );
}

function AgentDetail({
  title,
  done,
  children,
}: {
  title: string;
  done: boolean;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium">
        {done ? "✅" : "⏳"} {title}
      </summary>
      <div className="border-t border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800">
        {children}
      </div>
    </details>
  );
}

function AssistantBubble({ state }: { state: AssistantState }) {
  const { stage, agentsDone, tokens, result, error, route } = state;
  const streamingText = result?.final_markdown || tokens;

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">❌ {error}</p>
      ) : (
        <>
          {!result && stage && (
            <div className="mb-2 flex items-center gap-2 text-sm text-zinc-500">
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600" />
              {stage}
            </div>
          )}

          {route === "regulation" && !result && (
            <div className="mb-3 flex gap-3 text-xs text-zinc-500">
              <span>{agentsDone.reviewer ? "✅" : "⏳"} 규정 검토</span>
              <span>{agentsDone.auditor ? "✅" : "⏳"} 감사 분석</span>
              <span>
                {agentsDone.reviewer && agentsDone.auditor ? "⏳" : "·"} 종합 조정
              </span>
            </div>
          )}

          {result?.risk_level && (
            <div className="mb-2">
              <RiskBadge level={result.risk_level} />
            </div>
          )}

          {streamingText && <Markdown text={streamingText} />}

          {result?.reviewer && result?.auditor && (
            <div className="mt-4 flex flex-col gap-2">
              <AgentDetail title="규정 검토 에이전트 상세" done>
                <p className="mb-1">
                  <b>판단:</b> {result.reviewer.violation} · 위험도{" "}
                  {result.reviewer.risk_level}
                </p>
                <Markdown text={result.reviewer.reasoning} />
                <p className="mt-2 text-zinc-600 dark:text-zinc-400">
                  <b>권고:</b> {result.reviewer.recommendation}
                </p>
              </AgentDetail>
              <AgentDetail title="감사 에이전트 상세" done>
                <p className="mb-1">
                  <b>판단:</b> {result.auditor.compliance} · 처분 가능성{" "}
                  {result.auditor.sanction_likelihood}
                </p>
                <Markdown text={result.auditor.reasoning} />
                <p className="mt-2 text-zinc-600 dark:text-zinc-400">
                  <b>권고:</b> {result.auditor.recommendation}
                </p>
              </AgentDetail>
            </div>
          )}

          {result && <CitationChips citations={result.citations} />}

          {result && (
            <p className="mt-3 text-right text-xs text-zinc-400">
              ⏱️ {result.elapsed.toFixed(1)}초
            </p>
          )}
        </>
      )}
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
    <div className="flex min-h-[calc(100vh-3.5rem)] flex-col py-6">
      {mockMode && (
        <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-300">
          ⚠️ OPENAI_API_KEY가 설정되지 않아 <b>목업 모드</b>로 동작 중입니다.
          실제 분석을 사용하려면 api/.env에 키를 설정하세요.
        </div>
      )}

      <div className="flex-1 space-y-4">
        {messages.length === 0 && (
          <div className="mt-16 text-center">
            <p className="text-lg font-medium">
              학생회 규정에 대해 무엇이든 물어보세요
            </p>
            <p className="mt-1 text-sm text-zinc-500">
              규정 검토 · 감사 분석 · 종합 권고를 AI 에이전트가 병렬로 수행합니다
            </p>
            <div className="mx-auto mt-6 flex max-w-md flex-col gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => send(ex)}
                  className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-left text-sm text-zinc-700 transition hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
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
              <div className="max-w-[85%] rounded-2xl bg-blue-600 px-4 py-2.5 text-sm text-white">
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

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="sticky bottom-0 mt-6 flex gap-2 border-t border-zinc-200 bg-zinc-50 py-4 dark:border-zinc-800 dark:bg-zinc-950"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 학생회비로 회식비 사용이 가능한가요?"
          maxLength={1000}
          className="flex-1 rounded-xl border border-zinc-300 bg-white px-4 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition disabled:opacity-40"
        >
          {busy ? "분석 중..." : "질문"}
        </button>
      </form>
    </div>
  );
}
