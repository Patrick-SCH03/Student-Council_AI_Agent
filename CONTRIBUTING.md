# 개발 컨벤션

1인 개발 프로젝트지만, 변경 이력이 그 자체로 문서가 되도록 규칙을 정해 지켰습니다.

## 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/) 형식을 따릅니다.

```
<type>: <무엇을 왜 바꿨는지 한 줄>

<본문 — 배경·원인·해결·검증 결과>
```

| type | 용도 | 예시 |
|---|---|---|
| `feat` | 새 기능 | `feat: 스캔본 PDF를 Gemini 멀티모달로 자동 파싱` |
| `fix` | 버그 수정 | `fix: 신규 문서가 근거로 채택되지 않던 검색 품질 문제 해결` |
| `refactor` | 동작 변화 없는 구조 개선 | `refactor: v2 디렉터리 계층 제거` |
| `design` | UI/UX 변경 | `design: 이모지 제거 및 스트로크 아이콘 기반 디자인 정리` |
| `perf` | 성능·비용 개선 | `perf: 검색 중복 제거 및 컨텍스트 축소로 프롬프트 23% 감축` |
| `docs` | 문서 | `docs: README를 공개 저장소 방문자 대상으로 재작성` |
| `chore` | 설정·의존성 | `chore: gemini-3.6-flash 전환에 따른 기본값·단가 갱신` |

### 본문 작성 원칙

버그 수정은 **원인과 검증 결과를 반드시 남깁니다.** 나중에 같은 문제를 만났을 때
커밋 메시지만 읽고도 판단할 수 있어야 하기 때문입니다.

```
fix: 본문이 이미지인 PDF가 스캔본 판정을 우회하던 문제 해결

- 스캔본 판정을 절대 길이(50자)에서 페이지당 평균(200자) 기준으로 변경
  기존 기준으로는 목차·표지만 텍스트로 있는 문서(18페이지에 851자)가
  판정을 통과해 본문이 통째로 누락됨
- 25-2 총학생회_특별감사_보고서 재색인: 1청크 -> 19청크
```

## 브랜치

- `main` — 배포 브랜치. push 시 Vercel·Railway가 자동 배포합니다.
- 실험적 변경은 브랜치를 파서 PR로 병합합니다.

`main`이 곧 프로덕션이므로, **CI가 통과하지 않은 커밋은 push하지 않습니다.**

## CI

`.github/workflows/ci.yml` — push·PR마다 실행됩니다.

| Job | 내용 |
|---|---|
| **api** | 의존성 설치 → 스모크 테스트 (벡터 스토어 · 그래프 병렬 실행 · 라우팅) |
| **web** | 의존성 설치 → ESLint → 프로덕션 빌드 |

백엔드 스모크 테스트는 **API 키 없이 동작하는 목업 모드**로 실행되므로 CI에 시크릿이 필요 없습니다.

## 로컬 검증

push 전에 아래를 실행합니다.

```bash
# 백엔드
cd api && python smoke_test.py

# 프론트엔드
cd web && npm run lint && npm run build
```

## 릴리스

[SemVer](https://semver.org/lang/ko/)를 따르고, 태그 `vX.Y.Z`와 `api/app/config.py`의 `APP_VERSION`,
`web/package.json`의 `version`을 **함께** 올립니다. 배포본이 어떤 버전인지는
`GET /api/health`의 `version`으로 확인합니다.

| 올리는 자리 | 언제 |
|---|---|
| **MAJOR** | 응답 형식·관리자 API처럼 쓰는 쪽이 바뀌어야 하는 변경 |
| **MINOR** | 기능 추가·동작 변화 (새 검색 방식, 새 방어 계층) |
| **PATCH** | 결함 수정·보안 패치만 |

```bash
git tag -a vX.Y.Z -m "vX.Y.Z — 한 줄 요약"
git push origin vX.Y.Z
gh release create vX.Y.Z --verify-tag --title "vX.Y.Z — 한 줄 요약" --notes-file notes.md
```

문서만 바뀐 커밋은 릴리스하지 않습니다.

## 답변 품질 회귀 테스트

프롬프트나 검색 설정을 바꾼 뒤에는 평가셋을 실행해 품질 저하를 확인합니다.

```bash
cd api
python evaluate.py                          # 로컬 파이프라인
python evaluate.py --url https://<배포주소>  # 배포본
python evaluate.py --case vat-case          # 특정 케이스만
```

`evalset.json`에 질문별 기대치(라우팅·근거 문서·핵심 키워드·위험도·실명 노출 여부)를
정의해 두었습니다. **실제 LLM을 호출하므로 비용이 발생**하며, CI에는 포함하지 않고
품질에 영향을 주는 변경 시에만 수동 실행합니다.

테스트가 실패하면 두 가지를 구분해야 합니다.

- **시스템 문제** — 근거 문서를 못 찾거나 잘못된 답변을 함 → 코드·프롬프트 수정
- **기준 문제** — 답변은 맞는데 기대 문서만 다름 → `evalset.json` 기대치를 수정
