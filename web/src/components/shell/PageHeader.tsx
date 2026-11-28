import { PAGE_DESC, PAGE_TITLE } from "@/lib/ui";

/** 화면 제목 (모든 본문 화면이 같은 크기·간격을 쓴다) */
export default function PageHeader({ title, desc }: { title: string; desc?: string }) {
  return (
    <header>
      <h1 className={PAGE_TITLE}>{title}</h1>
      {desc && <p className={PAGE_DESC}>{desc}</p>}
    </header>
  );
}
