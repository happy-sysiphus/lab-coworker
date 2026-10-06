# horcrux

연구실 실험 기록·문제 진단 CLI. 실험 로그를 자연어로 입력하면 LLM이 구조화해
마크다운 볼트(옵시디언 호환)에 저장하고, 문제 질의 시 과거 유사 사례를 검색해
근거와 함께 진단을 보조한다.

## 설치

[GitHub Releases](../../releases)에서 받는다. 두 트랙 중 하나:

**트랙 1 — Python 3.10+ 있음**: `horcrux-<버전>-py3-none-any.whl` 다운로드 후

```
pip install horcrux-<버전>-py3-none-any.whl
```

**트랙 2 — Python 없음 (Windows)**: `horcrux.exe` 다운로드, 아무 폴더에 두고 그 폴더에서 실행.
Windows Defender가 차단하면 [추가 정보 → 실행] 또는 [허용]으로 통과 (서명 없는 exe 오탐).

### 설치 후 공통 절차 (순서대로)

1. **LLM CLI 설치·로그인** — 셋 중 하나: `claude`(Claude Code) / `gemini`(Gemini CLI) /
   `codex`(Codex CLI). Horcrux는 API 키 대신 로컬 CLI를 subprocess로 호출한다.
2. **설정 마법사**:

```
horcrux init
```

볼트 절대경로·provider·모델을 물어 `~/.horcrux/config.yaml`에 저장한다.
(환경변수 `HORCRUX_*`가 설정돼 있으면 그게 파일보다 우선.)

3. **실행** — 아래 "웹 UI (LAB GENE)" 참조.

### 개발 설치

```
git clone <repo> && cd horcrux
pip install -e .[dev]
```

검색은 LLM-select: LLM이 레코드·위키 카탈로그를 읽고 유사 사례를 직접 고른다.
임베딩·벡터 인덱스 없이 CLI 로그인만으로 동작한다.

## 사용

```
horcrux seed          # 합성 데모 데이터 생성 + 위키 편찬 (개발용)
horcrux log           # 실험 로그 기록 (부족 정보 되물음, 저장 후 위키 자동 편찬)
horcrux ask           # 문제 질의 (지식 그래프의 사례·원인·관계 근거로 답변)
horcrux absorb        # 위키 재편찬 (log/seed가 자동 실행 — 실패 시 재시도용)
horcrux feedback <id> --resolved y --cause "타겟 산화"   # 결과 피드백
horcrux serve         # 웹 UI (LAB GENE) — http://127.0.0.1:8765
horcrux kg rebuild|status   # 지식 그래프 재구축·상태 (kg.sqlite는 파생물)
horcrux ontology domains|use <id>...   # 연구 도메인 목록·선택 (시연: 실제 어휘는 실험 온톨로지)
```

## 웹 UI (LAB GENE)

    pip install -e ".[web]"
    cd web && npm install && npm run build && cd ..
    horcrux serve

브라우저에서 http://127.0.0.1:8765 접속. 기록/질문/연구노트/실험 피드백/후속 실험을
브라우저에서 수행한다 (CLI와 같은 볼트 공유).
개발 모드: `horcrux serve` + `cd web && npm run dev` (vite가 /api 프록시).

## 연구실 설정 (§2a)

볼트에 `config.yaml`을 두면 기록 시 하드 게이트가 적용된다 (없으면 6개 카테고리 전부 기본):

```
required_fields: [objective, parameters, results, symptom, actions_taken, notes]
required_parameters:
  - 기판 온도
  - 챔버 습도
```

공정변수는 단위 포함이 필수다 — 단위 없이 기록하면 재질문한다 (횟수·비율 등 무차원 값 예외).

## 배포 (Railway + Supabase)

기본은 로컬 단일 볼트 모드로 동작한다. 서버 환경변수 `SUPABASE_URL`이 설정된
경우에만 JWT 인증 + 연구실(멀티테넌시) 모드로 전환된다 (옵트인).

### 1. Supabase 준비

1. [supabase.com](https://supabase.com)에서 새 프로젝트를 생성한다.
2. SQL 에디터에서 `db/schema.sql` 내용을 그대로 실행한다 (labs/lab_members/llm_usage
   테이블 생성 — 파일럿 규모라 마이그레이션 도구 없이 수동 1회 실행).
3. Authentication → Providers에서 Google 로그인을 켠다.
4. Authentication → Settings에서 **legacy JWT secret**을 발급한다
   (`SUPABASE_JWT_SECRET`에 쓴다).

### 2. Railway 배포

1. Railway에서 새 프로젝트를 만들고 GitHub 리포를 연동한다 (푸시 시 `Dockerfile`로
   자동 배포).
2. 볼륨을 추가해 `/data`에 마운트한다 (`DATA_DIR` 기본값과 일치 — 연구실별 볼트가
   이 아래 `vaults/<lab_id>/`로 저장된다).
3. 환경변수를 설정한다:
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — Supabase 프로젝트 URL·service_role 키
   - `SUPABASE_JWT_SECRET` — 위에서 발급한 legacy JWT secret
   - `ANTHROPIC_API_KEY`, `HORCRUX_MODEL` — 중앙 LLM 모드 기본 키·모델명
   - `CRED_ENCRYPTION_KEY` — 연구실 자체 크레덴셜 암호화용 Fernet 키 (생성법 아래)
   - `DATA_DIR` — 볼트 저장 경로 (기본 `/data`, 위 볼륨 마운트 경로와 맞출 것)
   - `HORCRUX_WEB_DIST` — 프론트 빌드 산출물 경로. `Dockerfile`이 `/app/web/dist`로
     이미 설정하므로 Railway에서는 손댈 필요 없다 (미설정 시 소스 체크아웃 상대경로)

`CRED_ENCRYPTION_KEY`는 Fernet 키다:

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. LLM 모드

- **중앙 모드(기본)**: `ANTHROPIC_API_KEY`/`HORCRUX_MODEL`로 가입 즉시 동작하며,
  연구실별 일일 상한(기본 200회)이 적용된다.
- **연구실 자체 크레덴셜(고급)**: 아직 관리자 화면이 없어 운영자가
  `PUT /api/labs/settings`를 대신 호출해 등록한다 — `llm_provider: "claude"` +
  `claude setup-token`으로 발급한 장기 토큰, 또는 `llm_provider: "api"` + Anthropic
  API 키를 `llm_credential`에 담아 보낸다. 서버가 Fernet으로 암호화해 저장한다.

설계 문서: `docs/superpowers/specs/2026-07-19-horcrux-mvp-design.md`,
`docs/superpowers/specs/2026-08-06-deployment-auth-design.md`
