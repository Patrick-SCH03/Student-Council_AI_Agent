// 계정별로 기억하는 작성자 정보 — 기구·대수는 거의 바뀌지 않으니 다음에 기획 도우미를 열 때 미리 채운다.
// 이 브라우저에만 둔다(서버에 저장하지 않음 — 내 작업함과 같은 원칙). 저장소가 막혀 있으면 조용히 기억하지 않는다.

import { type Store, browserStore } from "./storage.ts";

export type Profile = { org: string; term: string };

const keyFor = (owner: string) => `profile:${owner}`;

export function loadProfile(owner: string, store: Store | null = browserStore()): Profile | null {
  if (!store) return null;
  try {
    const p = JSON.parse(store.getItem(keyFor(owner)) ?? "null") as Partial<Profile> | null;
    if (!p) return null;
    return { org: typeof p.org === "string" ? p.org : "", term: typeof p.term === "string" ? p.term : "" };
  } catch {
    return null;
  }
}

/** 빈 값은 덮어쓰지 않는다 — 이번에 대수를 안 적었다고 지난번 값을 지우지 않게 */
export function rememberProfile(owner: string, next: Partial<Profile>, store: Store | null = browserStore()): void {
  if (!store) return;
  const prev = loadProfile(owner, store) ?? { org: "", term: "" };
  const merged: Profile = { org: next.org?.trim() || prev.org, term: next.term?.trim() || prev.term };
  if (!merged.org && !merged.term) return;
  try {
    store.setItem(keyFor(owner), JSON.stringify(merged));
  } catch {
    // 용량 초과 등은 무시
  }
}
