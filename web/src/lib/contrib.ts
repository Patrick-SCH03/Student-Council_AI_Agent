// 서비스 개선용 자료(선택 동의) — 본인 자료 수 확인·모두 지우기.

import { request } from "./http";

export const fetchMyContributions = () =>
  request<{ count: number }>("/api/contributions/mine", { method: "GET" }, "개선 자료를 불러오지 못했어요.");

export const withdrawContributions = () =>
  request<{ deleted: number }>("/api/contributions/mine", { method: "DELETE" }, "개선 자료를 지우지 못했어요.");
