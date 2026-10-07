from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import load_config
from .ingest import run_log


def run_init() -> None:
    from .config import load_config, save_config
    cur = load_config()  # 기존 파일+env 반영값을 기본값으로 보여줌
    print("Horcrux 설정 — 빈 입력은 [현재값] 유지")

    def ask(label: str, cur_val) -> str:
        raw = input(f"{label} [{cur_val or ''}]: ").strip()
        return raw or (str(cur_val) if cur_val else "")

    vault = ask("볼트 절대경로", cur.vault.as_posix())
    provider = ask("LLM provider (claude/gemini/codex)", cur.provider)
    model = ask("모델 (빈 값 = CLI 기본)", cur.model)
    path = save_config({
        "vault": vault, "provider": provider, "model": model or None,
    })
    print(f"저장됨: {path}")
    print("다음: 'horcrux serve' 실행 (LLM CLI 로그인은 README 참조)")


def _utf8_console():
    for stream in (sys.stdout, sys.stdin, sys.stderr):
        try:
            if stream.encoding and stream.encoding.lower() != "utf-8":
                stream.reconfigure(encoding="utf-8")
        except Exception:
            pass  # 콘솔 인코딩 조정 실패는 치명적이지 않음


def _sync_quietly(cfg, record_id: str) -> None:
    """저장·피드백 뒤 그래프 반영. 실패해도 기록은 이미 저장됐으니 경고만 남긴다(absorb와 같은 정책)."""
    from . import kg
    try:
        kg.sync_records(cfg.vault, [record_id])
    except Exception as e:
        print(f"(KG 동기화 실패 — 'horcrux kg rebuild'로 재시도: {e})")


def _print_build(st: dict) -> None:
    if st.get("busy"):
        print("이미 구축 작업이 돌고 있습니다.")
        return
    print(f"질문 {st.get('questions', 0) + st.get('record_questions', 0)}개, 자동 승인 {st.get('auto', 0)}개, "
          f"실패 묶음 {st.get('errors', 0)}개 — 웹의 '검토' 화면에서 답하세요")


def _run_ontology(cfg, action: str, ids: list[str], url: str | None = None, out: str | None = None) -> None:
    from .config import load_vault_config
    from .vocab import active_domain, load_domains, select_domains
    if action in ("pull", "export"):
        from . import ontology_agent, trace
        run = trace.start(cfg.vault, "ontology", f"공통 온톨로지 {action}")
        try:
            if action == "pull":
                r = ontology_agent.pull_common(cfg, url, run)
                print(f"공통 온톨로지 {r['version']} · 용어 {r['terms']}개 (추가 {len(r['added'])}, 삭제 {len(r['removed'])})")
                if r["removed"]:
                    print(f"사라진 id: {', '.join(r['removed'])} — overlay·claims에서 참조하면 손으로 고치세요")
            else:
                print(f"기여 파일: {ontology_agent.export_contribution(cfg, out, run)} — 외부 id를 보완해 PR로 보내세요")
        except Exception:
            trace.finish(cfg.vault, run, "failed")
            raise
        trace.finish(cfg.vault, run)
        return
    if action == "use":
        try:
            notice = select_domains(cfg.vault, ids)
        except ValueError as e:
            raise RuntimeError(str(e)) from None
        print(f"선택한 도메인: {', '.join(ids)}")
        if notice:
            print(notice)
        return
    chosen = set(load_vault_config(cfg.vault).domains)
    reg = load_domains()
    for d in reg["domains"]:
        mark = "*" if d["id"] in chosen else " "
        state = "실제 진행" if d["status"] == "active" else "준비 중"
        print(f"{mark} {d['id']}  {d['name']} ({state})")
    print(f"실제 적재 어휘: {active_domain(reg)['vocabulary']}")


def main(argv: list[str] | None = None) -> None:
    _utf8_console()
    p = argparse.ArgumentParser(prog="horcrux", description="연구실 실험 기록·문제 진단 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("log", help="실험 로그 기록")
    sub.add_parser("ask", help="문제 질의")
    sub.add_parser("absorb", help="위키 아티클 편찬")
    fb = sub.add_parser("feedback", help="해결 여부·실제 원인 기록")
    fb.add_argument("record_id")
    fb.add_argument("--resolved", choices=["y", "n"], required=True)
    fb.add_argument("--cause", default=None, help="확인된 실제 원인")
    fb.add_argument("--note", default="")
    sd = sub.add_parser("seed", help="합성 데모 데이터 생성")
    sd.add_argument("-n", type=int, default=6)
    sv = sub.add_parser("serve", help="웹 UI 서버 (LAB GENE)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    sub.add_parser("init", help="설정 마법사 (~/.horcrux/config.yaml 생성)")
    kgp = sub.add_parser("kg", help="지식 그래프 재구축·상태")
    kgp.add_argument("action", choices=["rebuild", "status", "build"])
    mp = sub.add_parser("manual", help="장비 매뉴얼 PDF를 추가하고 지식 후보를 구축")
    mp.add_argument("action", choices=["add"])
    mp.add_argument("path", help="텍스트 PDF 경로")
    mp.add_argument("--pages", default=None, help="쪽 범위 예: 12-40")
    on = sub.add_parser("ontology", help="연구 도메인 목록·선택, 공통 온톨로지 pull·기여 export")
    on.add_argument("action", choices=["domains", "use", "pull", "export"])
    on.add_argument("ids", nargs="*", help="use: 고를 도메인 id들")
    on.add_argument("--url", default=None, help="pull: 공통 온톨로지 YAML 주소 (기본 GitHub main)")
    on.add_argument("--out", default=None, help="export: 기여 파일 경로")
    args = p.parse_args(argv)
    if args.cmd == "init":
        run_init()  # cfg 로드 전 분기 — 깨진 설정파일도 init으로 복구 가능해야 함
        return
    cfg = load_config()

    try:
        if args.cmd == "log":
            path = run_log(cfg)
            if path:
                from .absorb import run_absorb
                try:
                    n = run_absorb(cfg)
                    print(f"위키 갱신: {n}건")
                except Exception as e:
                    print(f"(위키 편찬 실패 — 'horcrux absorb'로 재시도: {e})")
                if isinstance(path, Path):
                    _sync_quietly(cfg, path.stem)
        elif args.cmd == "ask":
            from .diagnose import run_ask
            run_ask(cfg)
        elif args.cmd == "feedback":
            from .feedback import run_feedback
            print(run_feedback(cfg, args.record_id, args.resolved == "y", args.cause, args.note))
            _sync_quietly(cfg, args.record_id)
        elif args.cmd == "absorb":
            from .absorb import run_absorb
            n = run_absorb(cfg)
            print(f"아티클 갱신: {n}건")
        elif args.cmd == "seed":
            from .seed import run_seed
            run_seed(cfg, args.n)
        elif args.cmd == "manual":
            from . import manual, ontology_agent, trace
            src = Path(args.path)
            run = trace.start(cfg.vault, "manual", src.name)
            try:
                out = manual.add_manual(cfg.vault, src.name, src.read_bytes(), args.pages, run)
            except ValueError as e:
                raise RuntimeError(str(e)) from None
            print(f"문서 {out['doc_id']}" + ("" if out["created"] else " (이미 등록됨)") + " — 지식 구축 중…")
            _print_build(ontology_agent.build(cfg, run_id=run, doc_id=out["doc_id"]))
        elif args.cmd == "kg" and args.action == "build":
            from . import ontology_agent
            _print_build(ontology_agent.build(cfg))
        elif args.cmd == "kg":
            from . import kg
            if args.action == "rebuild":
                out = kg.rebuild(cfg.vault)
                print(f"재구축: 레코드 {out['records']}건, 엣지 {out['edges']}개, "
                      f"미연결 표기 {out['temp']}개, 승인 클레임 {out['claims']}개, 건너뜀 {out['skipped']}건")
            else:
                st = kg.status(cfg.vault)
                print(f"노드 {st['nodes']}개 (미연결 표기 {st['temp']}개), 엣지 {st['edges']}개, "
                      f"마지막 동기화 {st['synced_at'] or '없음'}")
        elif args.cmd == "ontology":
            _run_ontology(cfg, args.action, args.ids, args.url, args.out)
        elif args.cmd == "serve":
            try:
                from .server import run_serve
                run_serve(cfg, args.host, args.port)
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    f"웹 UI 의존성이 없습니다 ({e.name}) — pip install -e \".[web]\" 후 다시 실행하세요"
                ) from None
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
