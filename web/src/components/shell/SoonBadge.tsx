"use client";

// 아직 열지 않은 기능(nav의 soon)의 표시. 관리자 계정은 파일럿 테스트를 위해 먼저 써 본다.

import { useAuth } from "@/components/auth/AuthProvider";

/** 관리자면 실제 화면을 연다 (서버가 ADMIN_EMAILS로 정한 role) */
export function useCanPreview(): boolean | undefined {
  const { user } = useAuth();
  if (user === undefined) return undefined;
  return user?.role === "admin";
}

export default function SoonBadge({ className = "" }: { className?: string }) {
  const admin = useCanPreview();
  if (admin === undefined) return null;
  return admin ? (
    <span className={`rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800 ${className}`}>미리보기</span>
  ) : (
    <span className={`rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-600 ${className}`}>오픈 예정</span>
  );
}
