"use client";

import { useEffect, useRef, useState } from "react";

import {
  type HistoryItem,
  ChatBlockedError,
  fetchHealth,
  streamChat,
} from "@/lib/api";
import {
  type AssistantState,
  type Message,
  AssistantBubble,
  CARD_SHADOW,
  Icon,
  emptyAssistant,
  paths,
} from "@/components/chat/parts";

const EXAMPLES = [
  "행사 물품 구매 시 증빙서류는 무엇을 준비해야 하나요?",
  "동아리 지원금 사용 내역을 공개해야 하나요?",
  "예산 변경 시 필요한 승인 절차는 무엇인가요?",
  "감사에서 어떤 처분을 받을 수 있나요?",
];

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
            API 키(CLAUDE_API_KEY·VOYAGE_API_KEY)가 없어 <b>목업 모드</b>로 동작 중이에요.
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
