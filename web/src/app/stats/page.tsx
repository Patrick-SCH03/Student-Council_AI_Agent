"use client";

// 운영 관측 대시보드 (숨김 URL: /stats — 네비게이션에 노출하지 않음)

import { Fragment, useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  type Limits,
  AuthError,
  adminFetch,
  clearAdminToken,
  getAdminToken,
  setAdminToken,
  updateLimits,
} from "@/lib/api";

const CARD_SHADOW =
  "shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.08),0px_4px_6px_-2px_rgba(16,24,40,0.03)]";

type RecentRow = {
  id: number;
  analysis_id: number | null;
  ts: string;
  route: string | null;
  risk_level: string | null;
  status: string;
  elapsed: number | null;
  tokens: number;
  query_preview: string;
  helpful: number | null;
};

type Feedback = {
  helpful: number;
  unhelpful: number;
  recent_unhelpful: {
    analysis_id: number;
    ts: string;
    query: string;
    risk_level: string | null;
  }[];
};

type Stats = {
  totals: {
    count: number;
    avg_elapsed: number;
    input_tokens: number;
    output_tokens: number;
    errors: number;
  };
  today: {
    count: number;
    avg_elapsed: number;
    input_tokens: number;
    output_tokens: number;
  };
  daily: { date: string; count: number; avg_elapsed: number; tokens: number }[];
  risk: Record<string, number>;
  routes: Record<string, number>;
  recent: RecentRow[];
  visits: { today_visitors: number; total_visitors: number; total_visits: number };
  daily_visits: { date: string; visitors: number }[];
  cost: {
    total_usd: number;
    today_usd: number;
    total_krw: number;
    today_krw: number;
    usd_krw: number;
  };
  limits: Limits;
  feedback: Feedback;
};

type Analysis = {
  id: number;
  query: string;
  risk_level: string | null;
  result: { final_markdown: string };
};

const RISK_STYLE: Record<string, { dot: string; chip: string }> = {
  높음: { dot: "bg-rose-500", chip: "bg-rose-50 text-rose-600 ring-rose-200" },
  보통: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-600 ring-amber-200" },
  낮음: { dot: "bg-green-500", chip: "bg-green-50 text-green-600 ring-green-200" },
};

function fmt(n: number): string {
  return n.toLocaleString("ko-KR");
}

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-4 ${CARD_SHADOW}`}>
      <p className="text-xs font-bold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1.5 text-[24px] font-extrabold tracking-tight text-slate-900">
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs font-medium text-slate-400">{sub}</p>}
    </div>
  );
}

function DailyBars({
  title,
  data,
  unit,
}: {
  title: string;
  data: { date: string; value: number; tooltip?: string }[];
  unit: string;
}) {
  const byDate = new Map(data.map((d) => [d.date, d]));
  const days: { date: string; value: number; tooltip?: string }[] = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const row = byDate.get(key);
    days.push({ date: key, value: row?.value ?? 0, tooltip: row?.tooltip });
  }
  const max = Math.max(...days.map((d) => d.value), 1);
  const maxIdx = days.reduce((mi, d, i) => (d.value > days[mi].value ? i : mi), 0);

  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
      <p className="text-sm font-bold text-slate-800">{title}</p>
      <div className="mt-4 flex h-28 items-end gap-[2px]">
        {days.map((d, i) => {
          const h = d.value === 0 ? 2 : Math.max((d.value / max) * 100, 8);
          return (
            <div
              key={d.date}
              className="group relative flex h-full flex-1 flex-col items-center justify-end"
              title={d.tooltip ?? `${d.date} · ${d.value}${unit}`}
            >
              {i === maxIdx && d.value > 0 && (
                <span className="mb-1 text-[10px] font-bold text-slate-500">{d.value}</span>
              )}
              <div
                className={`w-full max-w-[26px] rounded-t-[4px] transition ${
                  d.value === 0 ? "bg-slate-100" : "bg-indigo-600 group-hover:bg-indigo-700"
                }`}
                style={{ height: `${h}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] font-medium text-slate-400">
        <span>{days[0].date.slice(5)}</span>
        <span>{days[days.length - 1].date.slice(5)}</span>
      </div>
    </div>
  );
}

function TokenGate({
  message,
  onSubmit,
}: {
  message: string | null;
  onSubmit: (token: string) => void;
}) {
  const [value, setValue] = useState("");
  return (
    <div className="mx-auto mt-24 max-w-sm">
      <div className={`rounded-2xl border border-slate-200 bg-white p-6 ${CARD_SHADOW}`}>
        <h1 className="text-lg font-extrabold tracking-tight text-slate-900">
          운영 대시보드
        </h1>
        <p className="mt-1 text-sm font-medium text-slate-500">
          관리자 토큰을 입력하세요.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (value.trim()) onSubmit(value.trim());
          }}
          className="mt-4 flex flex-col gap-2"
        >
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="ADMIN_TOKEN"
            autoFocus
            className="rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm outline-none focus:border-indigo-400"
          />
          <button
            type="submit"
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-indigo-700"
          >
            확인
          </button>
        </form>
        {message && (
          <p className="mt-3 text-xs font-medium text-rose-600">{message}</p>
        )}
      </div>
    </div>
  );
}

function LimitSettings({
  limits,
  onSaved,
}: {
  limits: Limits;
  onSaved: () => void;
}) {
  const [total, setTotal] = useState(String(limits.daily_limit_total));
  const [perUser, setPerUser] = useState(String(limits.daily_limit_per_user));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const dirty =
    total !== String(limits.daily_limit_total) ||
    perUser !== String(limits.daily_limit_per_user);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await updateLimits({
        daily_limit_total: Number(total) || 0,
        daily_limit_per_user: Number(perUser) || 0,
      });
      setMessage("저장되었습니다.");
      onSaved();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "저장 실패");
    } finally {
      setSaving(false);
    }
  };

  const used = limits.used_today;
  const cap = limits.daily_limit_total;
  const pct = cap > 0 ? Math.min(Math.round((used / cap) * 100), 100) : 0;

  const field = (
    label: string,
    value: string,
    onChange: (v: string) => void,
  ) => (
    <div className="flex items-center gap-2">
      <span className="whitespace-nowrap text-sm font-medium text-slate-600">
        {label}
      </span>
      <div className="relative">
        <input
          type="number"
          min={0}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-28 rounded-lg border border-slate-300 py-1.5 pl-3 pr-10 text-right text-sm tabular-nums outline-none focus:border-indigo-400"
        />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-slate-400">
          건
        </span>
      </div>
    </div>
  );

  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-bold text-slate-800">일일 질의 한도</p>
        {cap > 0 ? (
          <p className="text-xs font-medium text-slate-500">
            오늘 <span className="font-bold text-slate-700">{fmt(used)}</span> /{" "}
            {fmt(cap)}건 사용 ({pct}%)
          </p>
        ) : (
          <p className="text-xs font-medium text-slate-400">
            전체 한도 없음 · 오늘 {fmt(used)}건 사용
          </p>
        )}
      </div>

      {cap > 0 && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full transition-all ${
              pct >= 90 ? "bg-rose-500" : pct >= 70 ? "bg-amber-500" : "bg-indigo-600"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3">
        {field("전체", total, setTotal)}
        {field("사용자당", perUser, setPerUser)}

        <span className="text-xs font-medium text-slate-400">0 = 무제한</span>

        <div className="ml-auto flex items-center gap-2.5">
          {message && (
            <span className="text-xs font-medium text-slate-500">{message}</span>
          )}
          <button
            type="button"
            onClick={save}
            disabled={!dirty || saving}
            className="rounded-full bg-indigo-600 px-5 py-2 text-xs font-bold text-white transition hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400"
          >
            {saving ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, Analysis | "loading" | "error">>({});

  const load = useCallback(async () => {
    try {
      const res = await adminFetch("/api/stats");
      if (!res.ok) throw new Error(`서버 오류 (${res.status})`);
      setStats(await res.json());
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

  // 마운트 시 1회 + 30초 주기로 지표를 갱신한다.
  // load()의 setState는 fetch 이후에 실행되지만, 정적 분석상 동기 호출로 잡혀 예외 처리한다.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 서버 데이터 폴링(비동기 갱신)
    load();
    const t = setInterval(load, 30_000);
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
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "metrics.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("CSV 내보내기에 실패했습니다.");
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
    return <p className="py-16 text-center text-sm font-medium text-rose-600">{error}</p>;
  }
  if (!stats) {
    return (
      <p className="py-16 text-center text-sm font-medium text-slate-400">불러오는 중...</p>
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
              clearAdminToken();
              setNeedsAuth(true);
              setStats(null);
            }}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-400 transition hover:border-rose-200 hover:text-rose-600"
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
          sub={stats.totals.errors ? `오류 ${stats.totals.errors}건` : "오류 0건"}
        />
        <StatTile
          label="방문자"
          value={`오늘 ${fmt(stats.visits.today_visitors)}명`}
          sub={`누적 ${fmt(stats.visits.total_visitors)}명 · 총 방문 ${fmt(stats.visits.total_visits)}회`}
        />
        <StatTile
          label="예상 API 비용"
          value={`₩${fmt(stats.cost.total_krw)}`}
          sub={`오늘 ₩${fmt(stats.cost.today_krw)} · $${stats.cost.total_usd.toFixed(2)}`}
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
            <p className="mt-4 text-sm font-medium text-slate-400">
              아직 평가가 없습니다.
            </p>
          ) : (
            <>
              <p className="mt-3 text-[26px] font-extrabold tracking-tight text-slate-900">
                {Math.round((stats.feedback.helpful / fbTotal) * 100)}%
                <span className="ml-1.5 text-sm font-medium text-slate-400">
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
            <span className="font-medium text-slate-400">
              — &lsquo;부족함&rsquo; 평가를 받은 질문
            </span>
          </p>
          {stats.feedback.recent_unhelpful.length === 0 ? (
            <p className="mt-4 text-sm font-medium text-slate-400">
              부족하다는 평가가 아직 없습니다.
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
                  <span className="shrink-0 text-xs font-medium text-slate-400">
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
        <LimitSettings limits={stats.limits} onSaved={load} />
      </div>

      <div className={`mt-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white ${CARD_SHADOW}`}>
        <p className="px-5 pt-4 text-sm font-bold text-slate-800">
          최근 질의 20건 <span className="font-medium text-slate-400">— 클릭하면 전체 내용을 볼 수 있습니다</span>
        </p>
        <table className="mt-2 w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-400">
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
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs font-medium text-slate-400">
                    {new Date(r.ts).toLocaleString("ko-KR", {
                      month: "numeric",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="max-w-[280px] truncate px-2 py-2.5 font-medium text-slate-700">
                    {r.query_preview}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5">
                    {r.status !== "ok" ? (
                      <span className="text-xs font-bold text-rose-600">오류</span>
                    ) : r.risk_level ? (
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold ring-1 ${
                          RISK_STYLE[r.risk_level]?.chip ?? "bg-slate-50 text-slate-500 ring-slate-200"
                        }`}
                      >
                        {r.risk_level}
                      </span>
                    ) : (
                      <span className="text-xs font-medium text-slate-400">—</span>
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
                      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">
                        전체 질문
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-800">
                        {r.query_preview}
                      </p>
                      {r.analysis_id ? (
                        <div className="mt-3">
                          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">
                            최종 답변
                          </p>
                          {answers[r.analysis_id] === "loading" && (
                            <p className="mt-1 text-sm text-slate-400">불러오는 중...</p>
                          )}
                          {answers[r.analysis_id] === "error" && (
                            <p className="mt-1 text-sm text-rose-600">
                              답변을 불러오지 못했습니다.
                            </p>
                          )}
                          {typeof answers[r.analysis_id] === "object" && (
                            <div className="mt-1 max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-700 [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:font-bold [&_h3]:text-slate-900 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {(answers[r.analysis_id] as Analysis).result.final_markdown}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="mt-2 text-xs text-slate-400">
                          저장된 답변이 없는 기록입니다 (범위 밖 질문 또는 오류).
                        </p>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {stats.recent.length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-8 text-center text-sm text-slate-400">
                  아직 기록이 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
