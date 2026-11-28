// 회의록 정리 API 클라이언트 (로그인 필요, 입력·결과는 저장하지 않는다 — '개선에 쓰도록 허락'한 경우만 가명 처리본 보관).

import { postJson } from "./http";
import type { MinutesResult } from "./minutes-model";

export * from "./minutes-model";

export const organizeMinutes = (text: string, held_on: string | null, contribute = false) =>
  postJson<MinutesResult>(
    `/api/minutes${contribute ? "?contribute=true" : ""}`,
    { text, held_on },
    "회의록을 정리하지 못했어요. 잠시 후 다시 시도해 주세요.",
  );
