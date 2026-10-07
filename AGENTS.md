# AGENTS.md — Horcrux 작업 지침

에이전트(Codex 등)가 이 저장소에서 작업할 때 따라야 할 지침이다.

## 프로젝트

**horcrux** — wet lab(재료/공정/화학) 연구실의 실험 기록·문제 진단 CLI.
연구원이 자연어로 실험 로그를 입력하면 LLM이 구조화해 마크다운 볼트(옵시디언 호환)에
저장하고, 문제 질의 시 과거 유사 사례·위키를 검색해 근거와 함께 진단을 보조한다.

- 언어/스택: Python 3.10+, pydantic v2, pyyaml, pytest (src/ 레이아웃). LLM은 로컬 CLI subprocess 호출.
- 현재 상태: **MVP 구현 완료** (Task 1~9 + 최종 리뷰 반영), 온톨로지 KG M1~M4 구현(2026-10-07 — M2~M4는 시연 우선으로
  계획서 없이 진행, 원장 `.superpowers/sdd/m2-m4/progress.md`)

## 진실의 원천 문서

| 문서 | 역할 |
|---|---|
| `docs/superpowers/specs/2026-07-19-horcrux-mvp-design.md` | 승인된 설계 스펙 — 무엇을/왜 |
| `docs/superpowers/plans/2026-07-19-horcrux-mvp.md` | 구현 계획 — 실행 기준. Task 1~9, 태스크별 테스트·구현 코드·커밋 메시지 포함 |
| `docs/superpowers/specs/2026-10-07-ontology-kg-design.md` | 온톨로지 KG 설계 — 구축은 벡터, 질의는 그래프 (MVP 스펙의 검색·인덱스 조항을 개정) |
| `docs/superpowers/plans/2026-10-07-ontology-kg-m1-graph-core.md` | M1 구현 계획 — 어휘·그래프·리서치 에이전트 |

이 파일(AGENTS.md)과 위 문서가 충돌하면 **스펙·계획서가 우선**한다.

## 구현 방법

- 계획서의 **Task 1 → 9 순서대로**, 태스크 안에서는 Step 순서대로 진행한다 (TDD:
  실패하는 테스트 먼저 → 실패 확인 → 구현 → 통과 확인).
- 커밋은 각 태스크 마지막 Step의 git 명령을 그대로 따른다 (Task 1~8은 커밋 1개,
  Task 9는 2개 — seed/README + 예시 볼트). 커밋 메시지 제목은 Step에 명시된 것을 쓰고,
  계획서 Global Constraints의 커밋 트레일러 규칙도 함께 따른다.
- 계획서의 코드 블록은 완성본이다 — 임의로 리팩터링하거나 기능을 추가하지 말 것.
  코드 안의 `# ponytail:` 주석은 의도된 단순화 표시이므로 유지한다.

## 핵심 설계 결정 (요약 — 상세는 스펙)

- **진실은 md와 온톨로지 YAML**: 실험 1건 = `raw/experiments/*.md` 1개 (YAML frontmatter =
  구조화 레코드). 원문 로그는 본문에 그대로 보존. 어휘는 `ontology/{common,overlay,claims}.yaml`.
  `kg.sqlite`는 언제든 `horcrux kg rebuild`로 다시 만드는 파생물이다.
- **질의는 그래프만**: ask는 리서치 에이전트(`research_agent.py`)가 용어 연결 → 그래프 도구 →
  증거 카드 → 답변 → 코드 출처 검증으로 처리한다. 벡터·전문 검색·LLM-select 카탈로그는 질의에 쓰지 않는다.
  벡터는 온톨로지 구축 단계(M2)에서만 쓴다.
- **LLM 어댑터 격리**: `llm.py`만 호출 방식을 안다. API 키 없이 로컬 CLI subprocess —
  provider `claude`(`claude -p`) / `gemini` / `codex`(`codex exec`), 기본 `claude`.
  structured output은 스키마를 프롬프트에 포함해 JSON 출력 지시 → JSON 추출 → pydantic 검증.
- **§2a 하드 게이트**: log의 필수 필드 재질문은 볼트 `config.yaml`이 결정
  (의미 매칭은 LLM, 게이트 판단은 코드).
- **absorb 자동 체이닝**: log 저장 후 자동 실행(실패는 경고만 — 저장 유지), seed 끝에도
  1회. `needs_review` 레코드는 스킵. `horcrux absorb` 수동 명령은 재시도용.
- **ask 흐름**: 사용자에게 되묻지 않는다. 내부 품질 루프만 있다 — 질문 재구성 1회, partial·unseen이면 웹 1회
  (`llm.web_search`, claude CLI는 WebSearch·WebFetch만 연다). 웹 카드는 자동 적재하지 않고 "지식 후보로 보내기"로만 들어간다.
- **온톨로지 구축(M2)**: 매뉴얼 PDF·웹 발췌 → `manual.py` 청킹 → `ontology_agent.py` 추출·게이트·라우터 → `review.py`
  질문 → 사람 승인 → overlay·claims YAML. 단위 테스트는 `generate_parsed`·`embed`·`web_search`·`fetch_text`를 막는다
  (conftest가 웹·원문 확인을 기본으로 막는다).
  근거 라벨은 records(사례) / knowledge(지식만) / web / none과 mode(seen·partial·unseen).
- 환경변수는 3개뿐: `HORCRUX_VAULT`(기본 `example-vault`), `HORCRUX_PROVIDER`, `HORCRUX_MODEL`.
- **서버 배포 모드(옵트인)**: `SUPABASE_URL` 설정 시 `create_app(cfg, deploy=...)`가 Supabase
  JWT 인증을 요구하고 연구실별로 `DATA_DIR/vaults/<lab_id>`에 볼트를 격리한다. 미설정
  (`deploy=None`)이면 기존 로컬 동작과 동일. 상세는
  `docs/superpowers/specs/2026-08-06-deployment-auth-design.md`.

## 테스트 규칙

- 단위 테스트는 **LLM 호출 없이** 통과해야 한다 — LLM 호출(`generate`/`generate_parsed`)은
  전부 monkeypatch. 실제 CLI 호출은 수동 E2E 스모크 1회뿐.
- 실행: `PYTHONPATH=src py -3.13 -m pytest --basetemp=.pytest_tmp -q` (PATH의 python은 다른 프로젝트 것이다)

## 환경 주의

- Windows(cp949) 환경 — **모든 파일 I/O에 `encoding="utf-8"` 명시** (계획서 코드에 반영돼 있음).

## 금지 사항 (설계 개정 없이 추가하지 말 것)

스펙의 YAGNI 목록이 근거다. 특히:

- 질의 단계의 벡터·전문 검색·LLM-select 카탈로그 (구축 단계 임베딩은 2026-10-07 스펙이 허용한다)
- ask에서 사용자에게 되묻는 재질문·증상 하드 분기 (내부 재구성 1회는 스펙이 허용한다)
- 웹 UI, 인증/다중 사용자, 자동 스케줄링, 온프레미스 생성 LLM, 모델 재학습, 실데이터 마이그레이션 도구

## 레이어 소유 경계 (병렬 작업 시)

| 영역 | 소유 파일 |
|---|---|
| 백엔드 (코어) | `src/horcrux/{ingest,diagnose,research_agent,vocab,kg,trace,absorb,feedback,records,llm,config,seed}.py` + 기존 테스트 |
| 공용 접점 | `cli.py`, `pyproject.toml`, `README.md`, `docs/**` |

프론트가 의존하는 백엔드 인터페이스(전체 목록):
`parse_log(cfg, text, vcfg)` · `missing_required(parsed, vcfg)` · `to_record(vault, parsed, date)` ·
`save_record(vault, rec, text, summary)` · `save_unparsed(vault, text, err)` · `load_vault_config(vault)` ·
`diagnose(cfg, text)` · `diagnose_data(cfg, text, run_id=None)` · `run_absorb(cfg)` · `run_feedback(cfg, id, resolved, cause, note) -> str` ·
`run_seed(cfg, n)` · `kg.graph_data(vault)` · `kg.rebuild(vault)` · `trace.get_run(vault, run_id, after)`.
시그니처 변경은 백엔드 먼저 수정 후 프론트가 따라간다 — 같은 파일 동시 수정 금지.
