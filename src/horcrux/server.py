from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date as _date
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import kg, manual, ontology_agent, review, trace
from .absorb import run_absorb
from .auth import AuthCtx, verify_token
from .config import Config, load_vault_config
from .diagnose import diagnose_data
from .feedback import run_feedback
from .ingest import ParsedLog, missing_required, parse_log, save_unparsed, to_record
from .labs import LabsDB
from .vocab import active_domain, load_domains, load_vocabulary, select_domains
from .records import (
    Parameter, Reference, SuspectedCause, Symptom,
    list_records, load_record, record_path, save_record, write_md,
)

_META_KEYS = ("id", "date", "title", "experiment_type", "objective", "equipment", "materials",
              "symptom", "resolution", "needs_review", "followup_of", "references")

# 연구실 자체 CLI 크레덴셜의 주입 env — 키가 없으면 서버 머신의 CLI 로그인을 그대로 쓴다
_CLI_KEY_ENV = {"codex": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}


@dataclass
class DeployCtx:
    db: object          # LabsDB (테스트는 FakeDB)
    jwt_secret: str
    data_dir: Path
    jwks_url: str | None = None   # 신형 Supabase(ES256 서명)의 공개 키 목록


def load_deploy_ctx() -> DeployCtx | None:
    url = os.environ.get("SUPABASE_URL")
    if not url:
        return None
    return DeployCtx(
        db=LabsDB(url, os.environ["SUPABASE_SERVICE_KEY"],
                  os.environ["CRED_ENCRYPTION_KEY"]),
        jwt_secret=os.environ["SUPABASE_JWT_SECRET"],
        data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        jwks_url=f"{url}/auth/v1/.well-known/jwks.json",
    )


class ParseIn(BaseModel):
    text: str


class QAPair(BaseModel):
    question: str
    answer: str


class RecordIn(BaseModel):
    text: str
    parsed: ParsedLog
    followup_of: str | None = None
    qa: list[QAPair] = Field(default_factory=list)  # 재질문 이력 — 관례 학습 데이터


class RecordUpdateIn(BaseModel):
    # 연구노트 편집 — None이 아닌 필드만 갱신. id·date·resolution·needs_review·
    # references·followup_of는 제외(불변이거나 전용 경로가 있다).
    title: str | None = None
    experiment_type: str | None = None
    objective: str | None = None
    equipment: list[str] | None = None
    materials: list[str] | None = None
    parameters: list[Parameter] | None = None
    results: str | None = None
    symptom: Symptom | None = None
    suspected_causes: list[SuspectedCause] | None = None
    actions_taken: list[str] | None = None
    notes: str | None = None
    body: str | None = None


class RawIn(BaseModel):
    text: str


class DomainsIn(BaseModel):
    domains: list[str]


class WebSourceIn(BaseModel):
    url: str
    title: str = ""
    quote: str = ""


class BuildIn(BaseModel):
    doc_id: str | None = None


class AnswerIn(BaseModel):
    action: str
    reason_code: str | None = None
    edit: dict | None = None


class BulkIn(BaseModel):
    qids: list[str]


class AskIn(BaseModel):
    text: str
    run_id: str | None = None   # 클라이언트가 만든 실행 id — 대기 중 진행 단계를 읽는 데 쓴다


class FeedbackIn(BaseModel):
    record_id: str
    resolved: bool
    cause: str | None = None
    note: str = ""


class ReferencesIn(BaseModel):
    references: list[Reference]


class LabIn(BaseModel):
    name: str


class JoinIn(BaseModel):
    invite_code: str


class SettingsIn(BaseModel):
    # daily_llm_limit은 일부러 없다 — 일일 상한은 서비스 운영자만 정한다(DB에서 직접).
    # 연구실 관리자가 자기 상한을 올릴 수 있으면 중앙 API 키 비용을 통제할 수 없다.
    name: str | None = None
    llm_mode: str | None = None          # 'central'로 되돌리기
    llm_provider: str | None = None      # own 등록: 'claude' | 'api' | 'codex' | 'gemini'
    llm_credential: str | None = None    # own 등록: 평문 토큰/키 (서버가 암호화). codex·gemini는 선택
    rotate_invite: bool = False


def _sync_quietly(cfg: Config, record_id: str, run_id: str | None, normalize: bool = True,
                  finish: bool = True) -> None:
    """레코드 하나를 그래프에 반영하고 실행 기록을 닫는다. 실패해도 저장은 이미 확정 — 경고만 남긴다.

    normalize=False(피드백)는 정규화 단계를 따로 남기지 않는다 — 워크플로 뷰의 "피드백 → 지식 그래프" 선."""
    try:
        c = kg.sync_records(cfg.vault, [record_id])
        counts = f"엣지 {c['edges']}개, 미연결 표기 {c['temp']}개"
        if normalize:
            trace.event(cfg.vault, run_id, "p2.normalize", "ok", counts, c)
        trace.event(cfg.vault, run_id, "p2.store", "ok", "지식 그래프 반영" if normalize else f"지식 그래프 반영 · {counts}")
        if finish:
            trace.finish(cfg.vault, run_id)
    except Exception as e:
        print(f"(KG 동기화 실패 — 'horcrux kg rebuild'로 재시도: {e})")
        trace.finish(cfg.vault, run_id, "failed")


def _after_save(cfg: Config, lock: threading.Lock, record_id: str, run_id: str | None, budget=None) -> None:
    try:
        with lock:
            n = run_absorb(cfg)
        trace.event(cfg.vault, run_id, "p1.wiki", "ok", f"위키 아티클 {n}개 갱신")
    except Exception as e:  # 저장은 이미 확정 — absorb 실패는 로그만 (CLI와 동일 정책)
        print(f"(위키 편찬 실패 — 'horcrux absorb'로 재시도: {e})")
        trace.event(cfg.vault, run_id, "p1.wiki", "fail", f"위키 편찬 실패: {e}")
    with lock:
        _sync_quietly(cfg, record_id, run_id, finish=False)
    try:   # 미연결 표기가 있으면 용어 후보 선택 1회 — LLM은 락 밖, 쓰기는 락 안
        ontology_agent.record_candidates(cfg, run_id, lock, budget)
    except Exception as e:
        print(f"(용어 후보 선택 실패 — 승인 화면의 '이어서'로 재시도: {e})")
    trace.finish(cfg.vault, run_id)


def _build_quietly(cfg: Config, lock: threading.Lock, run_id: str, doc_id: str | None, budget=None) -> None:
    try:
        ontology_agent.build(cfg, lock, run_id, doc_id, budget)
    except Exception as e:
        print(f"(지식 구축 실패 — 승인 화면의 '이어서'로 재시도: {e})")


def _meta(rec) -> dict:
    d = rec.model_dump()
    return {k: d[k] for k in _META_KEYS}


def _existing_record(vault: Path, record_id: str) -> Path:
    """볼트 안의 실재 레코드 경로. 없거나 id가 부정하면 404 (트레이스백 노출 금지)."""
    try:
        p = record_path(vault, record_id)
    except ValueError:
        raise HTTPException(404, f"레코드 없음: {record_id}") from None
    if not p.exists():
        raise HTTPException(404, f"레코드 없음: {record_id}")
    return p


def _lab_out(lab: dict | None, role: str | None) -> dict | None:
    """클라이언트에 나가는 연구실 필드 화이트리스트 — llm_credential은 절대 포함하지 않는다."""
    if lab is None:
        return None
    out = {k: lab.get(k) for k in ("id", "name", "llm_mode", "llm_provider", "daily_llm_limit")}
    if role == "admin":
        out["invite_code"] = lab.get("invite_code")
    return out


def create_app(cfg: Config, deploy: DeployCtx | None = None) -> FastAPI:
    app = FastAPI(title="LAB GENE")

    # ponytail: 볼트별 쓰기 락 — 로컬 모드는 키 "local" 하나만 사용 (기존과 동일 동작)
    _locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
    # 저장 멱등 캐시: lab 키 → (내용 해시, 레코드 id, 시각). 클라이언트가 어떤 경로로든
    # 같은 저장을 연발해도 레코드는 하나만 생긴다. 메모리라 재시작 시 리셋 — 허용.
    _last_saves: dict[str, tuple[str, str, float]] = {}

    def get_ctx(authorization: str | None = Header(default=None)) -> AuthCtx | None:
        if deploy is None:
            return None                       # 로컬 모드 — 인증 없음
        if not authorization or not authorization.startswith("Bearer "):
            print("(401: Authorization 헤더 없음)")
            raise HTTPException(401, "로그인이 필요합니다")
        try:
            user_id = verify_token(authorization.removeprefix("Bearer "),
                                   deploy.jwt_secret, deploy.jwks_url)
        except ValueError as e:
            print(f"(401: {e})")   # 파일럿 진단용 — 검증 실패 사유가 없으면 원인 추적 불가
            raise HTTPException(401, "토큰이 유효하지 않습니다")
        found = deploy.db.lab_for_user(user_id)
        if found is None:
            return AuthCtx(user_id=user_id, lab=None, role=None)
        return AuthCtx(user_id=user_id, lab=found[0], role=found[1])

    def require_lab(ctx: AuthCtx | None = Depends(get_ctx)) -> AuthCtx | None:
        if deploy is not None and (ctx is None or ctx.lab is None):
            raise HTTPException(403, "소속 연구실이 없습니다 — 연구실을 만들거나 초대 코드로 합류하세요")
        return ctx

    def lab_cfg(ctx: AuthCtx | None) -> Config:
        if deploy is None or ctx is None:
            return cfg
        lab = ctx.lab
        vault = deploy.data_dir / "vaults" / lab["id"]
        if lab["llm_mode"] == "own":
            cred = deploy.db.get_credential(lab["id"])
            prov = lab.get("llm_provider")
            if prov in _CLI_KEY_ENV:
                # 코덱스·제미나이는 키가 선택 — 없으면 서버 머신의 CLI 로그인을 쓴다
                secret = cred[1] if cred else None
                return replace(cfg, vault=vault, provider=prov,
                               extra_env={_CLI_KEY_ENV[prov]: secret} if secret else None)
            if cred is None:
                raise HTTPException(502, "연구실 LLM 크레덴셜이 없습니다 — 관리자에게 재등록을 요청하세요")
            provider, secret = cred
            if provider == "claude":
                return replace(cfg, vault=vault, provider="claude",
                               extra_env={"CLAUDE_CODE_OAUTH_TOKEN": secret})
            return replace(cfg, vault=vault, provider="api", api_key=secret)
        return replace(cfg, vault=vault, provider="api", api_key=None)  # 중앙 키(env)

    def lab_lock(ctx: AuthCtx | None) -> threading.Lock:
        return _locks[ctx.lab["id"] if (deploy and ctx and ctx.lab) else "local"]

    def build_budget(ctx: AuthCtx | None):
        """구축·후보 선택 LLM 호출마다 사용량을 센다. 한도에 닿으면 문서를 paused로 둔다."""
        if deploy is None or ctx is None:
            return None

        def bump() -> None:
            if not deploy.db.bump_usage(ctx.lab["id"], ctx.lab["daily_llm_limit"]):
                raise ontology_agent.BudgetExceeded("오늘 사용량 한도를 초과했습니다")
        return bump

    def web_budget(ctx: AuthCtx | None):
        """웹 검색은 사용량을 1회 더 센다. 한도에 닿으면 웹 없이 답한다."""
        if deploy is None or ctx is None:
            return None
        return lambda: deploy.db.bump_usage(ctx.lab["id"], ctx.lab["daily_llm_limit"])

    def reviewer(ctx: AuthCtx | None) -> str:
        return ctx.user_id if ctx is not None else "local"

    def check_usage(ctx: AuthCtx | None) -> None:
        if deploy is None or ctx is None:
            return
        if not deploy.db.bump_usage(ctx.lab["id"], ctx.lab["daily_llm_limit"]):
            raise HTTPException(429, "오늘 사용량 한도를 초과했습니다 — 관리자에게 문의하세요")

    @app.post("/api/parse")
    def api_parse(inp: ParseIn, ctx=Depends(require_lab)):
        check_usage(ctx)
        c = lab_cfg(ctx)
        vcfg = load_vault_config(c.vault)
        parsed = parse_log(c, inp.text, vcfg)
        return {"parsed": parsed.model_dump(), "gaps": missing_required(parsed, vcfg)}

    @app.post("/api/records")
    def api_save(inp: RecordIn, bg: BackgroundTasks, ctx=Depends(require_lab)):
        check_usage(ctx)
        c = lab_cfg(ctx)
        today = _date.today().isoformat()
        key = ctx.lab["id"] if (deploy and ctx and ctx.lab) else "local"
        h = hashlib.sha256(
            (inp.text + (inp.followup_of or "") + inp.parsed.model_dump_json()).encode()
        ).hexdigest()
        with lab_lock(ctx):
            last = _last_saves.get(key)
            if last and last[0] == h and time.time() - last[2] < 60:
                return {"id": last[1], "path": "", "run_id": None}  # 동일 내용 재요청 — 기존 레코드로 응답
            rec = to_record(c.vault, inp.parsed, today)
            rec.followup_of = inp.followup_of
            path = save_record(c.vault, rec, inp.text, inp.parsed.summary,
                               [(q.question, q.answer) for q in inp.qa])
            _last_saves[key] = (h, rec.id, time.time())
        run_id = trace.start(c.vault, "record", rec.id)
        trace.event(c.vault, run_id, "p1.parse", "ok", f"구조화 완료, 재질문 {len(inp.qa)}개")
        trace.event(c.vault, run_id, "p1.save", "ok", f"{rec.id} 저장")
        bg.add_task(_after_save, c, lab_lock(ctx), rec.id, run_id, build_budget(ctx))
        return {"id": rec.id, "path": str(path), "run_id": run_id}

    @app.post("/api/records/raw")
    def api_save_raw(inp: RawIn, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        with lab_lock(ctx):
            path = save_unparsed(c.vault, inp.text, "웹에서 파싱 반복 실패")
        return {"id": path.stem, "path": str(path)}

    @app.post("/api/ask")
    def api_ask(inp: AskIn, ctx=Depends(require_lab)):
        check_usage(ctx)
        c = lab_cfg(ctx)
        return diagnose_data(c, inp.text, run_id=inp.run_id, web_ok=web_budget(ctx))

    @app.get("/api/records")
    def api_list(ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        out = []
        for p in list_records(c.vault):
            try:
                rec, _ = load_record(p)
            except Exception:
                continue  # 손상 md 스킵 — 그래프 동기화와 동일 정책
            out.append(_meta(rec))
        out.sort(key=lambda m: m["id"], reverse=True)
        return {"records": out}

    @app.get("/api/records/{record_id}")
    def api_detail(record_id: str, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        rec, body = load_record(_existing_record(c.vault, record_id))
        return {"record": rec.model_dump(), "body": body}

    @app.post("/api/feedback")
    def api_feedback(inp: FeedbackIn, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        _existing_record(c.vault, inp.record_id)
        with lab_lock(ctx):
            msg = run_feedback(c, inp.record_id, inp.resolved, inp.cause, inp.note)
            run_id = trace.start(c.vault, "feedback", inp.record_id)
            trace.event(c.vault, run_id, "fb.feedback", "ok", msg)
            _sync_quietly(c, inp.record_id, run_id, normalize=False)
        return {"message": msg}

    @app.put("/api/records/{record_id}")
    def api_update_record(record_id: str, inp: RecordUpdateIn, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        p = _existing_record(c.vault, record_id)
        with lab_lock(ctx):
            rec, body = load_record(p)
            for f in ("title", "experiment_type", "objective", "equipment", "materials",
                      "parameters", "results", "symptom", "suspected_causes",
                      "actions_taken", "notes"):
                v = getattr(inp, f)
                if v is not None:
                    setattr(rec, f, v)
            if inp.body is not None:
                body = inp.body
            write_md(p, rec.model_dump(), body)
            _sync_quietly(c, record_id, trace.start(c.vault, "record", f"편집 {record_id}"))
        return {"record": rec.model_dump(), "body": body}  # 상세 응답과 동일 형태

    @app.put("/api/records/{record_id}/references")
    def api_put_references(record_id: str, inp: ReferencesIn, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        p = _existing_record(c.vault, record_id)
        with lab_lock(ctx):
            rec, body = load_record(p)
            rec.references = inp.references
            write_md(p, rec.model_dump(), body)  # body 보존 — update_resolution과 동일
        return {"record": _meta(rec)}

    @app.get("/api/kg/graph")
    def api_kg_graph(ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        with lab_lock(ctx):   # 최신화가 그래프를 고칠 수 있다
            return kg.graph_data(c.vault)

    @app.post("/api/kg/rebuild")
    def api_kg_rebuild(ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        with lab_lock(ctx):
            run_id = trace.start(c.vault, "rebuild", "재구축")
            out = kg.rebuild(c.vault)
            trace.event(c.vault, run_id, "p2.store", "ok",
                        f"레코드 {out['records']}건, 엣지 {out['edges']}개, 승인 클레임 {out['claims']}개", out)
            trace.finish(c.vault, run_id)
        return out

    @app.get("/api/ontology/domains")
    def api_domains(ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        reg = load_domains()
        act = active_domain(reg)
        voc = load_vocabulary(c.vault)
        kinds: dict[str, int] = {}
        for t in voc.terms.values():
            kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
        return {"domains": reg["domains"], "ontologies": reg.get("ontologies", {}),
                "selected": load_vault_config(c.vault).domains, "active": act["id"],
                "vocabulary": act.get("vocabulary"),
                "vocab": {"terms": len(voc.terms), "units": len(voc.units), "predicates": len(voc.predicates),
                          "by_kind": kinds}}

    @app.put("/api/ontology/domains")
    def api_set_domains(inp: DomainsIn, ctx=Depends(require_lab)):
        if ctx is not None and ctx.role != "admin":
            raise HTTPException(403, "연구 도메인은 관리자만 바꿀 수 있습니다")
        c = lab_cfg(ctx)
        reg = load_domains()
        names = {d["id"]: d["name"] for d in reg["domains"]}
        with lab_lock(ctx):
            try:
                notice = select_domains(c.vault, inp.domains)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            chosen = load_vault_config(c.vault).domains
            act = active_domain(reg)
            n = len(load_vocabulary(c.vault).terms)
            run_id = trace.start(c.vault, "ontology", "도메인·온톨로지 선택")
            trace.event(c.vault, run_id, "common.select", "ok",
                        "선택: " + ", ".join(names.get(i, i) for i in chosen), {"domains": chosen})
            trace.event(c.vault, run_id, "common.pull", "info" if notice else "ok",
                        f"실제 적재 어휘 {act.get('vocabulary')} · 용어 {n}개" + (" (시연 범위)" if notice else ""),
                        {"vocabulary": act.get("vocabulary"), "terms": n})
            trace.event(c.vault, run_id, "p2.context", "ok", "공통 어휘를 연결 기준과 추출 문맥으로 사용")
            trace.finish(c.vault, run_id)
        return {"domains": chosen, "notice": notice, "run_id": run_id}

    @app.put("/api/manuals/{filename}")
    async def api_manual_upload(filename: str, request: Request, bg: BackgroundTasks, pages: str | None = None,
                                ctx=Depends(require_lab)):
        data = await request.body()
        if not data:
            raise HTTPException(400, "빈 파일입니다")
        c = lab_cfg(ctx)
        run_id = trace.start(c.vault, "manual", filename)
        try:
            out = manual.add_manual(c.vault, filename, data, pages, run_id)
        except ValueError as e:
            trace.event(c.vault, run_id, "p1.text", "fail", str(e))
            trace.finish(c.vault, run_id, "failed")
            raise HTTPException(400, str(e)) from None
        if not out["created"]:
            trace.event(c.vault, run_id, "p1.save", "info", f"이미 등록된 문서 {out['doc_id']} — 남은 청크를 이어서 처리")
        bg.add_task(_build_quietly, c, lab_lock(ctx), run_id, out["doc_id"], build_budget(ctx))
        return {"doc_id": out["doc_id"], "created": out["created"], "run_id": run_id}

    @app.post("/api/kg/web-sources")
    def api_web_source(inp: WebSourceIn, bg: BackgroundTasks, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        run_id = trace.start(c.vault, "web_source", (inp.title or inp.url)[:60])
        try:
            out = manual.add_web_source(c.vault, inp.url, inp.title, inp.quote, run_id)
        except ValueError as e:
            trace.finish(c.vault, run_id, "failed")
            raise HTTPException(400, str(e)) from None
        bg.add_task(_build_quietly, c, lab_lock(ctx), run_id, out["doc_id"], build_budget(ctx))
        return {"doc_id": out["doc_id"], "created": out["created"], "verified": out["verified"], "run_id": run_id}

    @app.post("/api/kg/build")
    def api_kg_build(inp: BuildIn, bg: BackgroundTasks, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        run_id = trace.start(c.vault, "manual", "지식 구축 이어서")
        bg.add_task(_build_quietly, c, lab_lock(ctx), run_id, inp.doc_id, build_budget(ctx))
        return {"run_id": run_id}

    @app.get("/api/kg/status")
    def api_kg_status(ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        st = review.status(c.vault)
        busy = ontology_agent.is_running(c.vault)
        for d in st["docs"]:   # 기동 전에 running으로 남은 문서는 멈춘 것이다 — '이어서'로 재개
            if d["status"] == "running" and not busy:
                d["status"] = "paused"
        return {**st, "building": busy}

    @app.get("/api/kg/questions")
    def api_questions(tab: str | None = None, status: str = "open", ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        if tab == "auto":
            return {"questions": [], "auto": review.auto_items(c.vault)}
        return {"questions": review.list_questions(c.vault, tab, status)}

    @app.post("/api/kg/questions/bulk-accept")
    def api_bulk_accept(inp: BulkIn, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        with lab_lock(ctx):
            return {"answered": review.bulk_accept(c, inp.qids, reviewer(ctx))}

    @app.get("/api/kg/questions/{qid}")
    def api_question(qid: str, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        q = review.get_question(c.vault, qid)
        if q is None:
            raise HTTPException(404, "질문을 찾을 수 없습니다")
        return {**q, "source": review.source_card(c.vault, q)}

    @app.post("/api/kg/questions/{qid}/answer")
    def api_answer(qid: str, inp: AnswerIn, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        with lab_lock(ctx):
            try:
                return review.answer(c, qid, inp.action, inp.reason_code, inp.edit, reviewer(ctx))
            except review.AnswerError as e:
                raise HTTPException(400, str(e)) from None

    @app.post("/api/kg/items/{item_id}/revoke")
    def api_revoke(item_id: str, ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        with lab_lock(ctx):
            try:
                return review.revoke(c, item_id, reviewer(ctx))
            except review.AnswerError as e:
                raise HTTPException(400, str(e)) from None

    @app.get("/api/flow/runs")
    def api_flow_runs(limit: int = 30, ctx=Depends(require_lab)):
        return {"runs": trace.list_runs(lab_cfg(ctx).vault, limit)}

    @app.get("/api/flow/runs/{run_id}")
    def api_flow_run(run_id: str, after: int = 0, ctx=Depends(require_lab)):
        got = trace.get_run(lab_cfg(ctx).vault, run_id, after)
        if got is None:
            raise HTTPException(404, "실행 기록 없음")
        return got

    @app.get("/api/auth-config")
    def api_auth_config():
        # 유일한 무인증 엔드포인트 — 프론트가 로그인 전에 Supabase를 초기화해야 한다.
        # anon key는 브라우저에 노출되는 것이 전제인 공개 값(RLS가 실제 방어).
        return {"deploy": deploy is not None,
                "supabase_url": os.environ.get("SUPABASE_URL"),
                "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY")}

    @app.get("/api/config")
    def api_config(ctx=Depends(require_lab)):
        c = lab_cfg(ctx)
        vcfg = load_vault_config(c.vault)
        return {"required_fields": vcfg.required_fields,
                "required_parameters": vcfg.required_parameters,
                "provider": c.provider, "vault": str(c.vault), "domains": vcfg.domains}

    @app.post("/api/labs")
    def api_lab_create(inp: LabIn, ctx=Depends(get_ctx)):
        if deploy is None:
            raise HTTPException(404)
        if ctx.lab is not None:
            raise HTTPException(409, "이미 소속 연구실이 있습니다")
        lab = deploy.db.create_lab(ctx.user_id, inp.name)
        (deploy.data_dir / "vaults" / lab["id"]).mkdir(parents=True, exist_ok=True)
        return {"lab": _lab_out(lab, "admin"), "role": "admin"}

    @app.post("/api/labs/join")
    def api_lab_join(inp: JoinIn, ctx=Depends(get_ctx)):
        if deploy is None:
            raise HTTPException(404)
        if ctx.lab is not None:
            raise HTTPException(409, "이미 소속 연구실이 있습니다")
        try:
            lab = deploy.db.join_lab(ctx.user_id, inp.invite_code)
        except LookupError:
            raise HTTPException(404, "초대 코드가 올바르지 않습니다")
        return {"lab": _lab_out(lab, "member"), "role": "member"}

    @app.get("/api/labs/me")
    def api_lab_me(ctx=Depends(get_ctx)):
        # require_lab이 아니라 get_ctx — 무소속도 200(lab=null)으로 답해야
        # 프론트가 "온보딩 필요"와 "서버 오류"를 구분한다
        if ctx is None or ctx.lab is None:
            return {"lab": None, "role": None, "usage_today": 0}
        out = {"lab": _lab_out(ctx.lab, ctx.role), "role": ctx.role,
               "usage_today": deploy.db.get_usage(ctx.lab["id"])}
        if ctx.role == "admin":
            out["members"] = deploy.db.list_members(ctx.lab["id"])
        return out

    @app.put("/api/labs/settings")
    def api_lab_settings(inp: SettingsIn, ctx=Depends(require_lab)):
        if deploy is None:
            raise HTTPException(404)
        if ctx.role != "admin":
            raise HTTPException(403, "관리자만 설정을 변경할 수 있습니다")
        if inp.llm_credential and inp.llm_provider:
            deploy.db.set_credential(ctx.lab["id"], inp.llm_provider, inp.llm_credential)
        fields = {}
        if inp.name: fields["name"] = inp.name
        if inp.llm_mode: fields["llm_mode"] = inp.llm_mode
        if inp.llm_provider and not inp.llm_credential:
            # 키 없는 provider 교체(codex 구독 모드) — 이전 provider의 토큰이 남아 있으면
            # 엉뚱한 env로 주입되므로 함께 비운다
            fields["llm_provider"] = inp.llm_provider
            fields["llm_credential"] = None
        if inp.rotate_invite:
            from .labs import new_invite_code
            fields["invite_code"] = new_invite_code()
        if fields:
            deploy.db.update_settings(ctx.lab["id"], fields)
        return {"ok": True}

    # 기본은 소스 체크아웃(-e 설치) 기준 경로. 비편집 설치(Docker)는 HORCRUX_WEB_DIST로 지정
    dist = Path(os.environ.get("HORCRUX_WEB_DIST")
                or Path(__file__).resolve().parents[2] / "web" / "dist")
    if dist.exists():  # 빌드 전엔 API만 (개발은 vite dev + proxy)
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


def run_serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn
    from .backup import start_backup_thread

    deploy = load_deploy_ctx()
    if deploy is not None:
        start_backup_thread(deploy)
    uvicorn.run(create_app(cfg, deploy), host=host, port=port)
