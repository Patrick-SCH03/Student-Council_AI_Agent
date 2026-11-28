"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { LoginCard } from "@/components/auth/Account";
import { PAGE } from "@/lib/ui";

/** 돌아갈 주소는 이 사이트 안의 경로만 받는다 (외부 주소로 보내는 열린 리디렉션 방지) */
function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

export default function LoginPage() {
  const { user } = useAuth();
  const router = useRouter();
  // useSearchParams는 정적 렌더에 Suspense 경계를 요구해 마운트 후 window에서 읽는다
  const [next, setNext] = useState("/");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 주소의 next를 마운트 후 한 번 읽는다
    setNext(safeNext(new URLSearchParams(window.location.search).get("next")));
  }, []);

  useEffect(() => {
    if (user) router.replace(next);
  }, [user, next, router]);

  return (
    <div className={`${PAGE} lg:py-20`}>
      <h1 className="sr-only">로그인</h1>
      <LoginCard next={next} />
    </div>
  );
}
