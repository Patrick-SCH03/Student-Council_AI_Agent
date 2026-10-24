"use client";

// 채팅 화면 조각: 아이콘·답변 말풍선·근거 칩·에이전트 상세 (page.tsx에서 옮김 — 동작 동일)


import { memo, useId, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type AuditorResult,
  type ChatResult,
  type Citation,
  type ReviewerResult,
  sendFeedback,
} from "@/lib/api";
import { CARD_SHADOW } from "@/lib/ui";

export { CARD_SHADOW };


/* ---------------------------------------------------------------- 아이콘
   이모지 대신 일관된 1.6px 스트로크 아이콘 세트 (Phosphor 스타일) */

export function Icon({
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

export const paths = {
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

export function FeedbackButtons({ analysisId, token }: { analysisId: number; token: string }) {
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

export type AssistantState = {
  stage: string | null;
  tokens: string;
  reviewer: ReviewerResult | null;
  auditor: AuditorResult | null;
  result: ChatResult | null;
  error: string | null;
  blocked: boolean; // 일일 한도 초과 (오류가 아닌 안내로 표시)
  route: string | null;
};

export type Message =
  // at: 질문한 시각 — 브라우저 저장본을 턴 단위로 만료시킨다
  | { id: number; role: "user"; text: string; at?: number }
  | { id: number; role: "assistant"; state: AssistantState };

export const emptyAssistant = (): AssistantState => ({
  stage: "질문 분석 중...",
  tokens: "",
  reviewer: null,
  auditor: null,
  result: null,
  error: null,
  blocked: false,
  route: null,
});

export function RiskBadge({ level }: { level: string | null }) {
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
export const MARKDOWN_STYLE =
  "max-w-none text-[15px] leading-[1.7] text-slate-700 [&_h3]:mt-5 [&_h3]:mb-1.5 [&_h3]:text-[15px] [&_h3]:font-bold [&_h3]:text-slate-900 [&_p]:my-1.5 [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-indigo-200 [&_blockquote]:pl-3 [&_blockquote]:text-slate-500 [&_strong]:font-bold [&_strong]:text-slate-900 [&_em]:not-italic [&_em]:text-slate-500 [overflow-wrap:anywhere] [&_a]:font-medium [&_a]:text-indigo-700 [&_a]:underline [&_a]:underline-offset-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-slate-50 [&_pre]:p-3 [&_pre]:text-[13px] [&_table]:my-2 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1";

// 입력창 타이핑·스트리밍 때 페이지 전체가 다시 그려져도, 글이 같으면 다시 파싱하지 않는다
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className={MARKDOWN_STYLE}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]} unwrapDisallowed>{text}</ReactMarkdown>
    </div>
  );
});

export function CitationChips({ citations }: { citations: Citation[] }) {
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

export function AgentDetail({
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

export function Spinner({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block shrink-0 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600 motion-reduce:animate-none ${className}`}
    />
  );
}

export function AssistantBubble({
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
  // 결과가 오기 전까지는 진행 중이다. 단계 이벤트 사이가 길어도 멈춘 게 아니라는 걸 보여준다.
  const running = !result && !error && !!stage;

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
      <span aria-hidden className="relative mt-1 h-8 w-8 shrink-0">
        {/* 분석 중에는 아이콘 둘레에 링이 돈다 — 이벤트 사이가 길어도 멈춘 게 아니라는 신호 */}
        {running && (
          <span className="absolute -inset-1 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-500 border-r-indigo-500 motion-reduce:animate-none" />
        )}
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-600 text-[11px] font-extrabold text-white">
          AI
        </span>
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
            {running && (
              <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium text-slate-500">
                <Spinner className="h-4 w-4 border-[2.5px]" />
                {stage}
                {/* 배포본 규정 질의 응답 중앙값 9.9초 · p90 13초 (2026-09 실측) */}
                <span className="text-xs text-slate-500">보통 10초 안팎</span>
              </div>
            )}

            {route === "regulation" && !result && (
              <div className="mb-4 flex flex-wrap gap-1.5 text-xs font-medium">
                {[
                  { label: "규정 검토", done: !!reviewer, active: !reviewer },
                  { label: "감사 분석", done: !!auditor, active: !auditor },
                  { label: "종합 조정", done: false, active: !!reviewer && !!auditor },
                ].map((step) => (
                  <span
                    key={step.label}
                    className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 ring-1 ${
                      step.done
                        ? "bg-green-50 text-green-700 ring-green-200"
                        : step.active
                          ? "bg-indigo-50 text-indigo-700 ring-indigo-200"
                          : "bg-slate-50 text-slate-500 ring-slate-200"
                    }`}
                  >
                    {step.done && <Icon path={paths.check} className="h-3 w-3" />}
                    {!step.done && step.active && <Spinner className="h-3 w-3" />}
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

            {streamingText ? (
              <Markdown text={streamingText} />
            ) : (
              running &&
              route === "regulation" && (
                <div aria-hidden className="flex flex-col gap-2.5 py-1">
                  <span className="skeleton-line h-3.5 w-11/12" />
                  <span className="skeleton-line h-3.5 w-full" />
                  <span className="skeleton-line h-3.5 w-3/4" />
                </div>
              )
            )}

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
