"use client";

// '작업함에 저장' — 결과 화면(기획·검토·회의록) 공통. 이 브라우저에 계정별로 남는다.

import { useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { BTN_MD, BTN_SECONDARY } from "@/lib/ui";
import { type WorkKind, saveWork } from "@/lib/workspace";

export default function SaveButton({ kind, title, text, disabled }: { kind: WorkKind; title: string; text: string; disabled?: boolean }) {
  const { user } = useAuth();
  const [state, setState] = useState<"idle" | "saved" | "failed">("idle");
  if (!user) return null;
  return (
    <button
      type="button"
      disabled={disabled || state === "saved"}
      onClick={() => setState(saveWork(user.email, { kind, title, text }) ? "saved" : "failed")}
      className={`${BTN_MD} ${BTN_SECONDARY}`}
    >
      {state === "saved" ? "작업함에 저장했어요" : state === "failed" ? "저장하지 못했어요" : "작업함에 저장"}
    </button>
  );
}
