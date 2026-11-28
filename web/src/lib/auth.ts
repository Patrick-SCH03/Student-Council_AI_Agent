// 학교 계정 로그인 API. 세션은 백엔드가 httpOnly 쿠키로 관리한다 — 화면은 토큰을 직접 들지 않는다.

import { API_BASE } from "./api";
import { errorDetail } from "./http";

export type User = { email: string; name: string | null; role: "member" | "admin" | string };

const opts: RequestInit = { credentials: "include" };

/** 로그인 상태. 로그인하지 않았으면 null (오류가 아니다). */
export async function fetchMe(): Promise<User | null> {
  const res = await fetch(`${API_BASE}/api/auth/me`, opts);
  if (res.status === 401) return null;
  if (!res.ok) throw new Error("로그인 상태를 확인하지 못했어요.");
  return (await res.json()).user as User;
}

/** Google이 준 ID 토큰을 서버에 넘겨 세션을 연다 */
export async function loginWithGoogle(credential: string): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/google`, {
    ...opts,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential }),
  });
  if (!res.ok) throw new Error(await errorDetail(res, "로그인하지 못했어요. 잠시 후 다시 시도해 주세요."));
  return (await res.json()).user as User;
}

/** 서버가 세션을 폐기했을 때만 성공이다 — 실패를 숨기면 새로고침 때 같은 계정으로 다시 로그인돼 있다 */
export async function logout(): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/auth/logout`, { ...opts, method: "POST" });
  } catch {
    throw new Error("로그아웃하지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요.");
  }
  if (!res.ok) throw new Error(await errorDetail(res, "로그아웃하지 못했어요. 잠시 후 다시 시도해 주세요."));
}

/** 이름 첫 글자(없으면 이메일 첫 글자) — 계정 동그라미에 쓴다 */
export function initial(user: User): string {
  return (user.name || user.email).trim().charAt(0).toUpperCase();
}
