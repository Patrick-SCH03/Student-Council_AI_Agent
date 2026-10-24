"use client";

// 운영 대시보드의 화면 조각·타입 (page.tsx에서 옮김 — 동작 동일)

import { useState } from "react";

import { type Limits, updateLimits } from "@/lib/api";
import { CARD_SHADOW } from "@/lib/ui";

export { CARD_SHADOW };
import { fmt } from "@/lib/format";
import { LIMIT_MAX, parseLimit } from "@/lib/limits";


export type RecentRow = {
  id: number;
  analysis_id: number | null;
  ts: string;
  route: string | null;
  risk_level: string | null;
  status: string;
  elapsed: number | null;
  tokens: number;
  query_preview: string;
  error: string | null;
  // 낮춘 경로로 이어간 단계 (쉼표 구분)
  fallback: string | null;
  helpful: number | null;
};

export type Feedback = {
  helpful: number;
  unhelpful: number;
  recent_unhelpful: {
    analysis_id: number;
    ts: string;
    query: string;
    risk_level: string | null;
  }[];
};

export type Stats = {
  totals: {
    count: number;
    avg_elapsed: number;
    input_tokens: number;
    output_tokens: number;
    errors: number;
    fallbacks: number;
  };
  today: {
    count: number;
    avg_elapsed: number;
    input_tokens: number;
    output_tokens: number;
    fallbacks: number;
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
    // total_usd 중 모델별 기록 없이 토큰 합으로 추정한 몫 (요청별 비용 기록 이전)
    estimated_usd: number;
  };
  limits: Limits;
  feedback: Feedback;
  cache: { entries: number; hits: number };
  // 최근 완료된 규정 질의의 단계별 중앙값 (초)
  stages?: Partial<Record<StageKey, number>> & { samples: number };
  // 규정 검토·감사 분석·종합 조정을 돌리는 모델
  agent?: { model: string; embedding_model: string };
};

export const FALLBACK_STAGE_NOTES: Record<string, string> = {
  retrieve: "임베딩 실패로 키워드 검색만 사용",
  router_failed: "질문 분류 실패로 규정 질의로 처리",
};

export function fallbackTitle(fallback: string): string {
  // 목록에 없는 값은 이전 버전의 기록이다 (분석 단계가 다른 모델로 대체 처리됨)
  return fallback
    .split(",")
    .map((s) => FALLBACK_STAGE_NOTES[s] ?? `이전 버전 대체 처리: ${s}`)
    .join(" · ");
}

export type StageKey =
  | "router"
  | "retrieve"
  | "reviewer"
  | "auditor"
  | "coordinator_ttft"
  | "coordinator";

export const STAGE_LABELS: { key: StageKey; label: string }[] = [
  { key: "router", label: "질문 분류" },
  { key: "retrieve", label: "검색" },
  { key: "reviewer", label: "규정 검토" },
  { key: "auditor", label: "감사 분석" },
  { key: "coordinator_ttft", label: "종합 첫 글자" },
  { key: "coordinator", label: "종합 완료" },
];

/** 응답이 느려졌을 때 어느 단계인지 가르는 줄. 표본이 없으면 그리지 않는다. */
export function StageBreakdown({ stages }: { stages: NonNullable<Stats["stages"]> }) {
  if (!stages.samples) return null;
  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
      <p className="text-sm font-bold text-slate-800">
        단계별 소요 시간
        <span className="ml-2 text-xs font-medium text-slate-500">
          최근 규정 질의 {fmt(stages.samples)}건의 중앙값 · 규정 검토와 감사 분석은 동시에 실행
        </span>
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {STAGE_LABELS.map(({ key, label }) =>
          stages[key] === undefined ? null : (
            <div key={key}>
              <dt className="text-xs font-medium text-slate-500">{label}</dt>
              <dd className="text-lg font-bold tabular-nums text-slate-800">
                {stages[key]!.toFixed(1)}초
              </dd>
            </div>
          ),
        )}
      </dl>
    </div>
  );
}

export type Analysis = {
  id: number;
  query: string;
  risk_level: string | null;
  result: { final_markdown: string };
};

export const RISK_STYLE: Record<string, { dot: string; chip: string }> = {
  높음: { dot: "bg-rose-500", chip: "bg-rose-50 text-rose-700 ring-rose-200" },
  보통: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-600 ring-amber-200" },
  낮음: { dot: "bg-green-500", chip: "bg-green-50 text-green-600 ring-green-200" },
};

export function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-4 ${CARD_SHADOW}`}>
      <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1.5 text-[24px] font-extrabold tracking-tight text-slate-900">
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs font-medium text-slate-500">{sub}</p>}
    </div>
  );
}

export function DailyBars({
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
      <div className="mt-1.5 flex justify-between text-[10px] font-medium text-slate-500">
        <span>{days[0].date.slice(5)}</span>
        <span>{days[days.length - 1].date.slice(5)}</span>
      </div>
    </div>
  );
}

export function TokenGate({
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
            aria-label="관리자 토큰"
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
          <p className="mt-3 text-xs font-medium text-rose-700">{message}</p>
        )}
      </div>
    </div>
  );
}

export function LimitSettings({
  limits,
  cache,
  onSaved,
  onClearCache,
}: {
  limits: Limits;
  cache: { entries: number; hits: number };
  onSaved: () => void;
  onClearCache: () => void;
}) {
  const [total, setTotal] = useState(String(limits.daily_limit_total));
  const [perUser, setPerUser] = useState(String(limits.daily_limit_per_user));
  const [perIp, setPerIp] = useState(String(limits.daily_limit_per_ip));
  const [ttl, setTtl] = useState(String(limits.cache_ttl_hours));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const dirty =
    total !== String(limits.daily_limit_total) ||
    perUser !== String(limits.daily_limit_per_user) ||
    perIp !== String(limits.daily_limit_per_ip) ||
    ttl !== String(limits.cache_ttl_hours);

  const parsed = {
    daily_limit_total: parseLimit(total, LIMIT_MAX.daily_limit_total),
    daily_limit_per_user: parseLimit(perUser, LIMIT_MAX.daily_limit_per_user),
    daily_limit_per_ip: parseLimit(perIp, LIMIT_MAX.daily_limit_per_ip),
    cache_ttl_hours: parseLimit(ttl, LIMIT_MAX.cache_ttl_hours),
  };
  const invalid = Object.values(parsed).some((v) => v === null);

  const save = async () => {
    const { daily_limit_total, daily_limit_per_user, daily_limit_per_ip, cache_ttl_hours } =
      parsed;
    if (
      daily_limit_total === null ||
      daily_limit_per_user === null ||
      daily_limit_per_ip === null ||
      cache_ttl_hours === null
    ) {
      setMessage("빈 칸이나 올바르지 않은 값이 있어요. 0 이상의 정수를 넣어 주세요.");
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await updateLimits({
        daily_limit_total,
        daily_limit_per_user,
        daily_limit_per_ip,
        cache_ttl_hours,
      });
      setMessage("저장했어요.");
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
    max: number,
    unit = "건",
  ) => (
    // label로 감싸 입력칸에 이름을 연결한다 (화면낭독기가 '숫자 입력'만 읽지 않도록)
    <label className="flex items-center gap-2">
      <span className="whitespace-nowrap text-sm font-medium text-slate-600">
        {label}
      </span>
      <div className="relative">
        <input
          type="number"
          min={0}
          max={max}
          step={1}
          value={value}
          aria-invalid={parseLimit(value, max) === null}
          onChange={(e) => onChange(e.target.value)}
          className="w-28 rounded-lg border border-slate-300 py-1.5 pl-3 pr-10 text-right text-sm tabular-nums outline-none focus:border-indigo-400 aria-[invalid=true]:border-rose-500"
        />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-slate-500">
          {unit}
        </span>
      </div>
    </label>
  );

  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-bold text-slate-800">
          사용량 설정
          <span className="ml-2 text-xs font-medium text-slate-500">
            캐시 {fmt(cache.entries)}건 저장 · {fmt(cache.hits)}회 재사용
          </span>
        </p>
        {cap > 0 ? (
          <p className="text-xs font-medium text-slate-500">
            오늘 <span className="font-bold text-slate-700">{fmt(used)}</span> /{" "}
            {fmt(cap)}건 사용 ({pct}%)
          </p>
        ) : (
          <p className="text-xs font-medium text-slate-500">
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
        {field("전체", total, setTotal, LIMIT_MAX.daily_limit_total)}
        {field("사용자당", perUser, setPerUser, LIMIT_MAX.daily_limit_per_user)}
        {field("IP당", perIp, setPerIp, LIMIT_MAX.daily_limit_per_ip)}
        {field("답변 재사용", ttl, setTtl, LIMIT_MAX.cache_ttl_hours, "시간")}

        <span className="text-xs font-medium text-slate-500">0 = 사용 안 함</span>

        <div className="ml-auto flex items-center gap-2.5">
          {message && (
            <span className="text-xs font-medium text-slate-500">{message}</span>
          )}
          <button
            type="button"
            onClick={onClearCache}
            className="rounded-full border border-slate-200 px-4 py-2 text-xs font-medium text-slate-500 transition hover:border-rose-200 hover:text-rose-700"
          >
            캐시 비우기
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!dirty || invalid || saving}
            className="rounded-full bg-indigo-600 px-5 py-2 text-xs font-bold text-white transition hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-500"
          >
            {saving ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
