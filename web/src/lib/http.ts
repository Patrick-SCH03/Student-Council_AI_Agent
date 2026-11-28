// 백엔드 호출 공통: 세션 쿠키를 싣고, 실패하면 서버가 준 안내(detail)나 화면별 기본 문구로 오류를 낸다.

import { API_BASE, errorDetail } from "./api";

export { errorDetail };

export async function request<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init });
  } catch {
    throw new Error("서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.");
  }
  if (!res.ok) throw new Error(await errorDetail(res, fallback));
  return res.json() as Promise<T>;
}

export const postJson = <T>(path: string, body: unknown, fallback: string) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, fallback);
