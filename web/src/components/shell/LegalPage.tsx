import Link from "next/link";

import { CARD, PAGE, SECTION_TITLE } from "@/lib/ui";

import PageHeader from "./PageHeader";

export type LegalSection = { title: string; body: React.ReactNode };

export const CONTACT_EMAIL = "wwoo5241@inha.edu";

/** 개인정보처리방침·이용약관 공통 틀 */
export default function LegalPage({
  title,
  updated,
  intro,
  sections,
}: {
  title: string;
  updated: string;
  intro: string;
  sections: LegalSection[];
}) {
  return (
    <div className={PAGE}>
      <PageHeader title={title} desc={updated} />
      <p className="mt-4 text-[15px] leading-relaxed text-slate-700">{intro}</p>
      <div className={`mt-6 divide-y divide-slate-100 ${CARD}`}>
        {sections.map((s, i) => (
          <section key={s.title} className="px-5 py-5 sm:px-6">
            <h2 className={SECTION_TITLE}>
              {i + 1}. {s.title}
            </h2>
            <div className="mt-2 space-y-2 text-[14px] leading-relaxed text-slate-600 [&_li]:ml-4 [&_li]:list-disc [&_strong]:font-semibold [&_strong]:text-slate-800 [&_ul]:space-y-1">
              {s.body}
            </div>
          </section>
        ))}
      </div>
      <LegalLinks className="mt-6 justify-center" />
    </div>
  );
}

export function MailLink() {
  return (
    <a href={`mailto:${CONTACT_EMAIL}`} className="font-semibold text-indigo-600 hover:underline">
      {CONTACT_EMAIL}
    </a>
  );
}

/** 개인정보처리방침·이용약관 링크 한 줄 */
export function LegalLinks({ className = "" }: { className?: string }) {
  return (
    <p className={`flex items-center gap-2 text-[12px] text-slate-500 ${className}`}>
      <Link href="/privacy" className="hover:text-slate-900 hover:underline">
        개인정보처리방침
      </Link>
      <span aria-hidden className="text-slate-300">·</span>
      <Link href="/terms" className="hover:text-slate-900 hover:underline">
        이용약관
      </Link>
    </p>
  );
}
