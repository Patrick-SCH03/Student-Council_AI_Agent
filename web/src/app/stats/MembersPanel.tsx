"use client";

// 운영 대시보드: 회원 관리 — 학교 계정 목록, 계정별 업무 도구 사용 기록(내용 없이 언제·무엇·비용), 세션 끊기·이용 제한·계정 삭제.
// 규정 질문은 익명이라 계정과 잇지 않는다.

import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import {
  type Member,
  type MemberCounts,
  type MemberDetail,
  blockMember,
  deleteMember,
  fetchMember,
  fetchMembers,
  logoutMember,
  routeLabel,
} from "@/lib/admin-users";
import { AuthError } from "@/lib/api";
import { usd } from "@/lib/format";

import { CARD_SHADOW } from "./parts";

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul" }) : "—";
const day = (iso: string) => new Date(iso).toLocaleDateString("ko-KR", { year: "2-digit", month: "numeric", day: "numeric", timeZone: "Asia/Seoul" });
const BTN = "rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50";

function Status({ m }: { m: Member }) {
  if (m.role === "admin") return <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-bold text-indigo-700">관리자</span>;
  if (m.blocked_at) return <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-bold text-rose-700">이용 제한</span>;
  return m.active_sessions ? (
    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-700">로그인 중</span>
  ) : (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-500">로그아웃</span>
  );
}

function Detail({ d, busy, onAction }: { d: MemberDetail; busy: boolean; onAction: (kind: "logout" | "block" | "unblock" | "delete") => void }) {
  const u = d.user;
  return (
    <div className="grid gap-4 bg-slate-50/70 px-5 py-4 text-[13px] lg:grid-cols-3">
      <div>
        <p className="text-xs font-bold text-slate-500">기능별 사용</p>
        {d.by_route.length ? (
          <ul className="mt-1.5 space-y-1">
            {d.by_route.map((r) => (
              <li key={r.route} className="flex justify-between gap-2">
                <span className="text-slate-700">{routeLabel(r.route)}</span>
                <span className="tabular-nums text-slate-500">
                  {r.uses}회{r.errors ? ` · 실패 ${r.errors}` : ""} · {usd(r.cost_usd)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1.5 text-slate-500">아직 업무 도구를 쓰지 않았어요.</p>
        )}
        <p className="mt-3 text-xs text-slate-500">
          문서 번호 대장 {d.ledger}건 · 개선용 자료 {d.contributions}건 · 가입 {day(u.created_at)}
        </p>
      </div>
      <div>
        <p className="text-xs font-bold text-slate-500">최근 활동 (내용은 저장하지 않아요)</p>
        <ul className="mt-1.5 max-h-48 space-y-1 overflow-y-auto pr-1">
          {d.recent.map((r, i) => (
            <li key={i} className="flex justify-between gap-2">
              <span className={r.status === "ok" ? "text-slate-700" : "text-rose-700"}>
                {routeLabel(r.route)}
                {r.status !== "ok" && " (실패)"}
              </span>
              <span className="shrink-0 tabular-nums text-slate-500">{when(r.ts)}</span>
            </li>
          ))}
          {!d.recent.length && <li className="text-slate-500">기록 없음</li>}
        </ul>
      </div>
      <div>
        <p className="text-xs font-bold text-slate-500">로그인 세션</p>
        <ul className="mt-1.5 space-y-1">
          {d.sessions.slice(0, 6).map((s, i) => (
            <li key={i} className="flex justify-between gap-2">
              <span className="tabular-nums text-slate-700">{when(s.created_at)} 로그인</span>
              <span className={s.active ? "font-semibold text-emerald-700" : "text-slate-400"}>{s.active ? "사용 중" : s.revoked_at ? "끊음" : "만료"}</span>
            </li>
          ))}
          {!d.sessions.length && <li className="text-slate-500">세션 없음</li>}
        </ul>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" disabled={busy || !u.active_sessions} onClick={() => onAction("logout")} className={`${BTN} border-slate-200 bg-white text-slate-700 hover:border-slate-300`}>
            로그아웃시키기
          </button>
          {(u.blocked_at || u.role !== "admin") &&
            (u.blocked_at ? (
              <button type="button" disabled={busy} onClick={() => onAction("unblock")} className={`${BTN} border-slate-200 bg-white text-slate-700 hover:border-slate-300`}>
                제한 풀기
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => onAction("block")} className={`${BTN} border-amber-200 bg-white text-amber-700 hover:bg-amber-50`}>
                이용 제한
              </button>
            ))}
          {u.role !== "admin" && (
            <button type="button" disabled={busy} onClick={() => onAction("delete")} className={`${BTN} border-rose-200 bg-white text-rose-700 hover:bg-rose-50`}>
              계정 삭제
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MembersPanel({ onAuthError }: { onAuthError: (e: unknown, fallback: string) => void }) {
  const [rows, setRows] = useState<Member[]>([]);
  const [counts, setCounts] = useState<MemberCounts | null>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [detail, setDetail] = useState<MemberDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const openRef = useRef<number | null>(null); // 늦게 온 응답이 지금 펼친 행이 아니면 버린다
  const searchSeq = useRef(0);

  const fail = useCallback(
    (e: unknown, fallback: string) => {
      if (e instanceof AuthError) onAuthError(e, "");
      else setMessage(e instanceof Error ? e.message : fallback);
    },
    [onAuthError],
  );

  const load = useCallback(
    (query: string) => {
      const seq = ++searchSeq.current;
      return fetchMembers(query).then(
        (r) => {
          if (seq !== searchSeq.current) return; // 더 나중 검색이 있으면 버린다
          setRows(r.users);
          setCounts(r.counts);
        },
        (e) => fail(e, "회원 목록을 불러오지 못했어요."),
      );
    },
    [fail],
  );

  useEffect(() => {
    const t = setTimeout(() => void load(q), q ? 300 : 0); // 검색은 입력이 멈추면
    return () => clearTimeout(t);
  }, [q, load]);

  const toggle = (id: number) => {
    if (busy) return;
    setMessage(null);
    const next = open === id ? null : id;
    openRef.current = next;
    setOpen(next);
    setDetail(null);
    if (next !== null)
      fetchMember(next).then(
        (d) => openRef.current === next && setDetail(d),
        (e) => fail(e, "회원 정보를 불러오지 못했어요."),
      );
  };

  const act = async (kind: "logout" | "block" | "unblock" | "delete") => {
    if (!detail) return;
    const u = detail.user;
    const ask = {
      logout: `${u.email} 계정의 로그인을 모두 끊을까요?`,
      block: `${u.email} 계정의 이용을 제한할까요? 지금 로그인도 끊기고, 풀기 전까지 다시 로그인할 수 없어요.`,
      unblock: `${u.email} 계정의 이용 제한을 풀까요?`,
      delete: `${u.email} 계정을 지울까요? 문서 번호 대장·개선용 자료도 함께 지워지고 되돌릴 수 없어요. 다음에 로그인하면 새 계정으로 만들어져요.`,
    }[kind];
    if (!confirm(ask)) return;
    setBusy(true);
    setMessage(null);
    try {
      if (kind === "logout") {
        const r = await logoutMember(u.id);
        setMessage(`세션 ${r.revoked}개를 끊었어요.`);
        setDetail(await fetchMember(u.id));
      } else if (kind === "delete") {
        await deleteMember(u.id);
        openRef.current = null;
        setOpen(null);
        setDetail(null);
        setMessage("계정을 지웠어요.");
      } else {
        setDetail(await blockMember(u.id, kind === "block"));
        setMessage(kind === "block" ? "이용을 제한했어요." : "이용 제한을 풀었어요.");
      }
      await load(q);
    } catch (e) {
      fail(e, "처리하지 못했어요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`overflow-x-auto rounded-2xl border border-slate-200 bg-white ${CARD_SHADOW}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
        <p className="text-sm font-bold text-slate-800">
          회원 관리
          {counts && (
            <span className="ml-2 text-xs font-medium text-slate-500">
              전체 {counts.total}명 · 최근 7일 로그인 {counts.active_7d}명{counts.blocked ? ` · 이용 제한 ${counts.blocked}명` : ""}
            </span>
          )}
        </p>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="이메일·이름 검색"
          aria-label="회원 검색"
          className="w-56 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
        />
      </div>
      {message && <p className="px-5 pt-2 text-xs font-medium text-slate-600">{message}</p>}
      <table className="mt-2 w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-[11px] font-bold uppercase tracking-wide text-slate-500">
            <th className="px-5 py-2">계정</th>
            <th className="px-2 py-2">상태</th>
            <th className="px-2 py-2">최근 로그인</th>
            <th className="px-2 py-2">최근 사용</th>
            <th className="px-2 py-2 text-right">30일 사용</th>
            <th className="px-5 py-2 text-right">누적 비용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <Fragment key={m.id}>
              <tr onClick={() => toggle(m.id)} className={`cursor-pointer border-b border-slate-50 transition hover:bg-slate-50 ${open === m.id ? "bg-slate-50" : ""}`}>
                <td className="px-5 py-2.5">
                  <p className="font-semibold text-slate-900">{m.name || "이름 없음"}</p>
                  <p className="text-xs text-slate-500">{m.email}</p>
                </td>
                <td className="px-2 py-2.5">
                  <Status m={m} />
                </td>
                <td className="px-2 py-2.5 tabular-nums text-slate-600">{when(m.last_login_at)}</td>
                <td className="px-2 py-2.5 tabular-nums text-slate-600">{when(m.last_used_at)}</td>
                <td className="px-2 py-2.5 text-right tabular-nums text-slate-700">{m.uses_30d}회</td>
                <td className="px-5 py-2.5 text-right tabular-nums text-slate-700">{usd(m.cost_usd)}</td>
              </tr>
              {open === m.id && (
                <tr>
                  <td colSpan={6} className="p-0">
                    {detail ? <Detail d={detail} busy={busy} onAction={act} /> : <p className="px-5 py-4 text-xs text-slate-500">불러오는 중...</p>}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6} className="px-5 py-6 text-center text-sm text-slate-500">
                {q ? "찾는 계정이 없어요." : "아직 로그인한 계정이 없어요."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
