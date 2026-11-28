"use client";

// 문서 검토: 올리기 → 읽어 온 표 확인 → 점검 결과.
// 규정 메모(LLM, 수 초)는 표를 읽자마자 미리 요청해 두어, 사용자가 표를 확인하는 동안 준비된다.

import { useEffect, useRef, useState } from "react";

import { LoginCard } from "@/components/auth/Account";
import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/chat/parts";
import ConfirmTable from "@/components/review/ConfirmTable";
import Report from "@/components/review/Report";
import ContributeCheck from "@/components/contrib/ContributeCheck";
import Upload from "@/components/review/Upload";
import PageHeader from "@/components/shell/PageHeader";
import { type BudgetDoc, type Extracted, type Finding, checkDoc, extractFile, fetchNotes } from "@/lib/review";
import { CARD, PAGE } from "@/lib/ui";

type Step =
  | { name: "upload"; error: string | null }
  | { name: "reading"; file: string }
  | { name: "confirm"; error?: string }
  | { name: "result"; findings: Finding[] };

type NotesState = { state: "loading" | "done" | "error"; notes: Finding[] };

export default function ReviewPage() {
  const { user } = useAuth();
  const [step, setStep] = useState<Step>({ name: "upload", error: null });
  const [extracted, setExtracted] = useState<Extracted | null>(null);
  const [doc, setDoc] = useState<BudgetDoc | null>(null);
  const [checking, setChecking] = useState(false);
  const [contribute, setContribute] = useState(true); // 기본 허락(운영자 결정 2026-11-28), 해제 가능
  const [notes, setNotes] = useState<NotesState>({ state: "loading", notes: [] });
  // 이전 문서의 늦게 도착한 응답이 새 문서 화면을 덮지 않게
  const runRef = useRef(0);

  const reset = () => {
    runRef.current += 1;
    setExtracted(null);
    setDoc(null);
    setChecking(false);
    setNotes({ state: "loading", notes: [] });
    setStep({ name: "upload", error: null });
  };

  const read = async (file: File) => {
    const run = ++runRef.current;
    setStep({ name: "reading", file: file.name });
    try {
      const out = await extractFile(file, contribute);
      if (run !== runRef.current) return;
      setExtracted(out);
      setDoc(out.doc);
      setStep({ name: "confirm" });
      setNotes({ state: "loading", notes: [] });
      fetchNotes(out.doc, out.text, out.source).then(
        (n) => run === runRef.current && setNotes({ state: "done", notes: n }),
        () => run === runRef.current && setNotes({ state: "error", notes: [] }),
      );
    } catch (e) {
      if (run !== runRef.current) return;
      setStep({ name: "upload", error: e instanceof Error ? e.message : "문서를 읽지 못했어요." });
    }
  };

  const confirm = async () => {
    if (!doc || !extracted) return;
    const run = runRef.current;
    setChecking(true);
    setStep({ name: "confirm" }); // 다시 시도하면 지난 오류 안내를 지운다
    try {
      const findings = await checkDoc(doc, extracted.source, extracted.contribution_id);
      if (run === runRef.current) setStep({ name: "result", findings });
    } catch (e) {
      // 고친 표는 그대로 두고 확인 화면에서 다시 시도하게 한다
      if (run === runRef.current) setStep({ name: "confirm", error: e instanceof Error ? e.message : "점검하지 못했어요. 다시 시도해 주세요." });
    } finally {
      if (run === runRef.current) setChecking(false);
    }
  };

  // 로그아웃하거나 다른 계정으로 바뀌면 이전 계정의 문서·결과를 지운다
  const owner = user ? user.email : null;
  const ownerRef = useRef(owner);
  useEffect(() => {
    if (ownerRef.current !== owner) {
      ownerRef.current = owner;
      reset();
    }
  }, [owner]);

  return (
    <div className={PAGE}>
      <PageHeader title="문서 검토" desc="사업계획서·예산안·결산서가 규정에 맞는지 점검해요." />
      <div className="mt-6">
        {user === undefined && <div className="h-48 animate-pulse rounded-3xl bg-slate-100 motion-reduce:animate-none" />}
        {user === null && <LoginCard />}
        {user && step.name === "upload" && (
          <>
            <Upload onFile={read} error={step.error} />
            <div className="mt-3">
              <ContributeCheck checked={contribute} onChange={setContribute} />
            </div>
          </>
        )}
        {user && step.name === "reading" && (
          <div className={`flex flex-col items-center gap-3 px-6 py-12 text-center ${CARD}`} role="status">
            <Spinner className="h-6 w-6" />
            <p className="text-[16px] font-bold text-slate-950">예산표를 읽고 있어요</p>
            <p className="max-w-full truncate text-[13px] text-slate-500">{step.file} · 보통 10~30초, 큰 문서는 1분쯤 걸려요</p>
          </div>
        )}
        {user && step.name === "confirm" && doc && extracted && (
          <>
            {step.error && (
              <p role="alert" className="mb-3 rounded-2xl bg-rose-50 px-4 py-3 text-[14px] font-semibold text-rose-700">
                {step.error}
              </p>
            )}
            {!doc.income.length && !doc.expense.length && (
              <p className="mb-3 rounded-2xl bg-amber-50 px-4 py-3 text-[14px] text-amber-800">
                수입·지출 표를 찾지 못했어요. 예산표가 있는 문서라면 아래 표를 직접 채워 주세요. 그대로 점검하면 원문 점검 결과만 보여요.
              </p>
            )}
            <ConfirmTable doc={doc} onChange={setDoc} onConfirm={confirm} onReset={reset} method={extracted.method} busy={checking} />
          </>
        )}
        {user && step.name === "result" && doc && (
          <Report
            title={doc.title}
            findings={step.findings}
            notes={notes.notes}
            notesState={notes.state}
            onEdit={() => setStep({ name: "confirm" })}
            onReset={reset}
          />
        )}
      </div>
    </div>
  );
}
