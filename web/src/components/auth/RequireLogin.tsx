"use client";

// 로그인한 사람만 쓰는 화면(규정 질문 외 업무 도구)을 감싼다.
// 확인 중엔 자리 표시, 로그인 전엔 로그인 카드, 계정이 바뀌면 안쪽 상태를 새로 시작한다(key) — 이전 계정의 입력이 남지 않게.

import { Fragment } from "react";

import { LoginCard } from "@/components/auth/Account";
import { useAuth } from "@/components/auth/AuthProvider";

export default function RequireLogin({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user === undefined) return <div className="mt-6 h-48 animate-pulse rounded-3xl bg-slate-100 motion-reduce:animate-none" />;
  if (!user)
    return (
      <div className="mt-6">
        <LoginCard />
      </div>
    );
  return <Fragment key={user.email}>{children}</Fragment>;
}
