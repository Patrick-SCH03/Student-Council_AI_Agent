// 화면 공통 스타일 토큰 — 화면마다 값을 따로 적지 말고 여기서 가져다 쓴다.
// 규격: 제목 slate-950 · 본문 slate-600 · 보조 slate-500, 큰 카드 24px · 목록 묶음 16px 모서리,
// 버튼은 알약 모양(검은 주 버튼 / 흰 보조 버튼), 높이 32px(작게)·40px(기본)·44px(입력 보내기).

// AI Chatbot UI Kit 카드 섀도 토큰
export const CARD_SHADOW =
  "shadow-[0px_12px_16px_-4px_rgba(16,24,40,0.08),0px_4px_6px_-2px_rgba(16,24,40,0.03)]";

/** 양식 입력 칸 */
export const INPUT =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-[16px] text-slate-800 sm:text-[14px] outline-none transition focus:border-slate-900";

/** 본문 화면 폭·여백 (홈만 더 넓다) */
export const PAGE = "mx-auto w-full max-w-3xl px-4 py-6 lg:py-10";
export const PAGE_TITLE = "text-[24px] font-extrabold tracking-tight text-slate-950";
export const PAGE_DESC = "mt-1.5 text-[14px] leading-relaxed text-slate-500";
export const SECTION_TITLE = "text-[16px] font-bold text-slate-950";

/** 큰 카드 (안내·로그인·약관 본문) */
export const CARD = `rounded-3xl border border-slate-200 bg-white ${CARD_SHADOW}`;
/** 목록 묶음 (메뉴·설정 행) */
export const LIST = `divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white ${CARD_SHADOW}`;
export const LIST_ROW = "flex min-h-[52px] items-center gap-3 px-4 py-3 text-[15px] font-semibold";

const BTN = "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full font-semibold transition disabled:opacity-40";
export const BTN_SM = `${BTN} h-8 px-3.5 text-[13px]`;
export const BTN_MD = `${BTN} h-10 px-4 text-[14px]`;
export const BTN_PRIMARY = "bg-slate-950 text-white hover:bg-slate-800";
export const BTN_SECONDARY = "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:text-slate-950";
export const BTN_GHOST = "text-slate-500 hover:bg-slate-100 hover:text-slate-950";

/** 알약 모양 질문 입력창과 둥근 보내기 버튼 (홈·규정 질문 공통) */
export const INPUT_PILL =
  "flex items-center gap-2 rounded-full bg-white p-2 pl-6 shadow-[0_8px_30px_rgba(15,23,42,0.10)] ring-1 ring-slate-200 transition focus-within:ring-2 focus-within:ring-slate-900";
export const INPUT_FIELD =
  "min-w-0 flex-1 bg-transparent py-2.5 text-[16px] font-medium sm:text-[15px] text-slate-800 placeholder-slate-400 outline-none";
export const SEND_BUTTON =
  "flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-slate-950 text-white transition hover:bg-slate-800 disabled:opacity-30";
