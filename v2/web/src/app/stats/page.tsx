"use client";

// 운영 관측 대시보드 (숨김 URL: /stats — 네비게이션에 노출하지 않음)

import { useCallback, useEffect, useState } from "react";

import { API_BASE } from "@/lib/api";

const CARD_SHADOW =
  "shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.08),0px_4px_6px_-2px_rgba(16,24,40,0.03)]";

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
  recent: {
    ts: string;
    route: string | null;
    risk_level: string | null;
    status: string;
    elapsed: number | null;
    tokens: number;
    query_preview: string;
  }[];
  cost: {
    total_usd: number;
    today_usd: number;
    total_krw: number;
    today_krw: number;
    usd_krw: number;
  };
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
      <p className="mt-1.5 text-[26px] font-extrabold tracking-tight text-slate-900">
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs font-medium text-slate-400">{sub}</p>}
    </div>
  );
}

function DailyBars({ daily }: { daily: Stats["daily"] }) {
  // 최근 14일을 빈 날짜 포함해 채운다
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const days: { date: string; count: number; avg: number }[] = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const row = byDate.get(key);
    days.push({ date: key, count: row?.count ?? 0, avg: row?.avg_elapsed ?? 0 });
  }
  const max = Math.max(...days.map((d) => d.count), 1);
  const maxIdx = days.reduce((mi, d, i) => (d.count > days[mi].count ? i : mi), 0);

  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
      <p className="text-sm font-bold text-slate-800">일별 질의 수 (최근 14일)</p>
      <div className="mt-4 flex h-32 items-end gap-[2px]">
        {days.map((d, i) => {
          const h = d.count === 0 ? 2 : Math.max((d.count / max) * 100, 8);
          return (
            <div
              key={d.date}
              className="group relative flex h-full flex-1 flex-col items-center justify-end"
              title={`${d.date} · ${d.count}건${d.count ? ` · 평균 ${d.avg.toFixed(1)}초` : ""}`}
            >
              {i === maxIdx && d.count > 0 && (
                <span className="mb-1 text-[10px] font-bold text-slate-500">{d.count}</span>
              )}
              <div
                className={`w-full max-w-[26px] rounded-t-[4px] transition ${
                  d.count === 0 ? "bg-slate-100" : "bg-indigo-600 group-hover:bg-indigo-700"
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

export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/stats`);
      if (!res.ok) throw new Error(`서버 오류 (${res.status})`);
      setStats(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "불러오기 실패");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

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

  return (
    <div className="py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">
            운영 대시보드
          </h1>
          <p className="mt-1 text-sm font-medium text-slate-500">
            30초마다 자동 갱신 · 관리용 페이지
          </p>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
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
          label="예상 API 비용"
          value={`₩${fmt(stats.cost.total_krw)}`}
          sub={`오늘 ₩${fmt(stats.cost.today_krw)} · $${stats.cost.total_usd.toFixed(2)}`}
        />
        <StatTile
          label="토큰 사용량"
          value={fmt(totalTokens)}
          sub={`오늘 ${fmt(todayTokens)} · 평균 응답 ${stats.totals.avg_elapsed.toFixed(1)}초`}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <DailyBars daily={stats.daily} />
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

      <div className={`mt-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white ${CARD_SHADOW}`}>
        <p className="px-5 pt-4 text-sm font-bold text-slate-800">최근 질의 20건</p>
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
            {stats.recent.map((r, i) => (
              <tr key={i} className="border-b border-slate-50 last:border-0">
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
                  {fmt(r.tokens)}
                </td>
              </tr>
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
