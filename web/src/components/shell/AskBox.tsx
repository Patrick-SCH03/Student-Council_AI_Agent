"use client";

// 홈의 질문 입력창: 입력한 질문을 규정 질문 화면(/ask?q=…)으로 넘긴다.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { INPUT_FIELD, INPUT_PILL, SEND_BUTTON } from "@/lib/ui";

export default function AskBox() {
  const router = useRouter();
  const [text, setText] = useState("");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const q = text.trim();
        if (!q) return;
        router.push(`/ask?q=${encodeURIComponent(q.slice(0, 1000))}`);
      }}
      className={INPUT_PILL}
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="규정 질문 입력"
        placeholder="학생회 규정·재정·감사에 대해 물어보세요"
        maxLength={1000}
        className={INPUT_FIELD}
      />
      <button
        type="submit"
        disabled={!text.trim()}
        aria-label="질문 보내기"
        className={SEND_BUTTON}
      >
        <SendArrow />
      </button>
    </form>
  );
}

/** 보내기 화살표 (홈·규정 질문 입력창 공통) */
export function SendArrow() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}
