// 화면 표기 공통 (숫자·비용·조사)

export function fmt(n: number): string {
  return n.toLocaleString("ko-KR");
}

/** 비용은 달러로만 표시한다. 1달러 미만은 질의 몇 건의 차이가 보이도록 소수 넷째 자리까지. */
export function usd(n: number): string {
  if (n === 0) return "$0";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`;
}

/** 5698191 → "5,698,191원" (소수는 반올림). 값이 없으면 — */
export function won(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "—" : `${(Math.round(value) || 0).toLocaleString("ko-KR")}원`; // -0 → 0
}

/** 오늘 날짜(한국 자정 기준) YYYY-MM-DD */
export function todayKst(now: Date = new Date()): string {
  return now.toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });
}

/** 받침에 맞는 조사 ('간식드리미'는 · '멘토링'은 · 학생회는) */
export function josa(word: string, withFinal: string, without: string): string {
  const base = word.replace(/[^가-힣A-Za-z0-9]+$/, ""); // 따옴표·괄호는 건너뛰고 마지막 글자를 본다
  const code = base.charCodeAt(base.length - 1) - 0xac00;
  const final = code >= 0 && code < 11172 ? code % 28 !== 0 : /[013678lmnr]$/i.test(base);
  return `${word}${final ? withFinal : without}`;
}
