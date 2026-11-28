"use client";

// 클립보드 복사 공통: 복사하고 2초 동안 '복사했어요'를 보인다. 권한이 막히면 조용히 넘어간다(화면의 글을 직접 복사하면 된다).

import { useCallback, useState } from "react";

export function useCopy(): [boolean, (text: string) => Promise<void>] {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 권한 거부
    }
  }, []);
  return [copied, copy];
}
