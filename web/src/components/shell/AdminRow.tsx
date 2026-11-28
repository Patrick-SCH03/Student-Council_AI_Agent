"use client";

// 더보기 목록의 관리자 패널 행 — 관리자 계정에만 보인다

import Link from "next/link";

import { LIST_ROW } from "@/lib/ui";

import { ADMIN, NavIcon } from "./nav";
import { useCanPreview } from "./SoonBadge";

export default function AdminRow() {
  if (!useCanPreview()) return null;
  return (
    <li>
      <Link href={ADMIN.href} className={`${LIST_ROW} text-slate-800 hover:text-slate-950`}>
        <NavIcon path={ADMIN.icon} className="h-5 w-5 text-slate-500" />
        {ADMIN.label}
        <span aria-hidden className="ml-auto text-slate-300">
          ›
        </span>
      </Link>
    </li>
  );
}
