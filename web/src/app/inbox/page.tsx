"use client";

// 내 작업함: '작업함에 저장'한 기획 초안·검토 결과·회의록. 이 브라우저에만 계정별로 30일 남는다(서버 저장 없음).

import { useEffect, useState } from "react";

import { LoginCard } from "@/components/auth/Account";
import { useAuth } from "@/components/auth/AuthProvider";
import MyContributions from "@/components/contrib/MyContributions";
import PageHeader from "@/components/shell/PageHeader";
import { BTN_SM, BTN_GHOST, BTN_SECONDARY, CARD, LIST, PAGE } from "@/lib/ui";
import { useCopy } from "@/lib/useCopy";
import { KEEP_DAYS, KIND_LABEL, type WorkItem, clearWork, deleteWork, listWork } from "@/lib/workspace";

const when = (iso: string) => {
  const d = new Date(iso);
  return `${d.getMonth() + 1}.${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

function Item({ item, onDelete }: { item: WorkItem; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const [copied, copyText] = useCopy();
  const copy = () => copyText(item.text);
  return (
    <li className="px-4 py-3">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-3 text-left">
        <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-bold text-slate-600">{KIND_LABEL[item.kind]}</span>
        <span className="min-w-0 flex-1 truncate text-[15px] font-semibold text-slate-950">{item.title}</span>
        <span className="shrink-0 text-[12px] tabular-nums text-slate-500">{when(item.savedAt)}</span>
      </button>
      {open && (
        <div className="mt-3">
          <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 font-sans text-[13px] leading-relaxed text-slate-800">
            {item.text}
          </pre>
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" onClick={onDelete} className={`${BTN_SM} ${BTN_GHOST}`}>
              지우기
            </button>
            <button type="button" onClick={copy} className={`${BTN_SM} ${BTN_SECONDARY}`}>
              {copied ? "복사했어요" : "복사"}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

export default function InboxPage() {
  const { user } = useAuth();
  const owner = user ? user.email : null;
  const [items, setItems] = useState<WorkItem[] | null>(null);

  useEffect(() => {
    // 브라우저 저장소는 화면을 그린 뒤에만 읽을 수 있다 (서버 렌더와 어긋나지 않게)
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 계정이 바뀌면 그 계정의 작업함으로 바꾼다
    setItems(owner ? listWork(owner) : null);
  }, [owner]);

  return (
    <div className={PAGE}>
      <PageHeader
        title="내 작업함"
        desc={`저장한 초안과 결과를 이 브라우저에만 ${KEEP_DAYS}일 남겨요. 공용 컴퓨터에서는 다 쓰고 지워 주세요.`}
      />
      <div className="mt-6">
        {user === undefined && <div className="h-32 animate-pulse rounded-3xl bg-slate-100 motion-reduce:animate-none" />}
        {user === null && <LoginCard />}
        {user && items && items.length === 0 && (
          <div className={`px-6 py-12 text-center ${CARD}`}>
            <p className="text-[16px] font-bold text-slate-950">아직 저장한 작업이 없어요</p>
            <p className="mt-1.5 text-[14px] text-slate-500">
              기획 도우미·문서 검토·회의록 정리 결과에서 &lsquo;작업함에 저장&rsquo;을 눌러요.
            </p>
          </div>
        )}
        {user && items && items.length > 0 && (
          <>
            <ul className={LIST}>
              {items.map((item) => (
                <Item key={item.id} item={item} onDelete={() => owner && setItems(deleteWork(owner, item.id))} />
              ))}
            </ul>
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  if (!owner) return;
                  clearWork(owner);
                  setItems([]);
                }}
                className={`${BTN_SM} ${BTN_GHOST}`}
              >
                모두 지우기
              </button>
            </div>
          </>
        )}
        {user && <MyContributions />}
      </div>
    </div>
  );
}
