"use client";

// 운영 관측 대시보드 (숨김 URL: /stats — 네비게이션에 노출하지 않음)

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  AuthError,
  adminFetch,
  clearAdminToken,
  clearAnswerCache,
  getAdminToken,
  setAdminToken,
} from "@/lib/api";
import { fmt, usd } from "@/lib/format";

import {
  type Analysis,
  type RecentRow,
  type Stats,
  CARD_SHADOW,
  DailyBars,
  LimitSettings,
  RISK_STYLE,
  StageBreakdown,
  StatTile,
  TokenGate,
  fallbackTitle,
} from "./parts";

export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  // 로그아웃 뒤 늦게 도착한 응답이 화면을 되살리지 않도록 세션을 구분한다
  const sessionRef = useRef(0);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, Analysis | "loading" | "error">>({});

  const load = useCallback(async () => {
    const session = sessionRef.current;
    try {
      const res = await adminFetch("/api/stats");
      if (!res.ok) throw new Error(`서버 오류 (${res.status})`);
      const data = await res.json();
      if (session !== sessionRef.current) return; // 그사이 로그아웃됨
      setStats(data);
      setError(null);
      setNeedsAuth(false);
    } catch (e) {
      if (e instanceof AuthError) {
        setNeedsAuth(true);
        setAuthError(getAdminToken() ? e.message : null);
        return;
      }
      setError(e instanceof Error ? e.message : "불러오기 실패");
    }
  }, []);

  // 관리자 조작(CSV·캐시)의 실패 처리. 인증 실패는 지표 조회와 똑같이 로그인 화면으로 보낸다.
  const handleAdminError = (e: unknown, fallback: string) => {
    if (e instanceof AuthError) {
      setNeedsAuth(true);
      setAuthError(e.message);
      return;
    }
    setError(e instanceof Error ? e.message : fallback);
  };

  // 마운트 시 1회 + 30초 주기로 지표를 갱신한다.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 서버 데이터 폴링(비동기 갱신)
    load();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const toggleRow = (row: RecentRow) => {
    const next = expandedId === row.id ? null : row.id;
    setExpandedId(next);
    if (next !== null && row.analysis_id && !answers[row.analysis_id]) {
      const aid = row.analysis_id;
      setAnswers((prev) => ({ ...prev, [aid]: "loading" }));
      adminFetch(`/api/analyses/${aid}`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data: Analysis) => setAnswers((prev) => ({ ...prev, [aid]: data })))
        .catch(() => setAnswers((prev) => ({ ...prev, [aid]: "error" })));
    }
  };

  const downloadCsv = async () => {
    try {
      const res = await adminFetch("/api/stats/export");
      // 오류 응답 본문이 metrics.csv로 저장되면 정상 내보내기로 착각한다
      if (!res.ok || !(res.headers.get("content-type") ?? "").includes("text/csv")) {
        throw new Error(`CSV를 내보내지 못했어요 (HTTP ${res.status}).`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "metrics.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      handleAdminError(e, "CSV를 내보내지 못했어요.");
    }
  };

  if (needsAuth) {
    return (
      <TokenGate
        message={authError}
        onSubmit={(token) => {
          setAdminToken(token);
          setAuthError(null);
          load();
        }}
      />
    );
  }
  if (error) {
    return <p className="py-16 text-center text-sm font-medium text-rose-700">{error}</p>;
  }
  if (!stats) {
    return (
      <p className="py-16 text-center text-sm font-medium text-slate-500">불러오는 중...</p>
    );
  }

  const totalTokens = stats.totals.input_tokens + stats.totals.output_tokens;
  const todayTokens = stats.today.input_tokens + stats.today.output_tokens;
  const riskTotal = Object.values(stats.risk).reduce((a, b) => a + b, 0);
  const fbTotal = stats.feedback.helpful + stats.feedback.unhelpful;

  return (
    <div className="py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">
            운영 대시보드
          </h1>
          <p className="mt-1 text-sm font-medium text-slate-500">
            30초마다 자동 갱신 · 관리용 페이지
            {stats.agent && ` · 분석 모델 ${stats.agent.model}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={downloadCsv}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-500 transition hover:border-indigo-300 hover:text-indigo-600"
          >
            지표 CSV 내보내기
          </button>
          <button
            type="button"
            onClick={() => {
              sessionRef.current += 1;
              clearAdminToken();
              setNeedsAuth(true);
              setStats(null);
            }}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-500 transition hover:border-rose-200 hover:text-rose-700"
          >
            로그아웃
          </button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <StatTile
          label="오늘 질의"
          value={`${fmt(stats.today.count)}건`}
          sub={stats.today.count ? `평균 ${stats.today.avg_elapsed.toFixed(1)}초` : undefined}
        />
        <StatTile
          label="누적 질의"
          value={`${fmt(stats.totals.count)}건`}
          sub={[
            stats.totals.errors ? `오류 ${stats.totals.errors}건` : "오류 0건",
            // 검색·분류를 낮춘 경로로 처리한 건수 — 늘면 임베딩·Claude 쪽 장애를 의심한다
            stats.totals.fallbacks ? `폴백 ${stats.totals.fallbacks}건` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
        <StatTile
          label="방문자"
          value={`오늘 ${fmt(stats.visits.today_visitors)}명`}
          sub={`누적 ${fmt(stats.visits.total_visitors)}명 · 총 방문 ${fmt(stats.visits.total_visits)}회`}
        />
        <StatTile
          label="예상 API 비용 (USD)"
          value={usd(stats.cost.total_usd)}
          sub={[
            `오늘 ${usd(stats.cost.today_usd)}`,
            // 요청별 비용 기록 이전 행은 모델 구분 없이 토큰 합으로 추정한 값이다
            stats.cost.estimated_usd ? `토큰 합 추정분 ${usd(stats.cost.estimated_usd)} 포함` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        />
        <StatTile
          label="토큰 사용량"
          value={fmt(totalTokens)}
          sub={`오늘 ${fmt(todayTokens)}`}
        />
        <StatTile
          label="평균 응답 시간"
          value={`${stats.totals.avg_elapsed.toFixed(1)}초`}
        />
      </div>

      {stats.stages && stats.stages.samples > 0 && (
        <div className="mt-4">
          <StageBreakdown stages={stats.stages} />
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4 lg:col-span-2">
          <DailyBars
            title="일별 질의 수 (최근 14일)"
            unit="건"
            data={stats.daily.map((d) => ({
              date: d.date,
              value: d.count,
              tooltip: `${d.date} · ${d.count}건 · 평균 ${d.avg_elapsed.toFixed(1)}초`,
            }))}
          />
          <DailyBars
            title="일별 방문자 수 (최근 14일)"
            unit="명"
            data={stats.daily_visits.map((d) => ({ date: d.date, value: d.visitors }))}
          />
        </div>

        <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
          <p className="text-sm font-bold text-slate-800">위험도 분포</p>
          <div className="mt-4 flex flex-col gap-2.5">
            {["높음", "보통", "낮음"].map((level) => {
              const n = stats.risk[level] ?? 0;
              const pct = riskTotal ? Math.round((n / riskTotal) * 100) : 0;
              const style = RISK_STYLE[level];
              return (
                <div key={level} className="flex items-center gap-2.5">
                  <span
                    className={`inline-flex w-14 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-bold ring-1 ${style.chip}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
                    {level}
                  </span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={`h-full rounded-full ${style.dot}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="w-16 text-right text-xs font-medium text-slate-500">
                    {fmt(n)}건 ({pct}%)
                  </span>
                </div>
              );
            })}
          </div>

          <p className="mt-6 text-sm font-bold text-slate-800">질문 유형</p>
          <div className="mt-3 flex flex-col gap-1.5 text-sm">
            <div className="flex justify-between">
              <span className="font-medium text-slate-500">규정 분석</span>
              <span className="font-bold text-slate-800">
                {fmt(stats.routes["regulation"] ?? 0)}건
              </span>
            </div>
            <div className="flex justify-between">
              <span className="font-medium text-slate-500">범위 밖 질문</span>
              <span className="font-bold text-slate-800">
                {fmt(stats.routes["general"] ?? 0)}건
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
          <p className="text-sm font-bold text-slate-800">답변 만족도</p>
          {fbTotal === 0 ? (
            <p className="mt-4 text-sm font-medium text-slate-500">
              아직 평가가 없어요.
            </p>
          ) : (
            <>
              <p className="mt-3 text-[26px] font-extrabold tracking-tight text-slate-900">
                {Math.round((stats.feedback.helpful / fbTotal) * 100)}%
                <span className="ml-1.5 text-sm font-medium text-slate-500">
                  도움됨
                </span>
              </p>
              <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="bg-green-500"
                  style={{ width: `${(stats.feedback.helpful / fbTotal) * 100}%` }}
                />
                <div
                  className="bg-rose-400"
                  style={{ width: `${(stats.feedback.unhelpful / fbTotal) * 100}%` }}
                />
              </div>
              <p className="mt-2 text-xs font-medium text-slate-500">
                도움됨 {fmt(stats.feedback.helpful)}건 · 부족함{" "}
                {fmt(stats.feedback.unhelpful)}건
              </p>
            </>
          )}
        </div>

        <div
          className={`rounded-2xl border border-slate-200 bg-white p-5 lg:col-span-2 ${CARD_SHADOW}`}
        >
          <p className="text-sm font-bold text-slate-800">
            개선이 필요한 답변{" "}
            <span className="font-medium text-slate-500">
              — &lsquo;부족함&rsquo; 평가를 받은 질문
            </span>
          </p>
          {stats.feedback.recent_unhelpful.length === 0 ? (
            <p className="mt-4 text-sm font-medium text-slate-500">
              부족하다는 평가가 아직 없어요.
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {stats.feedback.recent_unhelpful.map((f) => (
                <li
                  key={f.analysis_id}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="min-w-0 truncate text-sm font-medium text-slate-700">
                    {f.query}
                  </span>
                  <span className="shrink-0 text-xs font-medium text-slate-500">
                    {new Date(f.ts).toLocaleDateString("ko-KR", {
                      month: "numeric",
                      day: "numeric",
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="mt-4">
        <LimitSettings
          limits={stats.limits}
          cache={stats.cache}
          onSaved={load}
          onClearCache={async () => {
            if (!confirm("저장된 답변 캐시를 모두 비울까요?")) return;
            try {
              await clearAnswerCache();
              load();
            } catch (e) {
              handleAdminError(e, "캐시를 비우지 못했어요.");
            }
          }}
        />
      </div>

      <div className={`mt-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white ${CARD_SHADOW}`}>
        <p className="px-5 pt-4 text-sm font-bold text-slate-800">
          최근 질의 20건 <span className="font-medium text-slate-500">— 누르면 전체 내용을 볼 수 있어요</span>
        </p>
        <table className="mt-2 w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-500">
              <th className="px-5 py-2">시각</th>
              <th className="px-2 py-2">질문</th>
              <th className="px-2 py-2">위험도</th>
              <th className="px-2 py-2">응답</th>
              <th className="px-5 py-2 text-right">토큰</th>
            </tr>
          </thead>
          <tbody>
            {stats.recent.map((r) => (
              <Fragment key={r.id}>
                <tr
                  onClick={() => toggleRow(r)}
                  className={`cursor-pointer border-b border-slate-50 transition last:border-0 hover:bg-slate-50/60 ${
                    expandedId === r.id ? "bg-indigo-50/40" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs font-medium text-slate-500">
                    {new Date(r.ts).toLocaleString("ko-KR", {
                      month: "numeric",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="max-w-[280px] px-2 py-2.5 font-medium text-slate-700">
                    {/* 행 클릭은 마우스용이라, 키보드로 펼칠 수 있게 버튼을 둔다 */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleRow(r);
                      }}
                      aria-expanded={expandedId === r.id}
                      className="block w-full truncate text-left hover:text-indigo-700"
                    >
                      {r.query_preview}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5">
                    {/* 'cached'는 정상 응답이므로 오류로 표시하지 않는다 */}
                    {r.status === "error" ? (
                      <span
                        className="cursor-help text-xs font-bold text-rose-700"
                        title={r.error ?? "사유 미기록"}
                      >
                        오류
                      </span>
                    ) : r.status === "cached" ? (
                      <span className="text-xs font-medium text-slate-500">캐시</span>
                    ) : r.status === "cancelled" ? (
                      <span className="text-xs font-medium text-slate-500" title="사용자가 응답 도중 연결을 끊었어요">
                        중단
                      </span>
                    ) : r.risk_level ? (
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ${
                          RISK_STYLE[r.risk_level]?.chip ?? "bg-slate-50 text-slate-500 ring-slate-200"
                        }`}
                      >
                        {r.risk_level}
                      </span>
                    ) : (
                      <span className="text-xs font-medium text-slate-500">—</span>
                    )}
                    {r.fallback && (
                      <span
                        className="ml-1.5 cursor-help text-xs font-bold text-amber-700"
                        title={fallbackTitle(r.fallback)}
                      >
                        폴백
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5 text-xs font-medium text-slate-500">
                    {r.elapsed != null ? `${r.elapsed.toFixed(1)}초` : "—"}
                  </td>
                  <td className="whitespace-nowrap px-5 py-2.5 text-right text-xs font-medium text-slate-500">
                    {r.helpful !== null && (
                      <span
                        className={`mr-2 ${r.helpful ? "text-green-600" : "text-rose-500"}`}
                        title={r.helpful ? "도움됨" : "부족함"}
                      >
                        {r.helpful ? "좋음" : "부족"}
                      </span>
                    )}
                    {fmt(r.tokens)}
                  </td>
                </tr>
                {expandedId === r.id && (
                  <tr className="border-b border-slate-100">
                    <td colSpan={5} className="bg-slate-50/60 px-5 py-4">
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                        전체 질문
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-800">
                        {r.query_preview}
                      </p>
                      {r.analysis_id ? (
                        <div className="mt-3">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                            최종 답변
                          </p>
                          {answers[r.analysis_id] === "loading" && (
                            <p className="mt-1 text-sm text-slate-500">불러오는 중...</p>
                          )}
                          {answers[r.analysis_id] === "error" && (
                            <p className="mt-1 text-sm text-rose-700">
                              답변을 불러오지 못했어요.
                            </p>
                          )}
                          {typeof answers[r.analysis_id] === "object" && (
                            <div className="mt-1 max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-700 [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:font-bold [&_h3]:text-slate-900 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&_em]:not-italic [&_em]:text-slate-500">
                              <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]} unwrapDisallowed>
                                {(answers[r.analysis_id] as Analysis).result.final_markdown}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="mt-2 text-xs text-slate-500">
                          저장된 답변이 없는 기록이에요 (범위 밖 질문 또는 오류).
                        </p>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {stats.recent.length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-8 text-center text-sm text-slate-500">
                  아직 기록이 없어요.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
