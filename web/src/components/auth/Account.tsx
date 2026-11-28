"use client";

// 계정 표시 조각들: 사이드바 계정, 모바일 상단 계정 버튼, 로그인 안내 카드, 더보기 계정 행.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { type User, initial } from "@/lib/auth";
import { BTN_GHOST, BTN_MD, BTN_PRIMARY, BTN_SECONDARY, BTN_SM, CARD, LIST } from "@/lib/ui";

import { useAuth } from "./AuthProvider";
import GoogleButton from "./GoogleButton";

function loginHref(pathname: string): string {
  return pathname === "/login" ? "/login" : `/login?next=${encodeURIComponent(pathname)}`;
}

function Skeleton({ className }: { className: string }) {
  return <div aria-hidden className={`animate-pulse bg-slate-100 motion-reduce:animate-none ${className}`} />;
}

function Avatar({ user, size = "h-9 w-9 text-[14px]" }: { user: User; size?: string }) {
  return (
    <span aria-hidden className={`flex shrink-0 items-center justify-center rounded-full bg-indigo-100 font-bold text-indigo-700 ${size}`}>
      {initial(user)}
    </span>
  );
}

/** 이름·이메일 두 줄 */
function Identity({ user }: { user: User }) {
  return (
    <div className="min-w-0 flex-1 leading-tight">
      <p className="truncate text-[14px] font-bold text-slate-950">{user.name || "학교 계정"}</p>
      <p className="mt-1 truncate text-[12px] text-slate-500">{user.email}</p>
    </div>
  );
}

/** 로그아웃: 서버가 세션을 폐기하지 못하면 상태를 바꾸지 않고 알린다 */
function LogoutButton({ className }: { className: string }) {
  const { logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await logout();
    } catch (e) {
      setError(e instanceof Error ? e.message : "로그아웃하지 못했어요.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button type="button" disabled={busy} onClick={run} className={className}>
        로그아웃
      </button>
      {error && (
        <p role="alert" className="basis-full text-[12px] font-medium text-rose-600">
          {error}
        </p>
      )}
    </>
  );
}

/** 데스크톱 사이드바 아래 */
export function SidebarAccount() {
  const { user } = useAuth();
  const pathname = usePathname();
  if (user === undefined) return <Skeleton className="h-10 rounded-full" />;
  if (!user) {
    return (
      <Link href={loginHref(pathname)} className={`${BTN_MD} ${BTN_PRIMARY} w-full`}>
        로그인
      </Link>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <Avatar user={user} />
      <Identity user={user} />
      <LogoutButton className={`${BTN_SM} ${BTN_GHOST} px-2.5`} />
    </div>
  );
}

/** 모바일 상단 바 오른쪽 */
export function HeaderAccount() {
  const { user } = useAuth();
  const pathname = usePathname();
  if (user === undefined) return <Skeleton className="h-8 w-8 rounded-full" />;
  if (!user) {
    return (
      <Link href={loginHref(pathname)} className={`${BTN_SM} ${BTN_PRIMARY}`}>
        로그인
      </Link>
    );
  }
  return (
    <Link href="/more" aria-label="내 계정">
      <Avatar user={user} size="h-8 w-8 text-[13px]" />
    </Link>
  );
}

/** 로그인이 필요한 화면의 안내 카드 */
export function LoginCard({ title = "로그인", next }: { title?: string; next?: string }) {
  const router = useRouter();
  return (
    <section className={`mx-auto w-full max-w-md px-6 py-8 text-center ${CARD}`}>
      <h2 className="text-[20px] font-extrabold tracking-tight text-slate-950">{title}</h2>
      <p className="mt-2 text-[14px] text-slate-500">
        인하대학교 메일 <span className="font-semibold text-slate-700">@inha.edu</span> 계정으로만 로그인할 수 있어요.
      </p>
      <div className="mt-6">
        <GoogleButton onDone={next ? () => router.replace(next) : undefined} />
      </div>
      <p className="mt-4 text-[12px] text-slate-500">
        로그인하면{" "}
        <Link href="/terms" className="underline hover:text-slate-900">
          이용약관
        </Link>
        과{" "}
        <Link href="/privacy" className="underline hover:text-slate-900">
          개인정보처리방침
        </Link>
        에 동의하게 돼요.
      </p>
    </section>
  );
}

/** 더보기 화면 위쪽 계정 영역 */
export function MoreAccount() {
  const { user } = useAuth();
  if (user === undefined) return <Skeleton className="h-[68px] rounded-2xl" />;
  if (!user) return <LoginCard />;
  return (
    <div className={`flex flex-wrap items-center gap-3 p-4 ${LIST}`}>
      <Avatar user={user} size="h-10 w-10 text-[15px]" />
      <Identity user={user} />
      <LogoutButton className={`${BTN_SM} ${BTN_SECONDARY}`} />
    </div>
  );
}
