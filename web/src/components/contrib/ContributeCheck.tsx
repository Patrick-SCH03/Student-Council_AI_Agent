"use client";

// 서비스 개선에 쓰도록 허락하는 동의 (기본 허락 — 운영자 결정 2026-11-28, 언제든 해제 가능). 해제해도 기능은 그대로 쓴다.

import Link from "next/link";

export default function ContributeCheck({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-2 text-[13px] leading-snug text-slate-600">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-slate-900"
      />
      <span>
        서비스 개선에 쓰도록 허락해요 (원치 않으면 해제) · 이름·학번·연락처를 가린 내용만 1년 보관하고 언제든 지울 수 있어요.{" "}
        <Link href="/privacy" className="font-semibold text-indigo-600 hover:underline">
          자세히
        </Link>
      </span>
    </label>
  );
}
