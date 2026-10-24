// 화면 숫자 표기 (대시보드 공통)

export function fmt(n: number): string {
  return n.toLocaleString("ko-KR");
}

/** 비용은 달러로만 표시한다. 1달러 미만은 질의 몇 건의 차이가 보이도록 소수 넷째 자리까지. */
export function usd(n: number): string {
  if (n === 0) return "$0";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`;
}
