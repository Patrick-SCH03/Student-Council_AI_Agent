// 공문 번호 대장 API (로그인 필요). 본문은 보내지 않고 번호·날짜·제목·수신만 남긴다.

import { request } from "./http";

export type LedgerEntry = { id: number; prefix: string; year: number; seq: number; issued_on: string; title: string; recipient: string };
export type Ledger = { entries: LedgerEntry[]; problems: string[] };

const FALLBACK = "번호 대장을 불러오지 못했어요.";
const call = <T>(path: string, init: RequestInit = {}) => request<T>(path, init, FALLBACK);

export const fetchLedger = () => call<Ledger>("/api/ledger");

export const nextNumber = (prefix: string, year: number) =>
  call<{ seq: number; number: string }>(`/api/ledger/next?prefix=${encodeURIComponent(prefix)}&year=${year}`);

export const addEntry = (entry: { prefix: string; issued_on: string; title: string; recipient: string; seq?: number }) =>
  call<Ledger>("/api/ledger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(entry) });

export const deleteEntry = (id: number) => call<Ledger>(`/api/ledger/${id}`, { method: "DELETE" });

export const entryNumber = (e: LedgerEntry) => `${e.prefix}-${e.year}-${String(e.seq).padStart(4, "0")}`;
