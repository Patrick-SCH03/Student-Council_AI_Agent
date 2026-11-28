"use client";

// Google Identity Services 버튼. 받은 ID 토큰은 서버가 직접 검증한다(학교 도메인 확인 포함).

import { useEffect, useRef, useState } from "react";

import { useAuth } from "./AuthProvider";

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
const GSI_SRC = "https://accounts.google.com/gsi/client";

type Gsi = {
  accounts: {
    id: {
      initialize: (o: Record<string, unknown>) => void;
      renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
    };
  };
};

let gsiPromise: Promise<Gsi> | null = null;

function loadGsi(): Promise<Gsi> {
  const w = window as unknown as { google?: Gsi };
  if (w.google?.accounts?.id) return Promise.resolve(w.google);
  gsiPromise ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = GSI_SRC;
    s.async = true;
    s.onload = () => (w.google ? resolve(w.google) : reject(new Error("gsi")));
    s.onerror = () => {
      gsiPromise = null;
      reject(new Error("gsi"));
    };
    document.head.appendChild(s);
  });
  return gsiPromise;
}

export default function GoogleButton({ onDone }: { onDone?: () => void }) {
  const { login } = useAuth();
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!CLIENT_ID) return;
    let alive = true;
    loadGsi()
      .then((g) => {
        if (!alive || !ref.current) return;
        g.accounts.id.initialize({
          client_id: CLIENT_ID,
          // 학교 계정을 먼저 보여 주는 힌트일 뿐, 실제 제한은 서버가 한다
          hd: "inha.edu",
          ux_mode: "popup",
          callback: async ({ credential }: { credential: string }) => {
            setBusy(true);
            setError(null);
            try {
              await login(credential);
              onDone?.();
            } catch (e) {
              setError(e instanceof Error ? e.message : "로그인하지 못했어요.");
            } finally {
              setBusy(false);
            }
          },
        });
        g.accounts.id.renderButton(ref.current, {
          theme: "outline",
          size: "large",
          shape: "pill",
          text: "signin_with",
          logo_alignment: "left",
          locale: "ko",
          width: 280,
        });
      })
      .catch(() => alive && setError("Google 로그인을 불러오지 못했어요. 잠시 후 다시 시도해 주세요."));
    return () => {
      alive = false;
    };
  }, [login, onDone]);

  if (!CLIENT_ID) {
    return <p className="text-[13px] text-slate-500">로그인이 아직 설정되지 않았어요.</p>;
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <div ref={ref} className={`flex min-h-11 justify-center ${busy ? "pointer-events-none opacity-50" : ""}`} />
      {busy && <p className="text-[13px] text-slate-500">로그인하고 있어요…</p>}
      {error && (
        <p role="alert" className="text-center text-[13px] font-medium text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
}
