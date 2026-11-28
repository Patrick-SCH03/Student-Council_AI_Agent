// 화면 위 공지: 서버가 준 공지를 이 브라우저에서 닫았는지 기억한다. 네트워크 없음 — 단위 테스트가 바로 불러 쓴다.

import { type Store, browserStore } from "./storage.ts";

export type Notice = { id: string; text: string; href: string | null; until: string | null };

const DISMISSED_KEY = "notice-dismissed";


/** 닫은 공지는 숨긴다. 내용을 고쳐 다시 올리면 id가 바뀌어 다시 보인다 */
export function visibleNotice(notice: Notice | null, store: Store | null = browserStore()): Notice | null {
  if (!notice) return null;
  try {
    return store?.getItem(DISMISSED_KEY) === notice.id ? null : notice;
  } catch {
    return notice;
  }
}

export function dismissNotice(notice: Notice, store: Store | null = browserStore()): void {
  try {
    store?.setItem(DISMISSED_KEY, notice.id);
  } catch {
    // 기억하지 못해도 이번 화면에서는 닫힌다
  }
}
