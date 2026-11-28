import Link from "next/link";

import AskBox from "@/components/shell/AskBox";
import SoonBadge from "@/components/shell/SoonBadge";
import UpcomingEvents from "@/components/shell/UpcomingEvents";
import { NavIcon, icons } from "@/components/shell/nav";

type Start = {
  href: string;
  title: string;
  desc: string;
  icon: React.ReactNode;
  tone: string;
  soon?: boolean;
};

const STARTS: Start[] = [
  {
    href: "/plan",
    title: "사업 기획하기",
    desc: "개요만 적으면 총회 양식 초안을 써요",
    icon: icons.plan,
    tone: "from-emerald-100 to-lime-50 text-emerald-700",
  },
  {
    href: "/review",
    title: "문서 올려서 점검하기",
    desc: "예산안·결산서를 규정에 맞춰 점검해요",
    icon: <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 20h16" />,
    tone: "from-indigo-100 to-violet-50 text-indigo-700",
  },
  {
    href: "/ask",
    title: "규정 질문하기",
    desc: "회칙·세칙·감사 사례로 답해요",
    icon: icons.ask,
    tone: "from-sky-100 to-cyan-50 text-sky-700",
  },
  {
    href: "/audit",
    title: "정기감사 대비",
    desc: "오픈 준비 중이에요",
    icon: icons.audit,
    tone: "from-amber-100 to-orange-50 text-amber-700",
    soon: true,
  },
];

/** 할 일 칩: 누르면 바로 규정 질문으로 보낸다 */
const CHIPS: { text: string; q: string }[] = [
  { text: "증빙서류를 알려줘요", q: "행사 물품 구매 시 증빙서류는 무엇을 준비해야 하나요?" },
  { text: "사례금 지급 방법을 알려줘요", q: "외부 강사 사례금은 어떻게 지급해야 하나요?" },
  { text: "예산 변경 절차를 알려줘요", q: "예산 변경 시 필요한 승인 절차는 무엇인가요?" },
  { text: "감사 처분을 알려줘요", q: "감사에서 어떤 처분을 받을 수 있나요?" },
];

export default function HomePage() {
  return (
    <div className="relative mx-auto w-full max-w-4xl px-4 pb-10 pt-10 lg:px-8 lg:pt-20">
      {/* 제목 뒤 은은한 빛 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-10 -z-10 mx-auto h-[420px] max-w-3xl bg-[radial-gradient(closest-side,rgba(129,140,248,0.22),transparent),radial-gradient(closest-side_at_70%_60%,rgba(56,189,248,0.16),transparent)] blur-2xl"
      />
      <div className="text-center">
        <p className="text-[12px] font-bold uppercase tracking-[0.22em] text-indigo-500">INHA Student Council</p>
        <h1 className="mt-3 text-[30px] font-extrabold leading-[1.25] tracking-tight text-slate-950 sm:text-[40px]">
          학생회를 위한
          <br />
          AI 업무 파트너
        </h1>
        <p className="mt-3 text-[15px] font-medium leading-relaxed text-slate-500">
          규정 확인, 예산 검토, 공문·회의록 작성
          <br />
          학생회 일을 한 곳에서 끝내요
        </p>
      </div>

      <div className="mx-auto mt-8 max-w-2xl">
        <AskBox />
      </div>

      <ul className="-mx-4 mt-3 flex snap-x gap-2 overflow-x-auto px-4 py-1.5 [scrollbar-width:none] sm:mx-auto sm:max-w-2xl sm:flex-wrap sm:justify-center sm:overflow-visible sm:px-0">
        {CHIPS.map((c) => (
          <li key={c.q} className="shrink-0">
            <Link
              href={{ pathname: "/ask", query: { q: c.q } }}
              className="inline-flex snap-start items-center gap-1.5 whitespace-nowrap rounded-full bg-white px-3.5 py-2 text-[13px] font-semibold text-slate-700 shadow-[0_2px_10px_rgba(15,23,42,0.08)] ring-1 ring-slate-200/70 transition hover:-translate-y-0.5 hover:text-slate-950 motion-reduce:transition-none"
            >
              <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
              {c.text}
            </Link>
          </li>
        ))}
      </ul>

      <UpcomingEvents />

      <div className="mt-10 grid gap-3 sm:mt-12 sm:grid-cols-2 sm:gap-4">
        {STARTS.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className={`group relative flex items-center gap-4 overflow-hidden rounded-3xl bg-gradient-to-br p-5 transition hover:-translate-y-0.5 motion-reduce:transition-none sm:block sm:p-6 ${s.tone}`}
          >
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white/80 shadow-sm">
              <NavIcon path={s.icon} />
            </span>
            <span className="block min-w-0 sm:mt-6">
              <span className="flex items-center gap-2 text-[17px] font-extrabold tracking-tight text-slate-950">
                {s.title}
                {s.soon && <SoonBadge />}
              </span>
              <span className="mt-1 block text-[13px] font-medium text-slate-600">{s.desc}</span>
            </span>
            <span
              aria-hidden
              className="absolute right-5 top-1/2 -translate-y-1/2 text-[20px] sm:top-5 sm:translate-y-0 text-slate-950/30 transition group-hover:translate-x-0.5 group-hover:text-slate-950/60"
            >
              →
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
