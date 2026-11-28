// 홈 '다가오는 일정' 표시용 순수 함수 (네트워크 없음 — 단위 테스트가 바로 불러 쓴다).

export type Event = { date: string; title: string; href: string | null };

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];
const DAY = 86_400_000;
const utc = (d: string) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));

/** 오늘(YYYY-MM-DD) 기준 'D-3' · '오늘' · '내일' */
export function dday(date: string, today: string): string {
  const n = Math.round((utc(date) - utc(today)) / DAY);
  return n === 0 ? "오늘" : n === 1 ? "내일" : n > 0 ? `D-${n}` : `${-n}일 전`;
}

/** '12월 5일 (금)' */
export function dateLabel(date: string): string {
  const t = new Date(utc(date));
  return `${t.getUTCMonth() + 1}월 ${t.getUTCDate()}일 (${WEEK[t.getUTCDay()]})`;
}
