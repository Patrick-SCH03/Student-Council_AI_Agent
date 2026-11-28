// 플랫폼 메뉴 정의 — 데스크톱 사이드바·모바일 하단 탭·더보기 화면이 같은 목록을 쓴다.
// 'use client' 없이 두어 서버 컴포넌트(홈·더보기)에서도 값으로 쓸 수 있게 한다.

export type NavItem = {
  href: string;
  label: string;
  icon: React.ReactNode;
  badge?: string;
  /** 오픈 예정 — 일반 사용자에겐 안내만, 관리자 계정은 미리 써 본다 (SoonBadge) */
  soon?: boolean;
};

// 아이콘은 24×24 안에서 그림의 가운데가 (12, 12)에 오도록 맞춘다 (어긋나면 글자와 줄이 밀려 보인다)
export const icons = {
  home: <path d="M3 12l9-8 9 8M5 10v10h14V10" />,
  ask: <path transform="translate(-0.5 -0.8)" d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />,
  // 가운데(x 6~18)에 놓은 문서 + 접힌 귀퉁이 + 체크
  review: <path d="M14 3H6v18h12V7zM14 3v4h4M9 14l2 2 4-4" />,
  checklist: <path d="M9 12l2 2 4-4M5 4h14v16H5z" />,
  plan: <path transform="translate(0 1.4)" d="M12 3l2.5 5 5.5.8-4 3.9.9 5.5L12 15.6 7.1 18.2 8 12.7 4 8.8 9.5 8z" />,
  write: <path transform="translate(0.5 -0.5)" d="M4 20h4L19 9l-4-4L4 16zM13 7l4 4" />,
  inbox: <path d="M3 7h18M3 12h18M3 17h12" />,
  audit: <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6zM9 12l2 2 4-4" />,
  more: <path d="M4 6h16M4 12h16M4 18h16" />,
  admin: <path d="M5 20V11M12 20V5M19 20v-6M3 20h18" />,
};

export const HOME: NavItem = { href: "/", label: "홈", icon: icons.home };
export const ASK: NavItem = { href: "/ask", label: "규정 질문", icon: icons.ask };
export const REVIEW: NavItem = { href: "/review", label: "문서 검토", icon: icons.review };
export const CHECKLIST: NavItem = { href: "/checklist", label: "법령 점검표", icon: icons.checklist };
export const AUDIT: NavItem = { href: "/audit", label: "정기감사 대비", icon: icons.audit, soon: true };
export const WRITE: NavItem = { href: "/write", label: "문서 작성", icon: icons.write };
export const PLAN: NavItem = { href: "/plan", label: "기획 도우미", icon: icons.plan, badge: "NEW" };

export const INBOX: NavItem = { href: "/inbox", label: "내 작업함", icon: icons.inbox };

/** 관리자 계정(ADMIN_EMAILS)에만 보인다 — 운영 지표·설정 */
export const ADMIN: NavItem = { href: "/stats", label: "관리자 패널", icon: icons.admin };

/** 사이드바 구분선 아래 (내 기록) */
export const SECONDARY: NavItem[] = [INBOX];

/** 데스크톱 사이드바 주 메뉴 */
export const SIDEBAR: NavItem[] = [HOME, ASK, PLAN, REVIEW, WRITE, CHECKLIST, AUDIT];

/** 모바일 하단 탭 (2026-11-28 확정: 4개, 점검표·작업함은 더보기 안) */
export const TABS: NavItem[] = [HOME, ASK, { ...REVIEW, badge: undefined }, { href: "/more", label: "더보기", icon: icons.more }];

/** 더보기 탭이 활성으로 보일 경로 (탭에 없는 화면들) */
export const MORE_PATHS = ["/more", "/plan", "/checklist", "/audit", "/write", "/inbox", "/stats"];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/more") return MORE_PATHS.some((p) => pathname.startsWith(p));
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function NavIcon({ path, className = "h-5 w-5" }: { path: React.ReactNode; className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      viewBox="0 0 24 24"
      aria-hidden
    >
      {path}
    </svg>
  );
}
