# horcrux / LAB GENE — 프로그램 구조 문서

> 다른 LLM·개발자가 이 저장소를 처음 볼 때 읽는 문서. 2026-09-25 기준, `frontend` 브랜치 코드를 보고 작성했다.
> 설계 결정의 근거는 `docs/superpowers/specs/`의 스펙 문서들이 원본이다. 이 문서는 그 결과물인 **현재 구조**를 한곳에 모은 지도다.

---

## 1. 무엇을 하는 프로그램인가

wet lab(재료·공정·화학) 연구실의 **실험 기록과 문제 진단 도구**. CLI 이름은 `horcrux`, 웹 UI 이름은 **LAB GENE**.

1. 연구원이 실험 로그를 **자연어**로 입력한다.
2. LLM이 로그를 구조화한다(장비, 재료, 공정변수, 결과, 증상 등). 연구실이 필수로 정한 항목이 빠져 있으면 **재질문 루프**로 채운다.
3. 결과를 **마크다운 파일 1개**로 저장한다. 옵시디언에서 그대로 열린다.
4. 저장할 때마다 LLM이 기록들을 **위키 아티클**(장비별·재료별·실패 모드별)로 편찬한다. 재질문 이력에서 **연구실 관례**도 학습한다.
5. 문제가 생기면 자연어로 질문한다. 과거 기록과 위키를 근거로 진단을 보조하고, 근거가 어디서 왔는지 표시한다.

캡스톤 프로젝트이며, 연구실 1~2곳에서 파일럿을 목표로 한다. **보안보다 동작하는 프로토타입이 우선**이다.

---

## 2. 핵심 설계 원칙

| 원칙 | 내용 |
|---|---|
| **md 파일이 유일한 진실** | 실험 1건 = md 1개(YAML frontmatter = 구조화 데이터, 본문 = 원문 로그). 실험 데이터용 DB·검색 인덱스는 없다. |
| **DB는 사람·권한용** | 배포 모드에서만 Supabase Postgres를 쓴다. 저장 대상은 연구실, 멤버, 사용량, 암호화된 LLM 토큰이다. 실험 기록은 절대 DB에 넣지 않는다. |
| **LLM 어댑터 격리** | LLM을 어떻게 호출하는지는 `llm.py`만 안다. 기본은 로컬 CLI 서브프로세스(구독 기반, API 키 불필요)다. |
| **의미 판단은 LLM, 게이트 판단은 코드** | 필수 항목이 기재됐는지 의미로 매칭하는 일은 LLM이 한다. 재질문을 할지는 코드가 설정과 대조해 결정한다. LLM이 없는 이름을 지어내면 코드가 걸러낸다. |
| **로컬 모드 무변경** | `SUPABASE_URL`이 없으면 인증 없이 단일 볼트로 동작한다. 배포 기능은 전부 옵트인이다. |
| **검색은 LLM-select** | 벡터 검색 없이, 전체 레코드 카탈로그를 LLM에 주고 관련 항목을 고르게 한다. 연구실당 수백 건 규모를 가정한다. |

---

## 3. 저장소 레이아웃

```
horcrux/
├─ src/horcrux/          # 파이썬 백엔드 (CLI + FastAPI 서버)
├─ web/                  # React 프론트엔드 (LAB GENE)
│  ├─ src/
│  └─ dist/              # 빌드 산출물 — 커밋에 포함 (사용자 PC에 Node 불필요)
├─ tests/                # pytest (LLM 호출은 전부 monkeypatch)
├─ db/schema.sql         # Supabase 테이블 3개 (배포 모드)
├─ docs/
│  ├─ ARCHITECTURE.md    # 이 문서
│  ├─ deploy-checklist.md  # Supabase·구글 OAuth·Railway 설정 절차
│  └─ superpowers/specs|plans/  # 기능별 설계 스펙·구현 계획 (날짜순)
├─ example-vault/        # 예시 볼트
├─ Dockerfile            # 배포 이미지 (Railway 대상)
├─ pyproject.toml
└─ AGENTS.md             # MVP 시점 에이전트 지침 (일부 조항은 현재와 다름 — §12 참고)
```

---

## 4. 데이터 모델

### 4.1 볼트 디렉터리

로컬 모드에서는 볼트가 하나(`HORCRUX_VAULT`)다. 배포 모드에서는 **연구실마다 볼트가 하나씩**이며 `DATA_DIR/vaults/<lab_id>/`에 있다.

```
<vault>/
├─ config.yaml              # 재질문 게이트 설정 (required_fields, required_parameters)
├─ raw/experiments/*.md     # 실험 레코드 (1건 = 1파일)
└─ wiki/
   ├─ equipment/*.md        # 장비별 아티클
   ├─ materials/*.md        # 재료별 아티클
   ├─ failure-modes/*.md    # "{실험유형}-{증상}" 아티클 (예: 박막증착-값낮음)
   ├─ _index.md             # 위키 색인 (자동 재생성)
   ├─ _absorb_log.json      # 이미 편찬한 레코드 id 목록
   └─ _관례.md               # 재질문 이력에서 편찬한 연구실 관례 (파싱 프롬프트에 주입됨)
```

### 4.2 실험 레코드 md (`records.py: ExperimentRecord`)

파일명과 id는 `{날짜}_{실험유형 slug}-{3자리 순번}` 형식이다. 예: `2026-08-11_박막-증착-002.md`

```yaml
---
id: 2026-08-11_박막-증착-002
date: '2026-08-11'
title: HfO2 증착 두께 편차        # AI가 지은 6~15자 제목 (구 기록엔 빈 값)
experiment_type: 박막 증착
objective: 10nm 균일막 증착
equipment: [ALD-02]
materials: [TEMAH, 오존]
parameters:
- {name: 챔버 온도, value: 250 °C, controllable: true}
results: 가장자리 두께가 중앙보다 15% 얇음
symptom: {category: unstable, description: 두께 불균일}   # low_value|unstable|abnormal|none
suspected_causes:
- {cause: 오존 유량 부족, status: unconfirmed}            # unconfirmed|confirmed|rejected
actions_taken: [오존 유량 50→80 sccm]
notes: ''                                                  # 특이사항
references:                                                # 참고문헌
- {type: paper, title: '...', url: 'https://doi.org/...', record_id: ''}   # paper|link|record
resolution: {resolved: false, actual_cause: null, note: ''}
followup_of: null          # 후속 실험이면 기준 레코드 id
needs_review: false        # 파싱 실패로 원문만 저장된 레코드
---

## 원문 로그
(사용자가 입력한 원문 + 재질문 답변이 "[추가 답변]"으로 누적)

## 정리
(LLM 요약 2~4문장)

## 재질문
- Q: 공정변수 '챔버 온도'의 단위를 알려주세요.
  A: 섭씨
```

`## 재질문` 섹션은 관례 학습의 입력 데이터다. frontmatter가 아니라 본문에 둔 이유는, 위키·관례를 편찬하는 LLM이 레코드 파일을 통째로 읽기 때문이다.

### 4.3 볼트 설정 `config.yaml`

```yaml
required_fields: [objective, parameters, results, symptom, actions_taken, notes]  # 생략 시 이 6개 전부
required_parameters: [챔버 온도, 압력]   # 연구실이 반드시 기록해야 하는 공정변수
```

### 4.4 Supabase 테이블 (배포 모드, `db/schema.sql`)

| 테이블 | 주요 컬럼 | 용도 |
|---|---|---|
| `labs` | id, name, invite_code, llm_mode(`central`\|`own`), llm_provider, llm_credential(Fernet 암호문), daily_llm_limit(기본 200) | 연구실 |
| `lab_members` | lab_id, user_id, role(`admin`\|`member`) | 소속 (사용자 1명 = 연구실 1개) |
| `llm_usage` | lab_id, day, count | 일일 LLM 호출 카운트 |

사용자 계정 자체는 Supabase Auth(구글 로그인 전용)가 관리한다. Storage 버킷 `vault-backups`에는 볼트 zip 백업이 올라간다.

---

## 5. 백엔드 모듈 (`src/horcrux/`)

| 파일 | 책임 | 핵심 함수 |
|---|---|---|
| `config.py` | 프로그램 설정, 볼트 게이트 설정 | `Config(vault, provider, model, api_key, extra_env)`, `load_config()`, `load_vault_config(vault)` |
| `records.py` | 레코드 모델, md 읽기·쓰기 | `ExperimentRecord`, `save_record(vault, rec, raw, summary, qa)`, `load_record`, `write_md`/`read_md`, `record_path`(경로 이탈 방어), `update_resolution` |
| `llm.py` | **LLM 호출의 유일한 지점** | `generate(cfg, system, user) -> str`, `generate_parsed(cfg, system, user, Schema)` |
| `ingest.py` | 로그 구조화, 재질문 목록 생성 | `parse_log(cfg, text, vcfg)`, `missing_required(parsed, vcfg) -> list[질문]`, `to_record`, `save_unparsed` |
| `absorb.py` | 위키 편찬, 관례 편찬 | `run_absorb(cfg)`, `compile_conventions(cfg, texts)` |
| `retrieval.py` | LLM-select 검색 | `retrieve(cfg, query, top_k=3)` |
| `diagnose.py` | 문제 진단 답변 | `diagnose_data(cfg, text) -> {answer, evidence, records, wiki}` |
| `feedback.py` | 해결 여부·실제 원인 기록 | `run_feedback(cfg, id, resolved, cause, note)` |
| `seed.py` | 합성 데모 데이터 | `run_seed(cfg, n)` |
| `server.py` | FastAPI 웹 서버, 배포 모드 | `create_app(cfg, deploy)`, `run_serve()` |
| `auth.py` | Supabase JWT 검증 | `verify_token(token, secret, jwks_url) -> user_id` |
| `labs.py` | Supabase 연구실 DB 접근 | `LabsDB`: create/join/lab_for_user/settings/credential/usage/members |
| `backup.py` | 볼트 일일 백업 | `start_backup_thread(deploy)` |
| `cli.py` | CLI 진입점 | `horcrux log\|ask\|absorb\|feedback\|seed\|serve\|init` |

### 5.1 LLM 어댑터 (`llm.py`)

| provider | 호출 방식 | 인증 |
|---|---|---|
| `claude` (기본) | `claude -p` (프롬프트는 stdin) | CLI 로그인, 또는 `CLAUDE_CODE_OAUTH_TOKEN` env (연구실 장기 토큰) |
| `codex` | `codex exec - --skip-git-repo-check --ephemeral --sandbox read-only -o <파일>` | CLI 로그인, 또는 `OPENAI_API_KEY` |
| `gemini` | `gemini` (stdin) | CLI 로그인, 또는 `GEMINI_API_KEY` |
| `api` | Anthropic SDK 직접 호출 | `cfg.api_key` 또는 `ANTHROPIC_API_KEY` |

- 구조화 출력: JSON 스키마를 프롬프트에 넣고, 응답에서 JSON을 추출해 pydantic으로 검증한다. 실패하면 어댑터가 1회 재생성한다.
- 타임아웃은 300초다. Windows에서는 `taskkill /T`로 프로세스 트리 전체를 종료한다.
- 연구실 크레덴셜(`extra_env`)이 있으면 중앙 `ANTHROPIC_API_KEY`는 서브프로세스에 상속시키지 않는다. 연구실 호출이 중앙 키로 과금되는 것을 막기 위해서다.

---

## 6. 핵심 흐름

### 6.1 실험 기록 (재질문 루프 → 저장 → 편찬)

```
[웹] 홈에서 로그 입력 → 세션 생성(localStorage) → /log/:sid
  └ POST /api/parse ── parse_log: PARSE_SYSTEM
                        + [연구실 필수 파라미터 목록] (config.yaml)
                        + [연구실 관례] (wiki/_관례.md, 있을 때만)
                     ── missing_required → gaps(재질문 문장 목록)
[웹] useLogLoop: gaps를 하나씩 질문 (칩: "건너뛰기", 증상이면 "문제 없음")
  → 답변을 로컬에 모았다가 전부 끝나면 원문에 "[추가 답변]"으로 붙여 재파싱
  → 재파싱 최대 3라운드. 질문이 끝났거나 라운드를 소진하면 저장 가능
[웹] /preview/:sid — 파싱 결과를 사람이 수정
  └ POST /api/records {text, parsed, followup_of, qa}
        ├ 사용량 체크 (배포 모드)
        ├ 멱등: 60초 안에 같은 내용이면 새로 만들지 않고 기존 id 반환
        ├ to_record → save_record (본문에 ## 재질문 기록)
        └ 백그라운드 run_absorb:
             새 레코드 → 장비·재료·실패모드별 아티클을 LLM이 다시 씀
             → compile_conventions: 재질문 이력 → wiki/_관례.md 갱신
             → _absorb_log.json, _index.md 갱신
```

- **관례 학습 루프**: 재질문 답변이 `## 재질문`에 쌓인다 → 관례 문서로 편찬된다 → 다음 파싱 프롬프트에 주입된다 → 같은 패턴은 재질문하지 않는다. 모델 파인튜닝이 아니라 컨텍스트(md 문서)를 학습시키는 방식이다. 관례는 옵시디언에서 사람이 직접 고칠 수 있다.
- 파싱이 반복해서 실패하면 `POST /api/records/raw`로 원문만 저장한다(`needs_review: true`). 이런 레코드는 편찬에서 제외된다.

### 6.2 문제 질문 (`/ask/:sid`)

```
POST /api/ask → retrieve: 전체 레코드 카탈로그(한 줄 요약 + 해결 상태) + 위키 목록을 LLM에 넘겨 관련 항목 선택
             → diagnose_data: 선택된 사례·위키 원문을 근거로 답변 (유사 사례 → 원인 후보 → 확인 순서)
             → evidence 라벨: records(기록 근거) | wiki(위키만) | none(일반 지식)
```

### 6.3 후속 실험·피드백

- **후속 실험** (`/followup/:sid`): 기준 레코드를 옆에 띄우고 파라미터 차이(DiffPanel)를 보여주면서 같은 재질문 루프를 돈다. 저장 시 `followup_of`가 기록된다. 미리보기에서 기준 실험의 원인을 "확인됨"으로 갱신할 수 있다.
- **피드백** (`POST /api/feedback`): 해결 여부와 실제 원인을 기록한다. 원인 후보들은 confirmed/rejected로 정리되고, 새 원인이면 추가된다. 확인된 원인은 검색 우선순위와 그래프 노드에 반영된다.

---

## 7. HTTP API (`server.py`)

인증 열에서 `lab`은 배포 모드일 때 Bearer 토큰과 소속 연구실이 필요하다는 뜻이다(없으면 401/403). 로컬 모드에서는 모두 인증이 없다.

| 메서드·경로 | 인증 | 사용량 카운트 | 설명 |
|---|---|---|---|
| `GET /api/auth-config` | 없음 | | 프론트 부팅용. `{deploy, supabase_url, supabase_anon_key}` |
| `GET /api/config` | lab | | `{required_fields, required_parameters, provider, vault}` |
| `POST /api/parse` | lab | ✔ | `{text}` → `{parsed, gaps}` |
| `POST /api/records` | lab | ✔ | 저장 (멱등 60초). `{text, parsed, followup_of, qa}` → `{id, path}` |
| `POST /api/records/raw` | lab | | 원문만 저장 (needs_review) |
| `GET /api/records` | lab | | 메타 목록 (`_META_KEYS`만, id 내림차순) |
| `GET /api/records/{id}` | lab | | `{record, body}` |
| `PUT /api/records/{id}` | lab | | 노트 편집: 구조화 필드 부분 갱신 + `body`. id·date·resolution·references·followup_of는 제외 |
| `PUT /api/records/{id}/references` | lab | | 참고문헌 전체 교체 |
| `POST /api/feedback` | lab | | 해결 여부·원인 |
| `POST /api/ask` | lab | ✔ | 진단 |
| `POST /api/labs` | 로그인 | | 연구실 생성 (생성자가 admin) |
| `POST /api/labs/join` | 로그인 | | 초대 코드로 합류 |
| `GET /api/labs/me` | 로그인 | | `{lab, role, usage_today, members?(admin만)}`. 소속이 없으면 lab=null |
| `PUT /api/labs/settings` | admin | | name, llm_mode, llm_provider, llm_credential, rotate_invite |
| `/` (정적) | 없음 | | `web/dist` 서빙 (`HORCRUX_WEB_DIST`로 경로 변경 가능) |

- 연구실 객체는 화이트리스트로만 내보낸다(`_lab_out`). `llm_credential`은 어떤 응답에도 나가지 않고, `invite_code`는 admin에게만 나간다.
- **일일 상한(`daily_llm_limit`)은 API로 바꿀 수 없다.** 서비스 운영자가 Supabase 테이블 편집기에서 직접 정한다. 연구실이 자기 상한을 올려 중앙 키 비용이 새는 것을 막기 위해서다.

---

## 8. 배포 모드 (멀티 연구실)

`SUPABASE_URL` 환경변수가 있으면 켜진다.

### 8.1 요청 처리 파이프라인

```
Authorization: Bearer <Supabase JWT>
  → verify_token: 헤더의 alg가 HS256이면 SUPABASE_JWT_SECRET,
                  ES256/RS256이면 프로젝트 JWKS 공개 키로 검증
                  (iat 검사 끔, leeway 60초 — 연구실 PC의 시계 오차 대응)
  → sub = user_id → LabsDB.lab_for_user → AuthCtx(user_id, lab, role)
  → require_lab: 소속이 없으면 403
  → lab_cfg: 볼트 = DATA_DIR/vaults/<lab_id>, LLM 설정은 아래 표
  → lab_lock: 연구실별 쓰기 락
  → check_usage: llm_usage를 +1, 상한을 넘으면 429
```

### 8.2 연구실 LLM 모드 (비용이 누구에게 과금되는가)

| llm_mode / provider | 실행 | 과금 |
|---|---|---|
| `central` | Anthropic API (`ANTHROPIC_API_KEY`) | 서비스 운영자 |
| `own` / `claude` | `claude -p` + `CLAUDE_CODE_OAUTH_TOKEN` (연구실이 `claude setup-token`으로 발급해 등록) | 연구실의 Claude 구독 |
| `own` / `api` | Anthropic API + 연구실 키 | 연구실 |
| `own` / `codex` | codex CLI. 키가 있으면 `OPENAI_API_KEY`, 없으면 서버 머신의 codex 로그인 | 연구실 |
| `own` / `gemini` | gemini CLI. 키가 있으면 `GEMINI_API_KEY`, 없으면 서버 머신의 gemini 로그인 | 연구실 |

클라우드(Railway)에는 "서버 머신 로그인"이 없다. 그래서 codex·gemini를 클라우드에서 쓰려면 키 등록이 필요하다. Claude 장기 토큰은 특정 기계에 묶이지 않아 클라우드에서도 구독으로 동작한다. 크레덴셜은 `CRED_ENCRYPTION_KEY`(Fernet)로 암호화해 DB에 저장한다.

### 8.3 환경변수

| 변수 | 모드 | 용도 |
|---|---|---|
| `HORCRUX_VAULT` / `HORCRUX_PROVIDER` / `HORCRUX_MODEL` | 로컬 | 볼트 경로, provider, 모델 (`~/.horcrux/config.yaml`보다 우선) |
| `SUPABASE_URL` | 배포 | 이 값이 있으면 배포 모드 |
| `SUPABASE_ANON_KEY` | 배포 | 공개 키, `/api/auth-config`로 프론트에 전달 |
| `SUPABASE_SERVICE_KEY` | 배포 | 서버 전용 DB 접근 |
| `SUPABASE_JWT_SECRET` | 배포 | HS256 토큰 검증 (구형 프로젝트) |
| `CRED_ENCRYPTION_KEY` | 배포 | 연구실 토큰 암호화 키 (잃어버리면 모든 토큰 재등록 필요) |
| `ANTHROPIC_API_KEY` | 배포 | central 모드용 |
| `DATA_DIR` | 배포 | 볼트 루트 (기본 `/data`) |
| `PORT`, `HORCRUX_WEB_DIST` | 공통 | 서버 포트, 정적 파일 경로 |

### 8.4 백업·인프라

- `backup.py`: 기동 60초 후 한 번, 이후 24시간마다 `DATA_DIR/vaults` 전체를 zip으로 묶어 Supabase Storage `vault-backups`에 올린다. 실패해도 서비스에는 영향이 없다.
- `Dockerfile`: python:3.12-slim + Node 20 + claude/codex/gemini CLI + `pip install .[web,deploy]`. `/data` 볼륨 마운트가 필수이며, 없으면 재배포 때 볼트가 사라진다.
- 배포 대상은 Railway다. 설정 절차는 `docs/deploy-checklist.md`에 있다.

---

## 9. 프론트엔드 (`web/src/`)

스택: React 18 + TypeScript + Vite + Tailwind v4 + vitest. 주요 라이브러리는 react-router-dom(**HashRouter**), @supabase/supabase-js, react-force-graph-2d, lucide-react.

### 9.1 앱 골격

```
main.tsx: ErrorBoundary (렌더 에러 시 흰 화면 대신 복구 버튼)
└ App.tsx: HashRouter
   └ AuthProvider (auth.tsx)       — GET /api/auth-config로 local/deploy 판별
      └ Gate                       — resolveRoute(mode, session, lab)
         │   loading → 로딩 / login → <Login> / onboarding → <Onboarding> / app ↓
         └ NavProvider (nav.tsx)   — 모바일 드로어 상태
            └ Sidebar + <Routes>
```

- **Gate**는 라우트가 아니라 앱 셸을 통째로 대체한다. 어떤 해시 경로로 들어와도 로그인·온보딩이 똑같이 걸린다.
- 구글 OAuth는 supabase-js의 **PKCE**(`flowType: "pkce"`)를 쓴다. 복귀가 `?code=` 쿼리로 오기 때문에 HashRouter와 충돌하지 않는다. implicit 방식은 토큰이 `#`로 오는데, HashRouter가 그 해시를 덮어써서 로그인 루프가 생긴다.

### 9.2 라우트·페이지

| 경로 | 페이지 | 역할 |
|---|---|---|
| `/` | Home | 입력창 (실험 기록 / 문제 질문 전환), 미완료 기록 이어쓰기 |
| `/log/:sid` | LogChat | 채팅 + 구조 패널 (재질문 루프) |
| `/followup/:sid` | FollowUp | 기준 실험 + 차이(DiffPanel) + 채팅 + 구조 패널 |
| `/preview/:sid` | Preview | 저장 전 필드 편집 → 저장 |
| `/ask/:sid` | Ask | 진단 채팅 + 유사 사례 패널 + 근거 라벨 배너 |
| `/notes`, `/notes/:id` | Notes | 목록·상세 (마스터-디테일), ✏ 편집 모드(필드 + 본문 md), 참고문헌, 피드백, 후속 실험 시작 |
| `/graph` | Graph | 실험·장비·재료·원인 노드 그래프. 호버/선택 시 연결 노드 하이라이트, 모바일은 바텀 시트 |
| `/settings` | Settings | (admin) 연구실 이름, 오늘 사용량 게이지, 초대 코드 재발급, 멤버 목록, LLM 모드·provider·크레덴셜(입력 전용) |

### 9.3 주요 모듈

| 파일 | 역할 |
|---|---|
| `api.ts` | `http()` 래퍼 (Bearer 자동 첨부, 401이면 로그아웃) + `api.*` 메서드 전체 |
| `auth.tsx` | AuthProvider, `useAuth()` → `{mode, session, me, refreshLab, signIn, signOut}`, `resolveRoute` |
| `store.ts` | **대화 세션은 브라우저 localStorage에만 있다** (키 `labgene.sessions.v1`). 서버·기기 간 동기화 없음. 고정(pinned) 세션이 먼저 정렬된다 |
| `useLogLoop.ts` | 재질문 루프 상태기계 (parse → 질문 → 답 누적 → 재파싱, 최대 3라운드). 되감기(rewind)·포크(fork)는 발화 직전 스냅샷(`Session.history`) 기반 |
| `graph.ts` | `buildGraph(records)`: 레코드 메타에서 노드·엣지를 만든다 (참고문헌의 record 링크, followup_of 포함) |
| `refs.ts` | DOI 정규화, Crossref 제목 조회 |
| `nav.tsx` | 반응형: md(768px) 미만이면 MobileBar(햄버거) + MobileTabs |
| `types.ts` | 백엔드 응답 타입 + Session·ChatMsg·ConvoSnapshot |

컴포넌트: `ChatPane`(메시지, 선택 칩, ↩ 되감기·⑂ 포크 아이콘, 한글 IME Enter 가드), `StructurePanel`(필수 항목 게이지 — 단위 재질문은 `gaugeGaps`로 분모에서 제외), `DiffPanel`, `FeedbackModal`, `RecordCard`, `ReferencesSection`, `Sidebar`(세션 목록 오늘/이전 그룹, ⋯ 메뉴로 고정·이름변경·삭제, 데스크톱 검은 레일 하단에 연구실 카드).

제목 표시 우선순위는 모든 화면에서 `title || objective || experiment_type`이다.

---

## 10. 실행·개발

```bash
pip install -e ".[dev,web]"          # 배포 모드까지 쓰면 ".[dev,web,deploy]"
horcrux init                          # ~/.horcrux/config.yaml (볼트 경로, provider)
horcrux serve                         # http://localhost:8765 (web/dist 서빙)
python -m pytest --basetemp=.pytest_tmp -q    # --basetemp 필수 (Windows 권한 문제)
cd web && npm install && npx vitest run && npm run build   # 빌드 결과 dist는 커밋한다
```

CLI 명령: `log`, `ask`, `absorb`(위키 재편찬), `feedback <id> --resolved y|n --cause ...`, `seed -n 6`(합성 데모), `serve`, `init`.

**개발 규칙**

- 모든 파일 I/O에 `encoding="utf-8"`을 명시한다 (Windows cp949 환경).
- 단위 테스트는 LLM을 부르지 않는다. `generate`/`generate_parsed`/`parse_log`/`diagnose_data`는 monkeypatch한다.
- `# ponytail:` 주석은 의도적으로 단순화한 지점과 그 한계를 표시한다. 지우지 않는다.
- 웹 변경 시 `web/dist`를 다시 빌드해 함께 커밋한다.

---

## 11. 알려진 한계 (의도된 단순화)

| 항목 | 현재 | 확장 시점 |
|---|---|---|
| 검색 | 질의마다 전체 카탈로그를 LLM에 전달 | 레코드가 수백 건을 넘으면 색인이나 벡터 계층 추가 |
| 사용량 카운트 | read-then-write라 근사값 | 정확해야 하면 Postgres RPC increment |
| 저장 멱등 | 서버 메모리 캐시라 재시작하면 리셋 | 문제 되면 DB 기반으로 |
| 대화 세션 | 브라우저 localStorage | 기기 간 동기화가 필요하면 서버 저장 |
| 서버 인스턴스 | 1대 (볼륨이 로컬 디스크) | 여러 대로 늘리면 공유 스토리지 필요 |
| 연구실 소속 | 사용자당 1개 | 다중 소속·전환 UI는 미구현 |
| 연구실 생성 | 로그인한 누구나 가능. 구글 OAuth Testing 모드의 테스트 사용자 목록이 사실상 출입 통제 | 앱 게시 시 생성 코드 등 도입 |

---

## 12. 문서 간 관계와 현재 상태

- **`AGENTS.md`는 MVP(2026-07) 시점 문서**다. "웹 UI·인증·다중 사용자 금지", "환경변수 3개뿐" 같은 조항은 이후 사용자 결정으로 바뀌었다. 웹 UI(08-01), 배포·인증(08-06)이 스펙을 거쳐 도입됐다. 현재 구조는 이 문서와 `docs/superpowers/specs/` 최신 스펙을 따른다. md가 진실이라는 원칙, UTF-8, 테스트 규칙은 그대로 유효하다.
- 기능별 스펙: MVP(07-19) → 배포 패키징(07-22) → 웹 UI(08-01) → 배포·인증·참고문헌(08-06) → UI 배치·관례 학습·제미나이(08-12).
- 브랜치: 최신 코드는 `frontend` 브랜치(작업 워크트리 `.claude/worktrees/web-impl`)에 있다. `main`은 코덱스 provider 커밋까지 반영된 상태다. 다음 단계는 로컬 확인 → `main` 머지 → Railway 배포다.
