// 내 작업함: 기획 초안·검토 결과·회의록을 이 브라우저에 계정별로 남긴다 (서버에는 저장하지 않는다).
// 사용자가 '작업함에 저장'을 누른 것만, 30일·50건까지. 저장소가 막혀 있으면(사생활 모드 등) 조용히 빈 목록으로 동작한다.

import { type Store, browserStore } from "./storage.ts";

export type WorkKind = "plan" | "review" | "minutes";
export const KIND_LABEL: Record<WorkKind, string> = { plan: "기획 초안", review: "문서 검토", minutes: "회의록" };

export type WorkItem = { id: string; kind: WorkKind; title: string; text: string; savedAt: string };

export const KEEP_DAYS = 30;
export const MAX_ITEMS = 50;
const DAY = 24 * 60 * 60 * 1000;

const keyFor = (owner: string) => `workspace:${owner}`;

/** 최신순 목록. 만료(30일)를 지난 것은 읽을 때 저장소에서도 지운다 — 화면에서 안 보이는 원문이 남지 않게 */
export function listWork(owner: string, now = Date.now(), store: Store | null = browserStore()): WorkItem[] {
  if (!store) return [];
  let items: WorkItem[];
  try {
    items = JSON.parse(store.getItem(keyFor(owner)) ?? "[]") as WorkItem[];
  } catch {
    items = [];
  }
  const live = items.filter((i) => now - Date.parse(i.savedAt) < KEEP_DAYS * DAY).sort((a, b) => b.savedAt.localeCompare(a.savedAt));
  if (live.length !== items.length) write(owner, live, store);
  return live;
}

function write(owner: string, items: WorkItem[], store: Store | null): boolean {
  if (!store) return false;
  try {
    store.setItem(keyFor(owner), JSON.stringify(items.slice(0, MAX_ITEMS)));
    return true;
  } catch {
    return false; // 용량 초과 등
  }
}

export function saveWork(
  owner: string,
  item: Omit<WorkItem, "id" | "savedAt">,
  now = Date.now(),
  store: Store | null = browserStore(),
): WorkItem | null {
  const saved: WorkItem = { ...item, id: `${now.toString(36)}${Math.random().toString(36).slice(2, 6)}`, savedAt: new Date(now).toISOString() };
  return write(owner, [saved, ...listWork(owner, now, store)], store) ? saved : null;
}

export function deleteWork(owner: string, id: string, now = Date.now(), store: Store | null = browserStore()): WorkItem[] {
  const rest = listWork(owner, now, store).filter((i) => i.id !== id);
  write(owner, rest, store);
  return rest;
}

/** 공용 컴퓨터에서 다 쓴 뒤 이 계정의 작업함을 비운다 */
export function clearWork(owner: string, store: Store | null = browserStore()): void {
  write(owner, [], store);
}
