"use client";

// 법령 점검표 아래 '더 물어보기': 점검표에 없는 질문을 하면 법제처 법령에서 조문을 찾아 답하고 원문 링크를 붙인다.
// 이어 묻기(직전 3턴)를 지원하고, 대화는 이 화면에만 두며 서버에 저장하지 않는다.

import { useRef, useState } from "react";

import { Spinner } from "@/components/chat/parts";
import { type LawAnswer, type LawTurn, SAMPLE_QUESTIONS, askLaw } from "@/lib/law";
import { BTN_GHOST, BTN_MD, BTN_PRIMARY, BTN_SM, CARD } from "@/lib/ui";

type Entry = { q: string; res: LawAnswer };

/** 답 글: '확인할 것'·'근거' 줄은 작은 제목, '- ' 줄은 목록으로 */
function AnswerText({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (key: number) => {
    if (bullets.length)
      out.push(
        <ul key={`u${key}`} className="mt-1.5 list-disc space-y-1 pl-5 text-[14px] leading-relaxed text-slate-700">
          {bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>,
      );
    bullets = [];
  };
  text.split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (line.startsWith("- ")) return void bullets.push(line.slice(2));
    flush(i);
    if (!line) return;
    if (/^(확인할 것|근거)\s*:?$/.test(line))
      out.push(
        <p key={i} className="mt-4 text-[13px] font-bold text-slate-950">
          {line.replace(/:$/, "")}
        </p>,
      );
    else
      out.push(
        <p key={i} className="mt-2 text-[14px] leading-relaxed text-slate-800 first:mt-0">
          {line}
        </p>,
      );
  });
  flush(-1);
  return <div>{out}</div>;
}

function AnswerCard({ entry }: { entry: Entry }) {
  const { res } = entry;
  return (
    <li className="space-y-2">
      <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-slate-950 px-4 py-2.5 text-[14px] leading-relaxed text-white">{entry.q}</p>
      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <AnswerText text={res.answer} />
        {res.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {res.citations.map((c, i) => (
              <a
                key={`${c.url}-${i}`}
                href={c.url}
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[12px] font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-950"
              >
                {c.text}
                {c.effective && <span className="text-slate-400"> · {c.effective} 시행</span>} ↗
              </a>
            ))}
          </div>
        )}
        <p className="mt-3 text-[12px] text-slate-500">
          {res.verified ? "인용한 조문은 법제처 원문과 대조했어요." : "조문 대조를 하지 못했어요. 링크에서 원문을 꼭 확인해 주세요."}
        </p>
      </div>
    </li>
  );
}

export default function LawChat({ topic }: { topic: string }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const send = async (question = text) => {
    const q = question.trim();
    if (q.length < 2 || pending) return;
    setPending(q);
    setError(null);
    setText("");
    try {
      const history: LawTurn[] = entries.map((e) => ({ q: e.q, a: e.res.answer }));
      const res = await askLaw(q, topic, history);
      setEntries((prev) => [...prev, { q, res }]);
    } catch (e) {
      setText(q); // 실패하면 적은 질문을 돌려준다
      setError(e instanceof Error ? e.message : "법령을 찾지 못했어요.");
    } finally {
      setPending(null);
    }
  };

  const samples = SAMPLE_QUESTIONS[topic] ?? [];

  return (
    <section className={`mt-4 p-5 sm:p-6 ${CARD}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[18px] font-extrabold tracking-tight text-slate-950">점검표에 없는 걸 물어보세요</h2>
          <p className="mt-1 text-[14px] text-slate-500">법제처 법령에서 조문을 찾아 답하고, 근거 조문 원문 링크를 붙여요.</p>
        </div>
        {entries.length > 0 && !pending && (
          <button type="button" onClick={() => setEntries([])} className={`${BTN_SM} ${BTN_GHOST} shrink-0`}>
            새 대화
          </button>
        )}
      </div>

      {entries.length === 0 && !pending && samples.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {samples.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => void send(s)}
              className="rounded-full bg-slate-100 px-3.5 py-2 text-left text-[13px] font-medium text-slate-700 transition hover:bg-slate-200 hover:text-slate-950"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {(entries.length > 0 || pending) && (
        <ul className="mt-5 space-y-5" aria-live="polite">
          {entries.map((e, i) => (
            <AnswerCard key={i} entry={e} />
          ))}
          {pending && (
            <li className="space-y-2">
              <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-slate-950 px-4 py-2.5 text-[14px] leading-relaxed text-white">{pending}</p>
              <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-[13px] text-slate-600" role="status">
                <Spinner />
                법령을 찾아 조문을 확인하고 있어요. 보통 20~40초 걸려요.
              </div>
            </li>
          )}
        </ul>
      )}

      <form
        className="mt-5"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 focus-within:border-slate-500">
          <textarea
            ref={inputRef}
            value={text}
            maxLength={500}
            rows={2}
            disabled={!!pending}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={entries.length ? "이어서 물어보세요" : "예: 축제에서 외부 공연팀에게 출연료를 주면 세금을 떼야 하나요?"}
            aria-label="법령 질문"
            className="min-h-[44px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px] leading-relaxed text-slate-900 outline-none placeholder:text-slate-400 disabled:text-slate-400"
          />
          <button type="submit" disabled={!!pending || text.trim().length < 2} className={`${BTN_MD} ${BTN_PRIMARY} shrink-0 disabled:bg-slate-200 disabled:text-slate-500`}>
            {pending ? "찾는 중" : "물어보기"}
          </button>
        </div>
        {error && <p className="mt-2 text-[13px] font-medium text-rose-600">{error}</p>}
        <p className="mt-2 text-[12px] text-slate-500">
          참고 정보예요. 세무·법률 자문이 아니니 중요한 결정은 세무서·관할 구청이나 전문가와 확인해요. 학생회 회칙·세칙은 &lsquo;규정 질문&rsquo;에서 물어보세요. 하루 20번까지.
        </p>
      </form>
    </section>
  );
}
