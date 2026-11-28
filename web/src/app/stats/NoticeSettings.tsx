"use client";

// 운영 대시보드: 화면 위 공지 올리기·내리기. 방침·약관을 바꿀 땐 적용 7일(불리하면 30일) 전에 올린다.
// 공고문 사진·PDF를 첨부(끌어 놓기·붙여넣기 포함)하면 AI가 한 줄 공지와 끝나는 날을 써서 바로 올린다.

import { useEffect, useRef, useState } from "react";

import { AuthError, draftNoticeFromFile, fetchStoredNotice, publishNotice, withdrawNotice } from "@/lib/api";
import { todayKst } from "@/lib/format";
import type { Notice } from "@/lib/notice";

import { CARD_SHADOW } from "./parts";

const INPUT = "rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-400";
const ACCEPT = ["image/png", "image/jpeg", "image/webp", "application/pdf"];

export default function NoticeSettings({ onAuthError }: { onAuthError: (e: unknown, fallback: string) => void }) {
  const [current, setCurrent] = useState<Notice | null>(null);
  const [text, setText] = useState("");
  const [href, setHref] = useState("");
  const [until, setUntil] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "draft">("");
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const drafting = useRef(false); // 같은 순간 두 번 놓아도 한 번만 (busy는 다음 렌더에야 바뀐다)

  const show = (n: Notice | null) => {
    setCurrent(n);
    setText(n?.text ?? "");
    setHref(n?.href ?? "");
    setUntil(n?.until ?? "");
  };

  useEffect(() => {
    fetchStoredNotice().then(show, (e) => onAuthError(e, "공지를 불러오지 못했어요."));
  }, [onAuthError]);

  const run = async (kind: "save" | "draft", action: () => Promise<Notice | null>, done: string) => {
    setBusy(kind);
    setMessage(null);
    try {
      show(await action());
      setMessage(done);
    } catch (e) {
      if (e instanceof AuthError) onAuthError(e, "");
      else setMessage(e instanceof Error ? e.message : "처리하지 못했어요.");
    } finally {
      setBusy("");
    }
  };

  // 공고문 → 초안 → 바로 게시. 링크는 비운다(공고문엔 사이트 안 경로가 없다)
  const fromFile = (file: File | null | undefined) => {
    if (!file || busy || drafting.current) return;
    if (!ACCEPT.includes(file.type)) {
      setMessage("공고문 사진(PNG·JPG·WEBP)이나 PDF만 올릴 수 있어요.");
      return;
    }
    drafting.current = true;
    void run(
      "draft",
      async () => {
        const draft = await draftNoticeFromFile(file);
        return publishNotice({ text: draft.text, href: "", until: draft.until ?? "" });
      },
      "공고문을 읽어 공지를 올렸어요. 고칠 곳이 있으면 고쳐서 다시 올려 주세요.",
    ).finally(() => (drafting.current = false));
  };

  const ended = current?.until ? current.until < todayKst() : false;

  return (
    <div
      className={`rounded-2xl border border-slate-200 bg-white p-5 ${CARD_SHADOW}`}
      onPaste={(e) => {
        // 입력칸에 글을 붙일 때(워드·한글은 글과 함께 그림도 싣는다)는 가로채지 않는다
        if ((e.target as HTMLElement).closest("input, textarea") || e.clipboardData.getData("text/plain")) return;
        const file = [...e.clipboardData.files].find((f) => ACCEPT.includes(f.type));
        if (file) {
          e.preventDefault();
          fromFile(file);
        }
      }}
      onDragOver={(e) => {
        if (![...e.dataTransfer.types].includes("Files")) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault(); // 카드 어디에 놓아도 브라우저가 파일을 열지 않게
        setDragging(false);
        fromFile(e.dataTransfer.files[0]);
      }}
    >
      <p className="text-sm font-bold text-slate-800">
        화면 위 공지
        <span className="ml-2 text-xs font-medium text-slate-500">
          {current ? (ended ? "끝난 공지 (화면에 안 보여요)" : "게시 중") : "게시한 공지 없음"}
        </span>
      </p>
      <button
        type="button"
        disabled={!!busy}
        onClick={() => fileRef.current?.click()}
        className={`mt-4 flex w-full flex-col items-center gap-1 rounded-xl border border-dashed px-4 py-4 text-center transition ${
          dragging ? "border-indigo-400 bg-indigo-50" : "border-slate-300 bg-slate-50 hover:border-indigo-300 hover:bg-indigo-50/50"
        } disabled:cursor-wait disabled:opacity-70`}
      >
        <span className="text-sm font-semibold text-slate-700">
          {busy === "draft" ? "공고문을 읽고 있어요..." : "공고문 첨부하면 공지를 자동으로 올려요"}
        </span>
        <span className="text-xs text-slate-500">사진·PDF(3쪽까지)를 고르거나 끌어 놓기, 캡처는 이 카드에서 Ctrl+V · 5MB까지</span>
      </button>
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT.join(",")}
        className="hidden"
        onChange={(e) => {
          fromFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_180px_150px]">
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          내용 (200자)
          <input
            value={text}
            maxLength={200}
            onChange={(e) => setText(e.target.value)}
            className={INPUT}
            placeholder="12월 5일부터 개인정보처리방침이 바뀌어요."
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          링크 (선택)
          <input value={href} onChange={(e) => setHref(e.target.value)} className={INPUT} placeholder="/privacy" />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          끝나는 날 (선택)
          <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={INPUT} />
        </label>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2.5">
        {message && <span className="mr-auto text-xs font-medium text-slate-500">{message}</span>}
        {current && (
          <button
            type="button"
            disabled={!!busy}
            onClick={() => confirm("공지를 내릴까요?") && run("save", async () => (await withdrawNotice(), null), "공지를 내렸어요.")}
            className="rounded-full border border-slate-200 px-4 py-2 text-xs font-medium text-slate-500 transition hover:border-rose-200 hover:text-rose-700"
          >
            내리기
          </button>
        )}
        <button
          type="button"
          disabled={!!busy || !text.trim()}
          onClick={() => run("save", () => publishNotice({ text, href, until }), "공지를 올렸어요. 닫았던 사람에게도 다시 보여요.")}
          className="rounded-full bg-indigo-600 px-5 py-2 text-xs font-bold text-white transition hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-500"
        >
          {busy === "save" ? "처리 중..." : current ? "고쳐서 다시 올리기" : "올리기"}
        </button>
      </div>
    </div>
  );
}
