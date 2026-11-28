"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { type User, fetchMe, loginWithGoogle, logout as apiLogout } from "@/lib/auth";

type AuthState = {
  /** undefined = 확인 중, null = 로그인 안 함 */
  user: User | null | undefined;
  login: (credential: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    fetchMe()
      .then((u) => alive && setUser(u))
      // 서버에 닿지 않으면 로그인 안 한 것으로 본다 — 익명 기능(규정 질문)은 그대로 쓴다
      .catch(() => alive && setUser(null));
    return () => {
      alive = false;
    };
  }, []);

  const login = useCallback(async (credential: string) => {
    setUser(await loginWithGoogle(credential));
  }, []);

  // 실패하면 그대로 던진다 — 호출한 화면이 안내한다 (로그인 상태는 바꾸지 않음)
  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth는 AuthProvider 안에서만 써요");
  return ctx;
}
