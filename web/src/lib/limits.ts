// 운영 대시보드의 한도 입력값 검증

/** 서버 SettingsRequest의 상한과 같다. 넘으면 서버가 422로 거절한다. */
export const LIMIT_MAX = {
  daily_limit_total: 100_000,
  daily_limit_per_user: 10_000,
  daily_limit_per_ip: 10_000,
  cache_ttl_hours: 720,
} as const;

/** 입력칸 문자열을 저장할 정수로 바꾼다. 빈 값·소수·음수·숫자가 아닌 값·상한 초과는 null.
 *  `Number(value) || 0`으로 바꾸면 비운 칸이 0(= 제한 없음)으로 저장돼 비용 한도가 풀린다.
 *  0은 운영자가 직접 입력했을 때만 받는다. */
export function parseLimit(value: string, max: number): number | null {
  const v = value.trim();
  if (!/^\d+$/.test(v)) return null;
  const n = Number(v);
  return n <= max ? n : null;
}
