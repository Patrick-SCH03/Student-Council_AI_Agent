"use client";

// 시안 A 화면 뼈대: 데스크톱(lg 이상)은 왼쪽 사이드바, 모바일은 상단 바 + 하단 탭 4개.
// 본문 스크롤은 창(window) 그대로 둔다 — 규정 질문의 '따라가기' 스크롤이 창 기준이다.

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import ContactButton from "@/components/ContactButton";
import { HeaderAccount, SidebarAccount } from "@/components/auth/Account";
import { LegalLinks } from "@/components/shell/LegalPage";
import { AuthProvider } from "@/components/auth/AuthProvider";

import { ADMIN, type NavItem, NavIcon, SECONDARY, SIDEBAR, TABS, isActive } from "./nav";
import NoticeBar from "./NoticeBar";
import SoonBadge, { useCanPreview } from "./SoonBadge";

/** 브랜드: 인하대 마크 + 글자 로고 (단색, 군더더기 없이). 데스크톱 사이드바는 마크가 잘 보이게 크게 */
function Brand({ large = false }: { large?: boolean }) {
  const size = large ? 44 : 34;
  return (
    <Link href="/" aria-label="학생회 업무 AI 홈" className={`flex items-center ${large ? "gap-3" : "gap-2.5"}`}>
      <Image src="/emblem.svg" alt="" width={size} height={size} priority />
      <span className={`${large ? "text-[19px]" : "text-[17px]"} font-extrabold tracking-tight text-slate-950`}>학생회 업무 AI</span>
    </Link>
  );
}

function SidebarLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-3 rounded-full px-4 py-2.5 transition ${
        active ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
      }`}
    >
      <NavIcon path={item.icon} />
      {item.label}
      {item.badge && <span className="ml-auto rounded-full bg-indigo-500 px-2 py-0.5 text-[10px] font-bold text-white">{item.badge}</span>}
      {item.soon && <SoonBadge className="ml-auto" />}
    </Link>
  );
}

/** 관리자 계정일 때만 사이드바에 관리자 패널을 더한다 */
function AdminLink({ pathname }: { pathname: string }) {
  return useCanPreview() ? <SidebarLink item={ADMIN} active={isActive(pathname, ADMIN.href)} /> : null;
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <AuthProvider>
      {/* 데스크톱 사이드바 */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 print:!hidden flex-col border-r border-slate-200/70 bg-white lg:flex">
        <div className="flex h-20 items-center px-5">
          <Brand large />
        </div>
        <nav aria-label="주 메뉴" className="flex-1 space-y-1 px-3 py-2 text-[14px] font-semibold">
          {SIDEBAR.map((item) => (
            <SidebarLink key={item.href} item={item} active={isActive(pathname, item.href)} />
          ))}
          <div className="my-3 border-t border-slate-100" />
          {SECONDARY.map((item) => (
            <SidebarLink key={item.href} item={item} active={isActive(pathname, item.href)} />
          ))}
          <AdminLink pathname={pathname} />
        </nav>
        <div className="space-y-4 border-t border-slate-100 p-4">
          <SidebarAccount />
          <ContactButton placement="above-start" />
          <LegalLinks />
        </div>
      </aside>

      {/* 모바일 상단 바 */}
      <header className="sticky top-0 z-10 bg-slate-50/80 backdrop-blur-md lg:hidden print:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <Brand />
          <HeaderAccount />
        </div>
      </header>

      <main className="w-full flex-1 pb-28 lg:pb-0 lg:pl-64 print:p-0">
        <NoticeBar />
        {children}
      </main>

      {/* 모바일 하단 탭: 떠 있는 알약 모양 */}
      <nav
        aria-label="주 메뉴"
        className="fixed inset-x-4 bottom-[calc(0.75rem+env(safe-area-inset-bottom))] z-20 grid h-16 grid-cols-4 rounded-full bg-white/90 p-1.5 text-[11px] font-semibold shadow-[0_8px_30px_rgba(15,23,42,0.14)] ring-1 ring-slate-200/80 backdrop-blur-md lg:hidden print:hidden"
      >
        {TABS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex flex-col items-center justify-center gap-0.5 rounded-full transition ${
                active ? "bg-slate-950 text-white" : "text-slate-500 hover:text-slate-950"
              }`}
            >
              <NavIcon path={item.icon} className="h-[18px] w-[18px]" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </AuthProvider>
  );
}
