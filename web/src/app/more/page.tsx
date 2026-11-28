import type { Metadata } from "next";
import Link from "next/link";

import ContactButton from "@/components/ContactButton";
import { MoreAccount } from "@/components/auth/Account";
import { LegalLinks } from "@/components/shell/LegalPage";
import { AUDIT, CHECKLIST, INBOX, NavIcon, PLAN, WRITE } from "@/components/shell/nav";
import AdminRow from "@/components/shell/AdminRow";
import PageHeader from "@/components/shell/PageHeader";
import SoonBadge from "@/components/shell/SoonBadge";
import { LIST, LIST_ROW, PAGE } from "@/lib/ui";

export const metadata: Metadata = { title: "더보기 · 학생회 업무 AI" };

export default function MorePage() {
  return (
    <div className={PAGE}>
      <PageHeader title="더보기" />

      <div className="mt-5">
        <MoreAccount />
      </div>

      <ul className={`mt-4 ${LIST}`}>
        {[PLAN, WRITE, CHECKLIST, AUDIT, INBOX].map((item) => (
          <li key={item.href}>
            <Link href={item.href} className={`${LIST_ROW} text-slate-800 hover:text-slate-950`}>
              <NavIcon path={item.icon} className="h-5 w-5 text-slate-500" />
              {item.label}
              {item.soon && <SoonBadge />}
              <span aria-hidden className="ml-auto text-slate-300">
                ›
              </span>
            </Link>
          </li>
        ))}
        <AdminRow />
      </ul>

      <div className={`mt-4 ${LIST}`}>
        <div className={`${LIST_ROW} justify-between text-slate-800`}>
          문의하기
          <ContactButton />
        </div>
      </div>

      <LegalLinks className="mt-6 justify-center" />
    </div>
  );
}
