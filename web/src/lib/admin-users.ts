// 관리자 패널 '회원 관리' — 학교 계정 목록·계정별 업무 도구 사용 기록·세션 관리. 규정 질문은 익명이라 계정과 잇지 않는다.

import { adminFetch, errorDetail } from "./api";

export type Member = {
  id: number;
  email: string;
  name: string | null;
  role: "admin" | "member";
  created_at: string;
  last_login_at: string;
  blocked_at: string | null;
  active_sessions: number;
  uses_30d: number;
  cost_usd: number;
  last_used_at: string | null;
};
export type MemberCounts = { total: number; blocked: number; active_7d: number };
export type MemberDetail = {
  user: Member;
  by_route: { route: string; uses: number; errors: number; cost_usd: number; last_at: string }[];
  recent: { ts: string; route: string; status: string; elapsed: number; cost_usd: number | null }[];
  sessions: { created_at: string; expires_at: string; revoked_at: string | null; active: boolean }[];
  ledger: number;
  contributions: number;
};

/** 지표 경로 → 화면 이름 */
export const ROUTE_LABEL: Record<string, string> = {
  "review-extract": "문서 검토(파일 읽기)",
  "review-notes": "규정 메모",
  "review-plan": "기획 초안",
  "review-plan-suggest": "기획 AI 초안",
  "review-minutes": "회의록 정리",
  "review-law-ask": "법령 질문",
  "review-notice-draft": "공고문 → 공지",
};
export const routeLabel = (route: string) => ROUTE_LABEL[route] ?? route;

async function json<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) throw new Error(await errorDetail(res, fallback));
  return res.json() as Promise<T>;
}

export const fetchMembers = async (q = "") =>
  json<{ users: Member[]; counts: MemberCounts }>(await adminFetch(`/api/users?q=${encodeURIComponent(q)}`), "회원 목록을 불러오지 못했어요.");

export const fetchMember = async (id: number) => json<MemberDetail>(await adminFetch(`/api/users/${id}`), "회원 정보를 불러오지 못했어요.");

export const logoutMember = async (id: number) =>
  json<{ revoked: number }>(await adminFetch(`/api/users/${id}/logout`, { method: "POST" }), "로그아웃시키지 못했어요.");

export const blockMember = async (id: number, blocked: boolean) =>
  json<MemberDetail>(
    await adminFetch(`/api/users/${id}/block`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ blocked }) }),
    "처리하지 못했어요.",
  );

export const deleteMember = async (id: number) =>
  json<{ deleted: boolean }>(await adminFetch(`/api/users/${id}`, { method: "DELETE" }), "계정을 지우지 못했어요.");
