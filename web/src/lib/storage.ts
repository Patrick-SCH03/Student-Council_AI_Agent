// 이 브라우저 저장소(localStorage). 서버 렌더링·저장소 차단 환경에서는 null — 단위 테스트는 가짜 저장소를 넘긴다.

export type Store = Pick<Storage, "getItem" | "setItem">;

export function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // 저장소 차단 환경
  }
}
