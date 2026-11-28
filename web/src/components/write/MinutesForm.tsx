"use client";

// 회의록 정리 (문서 작성의 한 탭): 회의 메모 → 감사 제출용 서식·결정사항·할 일. 이 탭만 서버(AI)를 쓰므로 로그인이 필요하다.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { LoginCard } from "@/components/auth/Account";
import { useAuth } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/chat/parts";
import { Area, Form, INPUT, Output } from "@/components/form/Fields";
import SaveButton from "@/components/workspace/SaveButton";
import ContributeCheck from "@/components/contrib/ContributeCheck";
import { word } from "@/lib/office/download";
import { minutesBlocks } from "@/lib/office/forms";
import { MAX_CHARS, MIN_CHARS, type MinutesResult, minutesChecks, organizeMinutes, todoTopic } from "@/lib/minutes";
import { BTN_MD, BTN_PRIMARY, CARD } from "@/lib/ui";

function MinutesSheet({ result }: { result: MinutesResult }) {
  const m = result.minutes;
  return (
    <div className="mt-4 space-y-4 rounded-2xl bg-white p-4 text-[14px] text-slate-800 ring-1 ring-slate-200 print:p-0 print:ring-0">
      <div>
        <h3 className="text-[17px] font-extrabold text-slate-950">{m.title}</h3>
        <p className="mt-1 text-[13px] text-slate-500">
          {[m.held_on, m.place, m.attendees ? `${m.attendees}명 참석` : ""].filter(Boolean).join(" · ") || "일시·장소를 채워 주세요"}
        </p>
      </div>
      {m.agenda.length > 0 && (
        <ol className="space-y-2">
          {m.agenda.map((a, i) => (
            <li key={i}>
              <p className="font-semibold text-slate-950">
                {i + 1}. {a.title}{" "}
                <span className="ml-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-bold text-slate-600">{a.result}</span>
              </p>
              <p className="mt-0.5 leading-relaxed text-slate-600">{a.discussion}</p>
            </li>
          ))}
        </ol>
      )}
      {m.decisions.length > 0 && (
        <div>
          <p className="text-[12px] font-bold text-slate-500">결정사항</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {m.decisions.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      {m.todos.length > 0 && (
        <div>
          <p className="text-[12px] font-bold text-slate-500">할 일</p>
          <ul className="mt-1 divide-y divide-slate-100">
            {m.todos.map((t, i) => {
              const topic = todoTopic(t);
              return (
                <li key={i} className="flex flex-wrap items-baseline gap-x-2 py-1.5">
                  <span className="min-w-0 flex-1">{t.task}</span>
                  <span className="text-[12px] text-slate-500">{t.owner || "담당 미정"}</span>
                  <span className={`text-[12px] tabular-nums ${t.due ? "text-slate-500" : "text-rose-600"}`}>
                    {t.due ? `~${t.due.slice(5)}` : "기한 없음"}
                  </span>
                  {topic && (
                    <Link
                      href={{ pathname: "/checklist", query: { topic } }}
                      className="text-[12px] font-semibold text-indigo-600 hover:underline print:hidden"
                    >
                      점검표 →
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {m.next_agenda.length > 0 && (
        <p className="text-[13px] text-slate-600">
          <span className="font-bold text-slate-500">다음 회의 · </span>
          {m.next_agenda.join(" · ")}
        </p>
      )}
    </div>
  );
}

export default function MinutesForm({ org = "" }: { org?: string }) {
  const { user } = useAuth();
  const [text, setText] = useState("");
  const [date, setDate] = useState("");
  const [contribute, setContribute] = useState(true); // 기본 허락(운영자 결정 2026-11-28), 해제 가능
  const [state, setState] = useState<{ name: "idle" | "busy"; error?: string } | { name: "done"; result: MinutesResult }>({ name: "idle" });
  const run = useRef(0);

  // 다른 계정으로 바뀌면 이전 계정의 메모·결과를 지운다
  const owner = user ? user.email : null;
  const ownerRef = useRef(owner);
  useEffect(() => {
    if (ownerRef.current !== owner) {
      ownerRef.current = owner;
      run.current += 1;
      setText("");
      setState({ name: "idle" });
    }
  }, [owner]);

  if (user === undefined) return <div className="mt-4 h-48 animate-pulse rounded-3xl bg-slate-100 motion-reduce:animate-none" />;
  if (user === null)
    return (
      <div className="mt-4">
        <LoginCard />
      </div>
    );

  const submit = async () => {
    const id = ++run.current;
    setState({ name: "busy" });
    try {
      const result = await organizeMinutes(text, date || null, contribute);
      if (id === run.current) setState({ name: "done", result });
    } catch (e) {
      if (id === run.current) setState({ name: "idle", error: e instanceof Error ? e.message : "정리하지 못했어요." });
    }
  };
  const tooShort = text.trim().length < MIN_CHARS;

  return (
    <>
      <Form title="회의록 정리">
        <label>
          <span className="text-[12px] font-semibold text-slate-500">회의 날짜 (기한 계산용)</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`mt-1 ${INPUT}`} />
        </label>
        <div className="hidden sm:block" />
        <Area
          label="회의 메모 — 노션·카톡에 적은 그대로 붙여 넣기 (이름은 직책으로 바꿔 정리해요)"
          rows={10}
          value={text}
          placeholder={"2/11 팀장급 회의\n- 버스 3대 → 2대로 줄이기로 함\n- 견적 다시 받기: 재무팀장 2/13까지"}
          onChange={(v) => setText(v.slice(0, MAX_CHARS))}
        />
      </Form>
      <div className="mt-3 print:hidden">
        <ContributeCheck checked={contribute} onChange={setContribute} />
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-3 print:hidden">
        {state.name === "idle" && state.error && <p className="text-[14px] font-semibold text-rose-600">{state.error}</p>}
        <button type="button" disabled={tooShort || state.name === "busy"} onClick={submit} className={`${BTN_MD} ${BTN_PRIMARY}`}>
          {state.name === "busy" ? "정리하고 있어요" : "정리하기"}
        </button>
      </div>
      {state.name === "busy" && (
        <div className={`mt-4 flex items-center justify-center gap-2 px-6 py-10 text-[14px] text-slate-500 ${CARD}`} role="status">
          <Spinner /> 안건·결정사항·할 일을 나누고 있어요 · 10초 안팎
        </div>
      )}
      {state.name === "done" && (
        <Output
          text={state.result.text}
          checks={minutesChecks(state.result.minutes)}
          preview={<MinutesSheet result={state.result} />}
          file={word(`회의록 ${state.result.minutes.held_on ?? ""}`, () => minutesBlocks(state.result.minutes, org))}
          actions={<SaveButton key={state.result.text} kind="minutes" title={state.result.minutes.title} text={state.result.text} />}
        />
      )}
    </>
  );
}
