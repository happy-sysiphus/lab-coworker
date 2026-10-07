"""하네스 본실험 원장 → horcrux 시연 볼트 레코드.

    PYTHONPATH=src py -3.13 scripts/export_experiment.py --labgene C:/Users/지완/claude/labgene \
        --run pilot-02 --vault demo-vault

가상 실험(run_experiment) 한 건이 레코드 md 한 건이 된다. LLM을 부르지 않는 결정론 변환이다.
같은 에피소드의 실험은 followup_of로 이어져 그래프에서 조건 변화와 결과 변화가 보인다.
--replay는 같은 원장을 워크플로 뷰 "실험 재생" 탭이 읽는 JSON으로 내보낸다. --translate는 질문·답·메모를
llm.py로 한국어 번역한다(이미 번역된 글은 기존 JSON에서 다시 쓴다).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

import yaml
from pydantic import BaseModel

from horcrux.config import load_config
from horcrux.llm import generate_parsed
from horcrux.records import ExperimentRecord, Parameter, Symptom, make_record_id, records_dir, save_record
from horcrux.vocab import active_domain, select_domains

EXPERIMENT_TYPE = "Suzuki-Miyaura coupling"


def load_run(labgene: Path, run: str) -> dict:
    """원장에서 에피소드·행동·관측만 읽는다. 비용·누수 게이트·세션 기록은 읽지 않는다."""
    con = sqlite3.connect(Path(labgene) / "artifacts" / run / "ledger.sqlite")
    con.row_factory = sqlite3.Row
    try:
        episodes = [dict(r) for r in con.execute(
            "select episode_id, condition, task_id, episode_order from episodes order by condition, episode_order")]
        actions = [dict(r) for r in con.execute(
            "select action_id, episode_id, seq, kind, payload_json from actions order by episode_id, seq")]
        observations = {r["action_id"]: json.loads(r["json"]) for r in con.execute(
            "select action_id, json from observations")}
    finally:
        con.close()
    tasks = {}
    for e in episodes:
        if e["task_id"] not in tasks:
            p = Path(labgene) / "configs" / "tasks" / f"{e['task_id']}.yaml"
            tasks[e["task_id"]] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return {"episodes": episodes, "actions": actions, "observations": observations, "tasks": tasks}


def substrates(task: dict) -> list[str]:
    """과제 제목 'Suzuki-Miyaura coupling in flow: A with B'에서 기질 두 개를 꺼낸다."""
    m = re.search(r":\s*(.+?)\s+with\s+(.+)$", task.get("title", ""))
    return [m.group(1).strip(), m.group(2).strip()] if m else []


def reagents(task: dict) -> list[str]:
    problem = task.get("problem", "")
    return [name for name in ("DBU", "THF", "water") if name in problem]


def write_vault(run: dict, vault: Path, date: str, source: str) -> list[str]:
    vault = Path(vault)
    if any(records_dir(vault).glob("*.md")):
        raise SystemExit(f"{records_dir(vault)}에 이미 레코드가 있습니다 — 빈 볼트를 지정하세요")
    ids: list[str] = []
    for ep in run["episodes"]:
        task = run["tasks"][ep["task_id"]]
        targets = {s["metric"]: s["target"] for s in task.get("success", [])}
        prev = None
        for a in run["actions"]:
            if a["episode_id"] != ep["episode_id"] or a["kind"] != "run_experiment":
                continue
            obs = run["observations"].get(a["action_id"])
            if obs is None:
                continue   # 무효 실험 — 관측이 없다
            hyp = json.loads(a["payload_json"]).get("args", {}).get("hypothesis", "")
            p, r = obs["parameters"], obs["results"]
            ok = bool(obs.get("meets_success_criteria"))
            rec = ExperimentRecord(
                id=make_record_id(vault, date, EXPERIMENT_TYPE), date=date,
                title=f"{p['catalyst']} {p['temperature']:g}°C {p['residence_time']:g}s",
                experiment_type=EXPERIMENT_TYPE, objective=task["title"], equipment=["flow reactor"],
                materials=[p["catalyst"], *substrates(task), *reagents(task)],
                parameters=[Parameter(name="temperature", value=f"{p['temperature']:g} °C"),
                            Parameter(name="residence time", value=f"{p['residence_time']:g} s"),
                            Parameter(name="catalyst loading", value=f"{p['catalyst_loading']:g} mol%"),
                            Parameter(name="catalyst", value=str(p["catalyst"]))],
                results=f"yield {r['yield']:.1f} %, TON {r['ton']:.1f}",
                symptom=Symptom(category="none", description="목표 달성") if ok else Symptom(
                    category="low_value",
                    description=f"수율 또는 TON 목표 미달 (목표 수율 {targets.get('yield')} %, TON {targets.get('ton')})"),
                notes=hyp, followup_of=prev)
            raw = f"{hyp}\n\n결과: {rec.results}\n\n출처: {source} {a['action_id']}"
            save_record(vault, rec, raw, f"{rec.title} 조건에서 {rec.results}. {'목표 달성' if ok else '목표 미달'}.")
            ids.append(rec.id)
            prev = rec.id
    select_domains(vault, [active_domain()["id"]])
    return ids


CONDITION_NAMES = {"baseline": "일반 LLM", "product": "LAB GENE"}
BATCH = 20
TRANSLATE_SYSTEM = """연구 실험 기록을 한국어로 번역한다. 화학 용어·물질·촉매 이름·단위·수치는 원문 표기를 그대로 둔다.
입력은 {i, en} 목록이다. 같은 i로 {i, ko}를 돌려준다. 번역만 하고 설명을 덧붙이지 마라."""


class _Item(BaseModel):
    i: int
    ko: str


class Translations(BaseModel):
    items: list[_Item]


Translations.model_rebuild()   # importlib로 읽혀도 _Item을 찾게 한다


def _knowledge(root: Path, cond: str) -> dict:
    """조건별 지식 저장소의 인용 id → (본문, 메타). 저장소가 없으면 빈 사전."""
    p = root / "initial" / cond / "state" / "knowledge.sqlite"
    if not p.exists():
        return {}
    con = sqlite3.connect(p)
    try:
        return {i: (t or "", json.loads(m or "{}")) for i, t, m in con.execute("select id, text, meta from artifacts")}
    finally:
        con.close()


def _cite(arts: dict, cid: str) -> dict:
    text, meta = arts.get(cid, ("", {}))
    src = arts.get(cid.split("#")[0], ("", {}))[1]
    title = src.get("title") or meta.get("title") or (meta.get("header") or "").split(" | ")[0] or cid
    return {"id": cid, "title": title, "excerpt": " ".join(text.split())[:300]}


def _obs_cite(obs: dict, cid: str) -> dict:
    o = obs.get(cid[4:])
    if not o:
        return {"id": cid, "title": "이전 실험 관측", "excerpt": ""}
    p, r = o["parameters"], o["results"]
    return {"id": cid, "title": "이전 실험 관측",
            "excerpt": f"{p['catalyst']} {p['temperature']:g}°C {p['residence_time']:g}s {p['catalyst_loading']:g} mol% "
                       f"→ yield {r['yield']:.1f} %, TON {r['ton']:.1f}"}


def load_replay(labgene: Path, run: str, label: str, date: str) -> dict:
    """원장 → 재생 JSON. 상담·실험처럼 겉으로 보이는 흐름만 담는다(검색 내부·비용·세션 기록은 읽지 않는다)."""
    root = Path(labgene) / "artifacts" / run
    con = sqlite3.connect(root / "ledger.sqlite")
    con.row_factory = sqlite3.Row
    try:
        episodes = [dict(r) for r in con.execute(
            "select episode_id, condition, task_id, episode_order, outcome from episodes order by condition, episode_order")]
        actions = [dict(r) for r in con.execute(
            "select action_id, episode_id, seq, kind, payload_json from actions order by episode_id, seq")]
        obs = {r["action_id"]: json.loads(r["json"]) for r in con.execute("select action_id, json from observations")}
        consults = {r["action_id"]: json.loads(r["json"]) for r in con.execute(
            "select action_id, json from consult_exchanges")}
    finally:
        con.close()
    budget = next((o["scope"].get("action_budget") for o in obs.values() if o.get("scope")), None)
    tasks: dict[str, dict] = {}
    conds: dict[str, dict] = {}
    arts: dict[str, dict] = {}
    for ep in episodes:
        if ep["task_id"] not in tasks:
            t = yaml.safe_load((Path(labgene) / "configs" / "tasks" / f"{ep['task_id']}.yaml").read_text(encoding="utf-8"))
            tasks[ep["task_id"]] = {"task_id": ep["task_id"], "title": t["title"],
                                    "targets": {x["metric"]: x["target"] for x in t.get("success", [])}}
        cond = ep["condition"]
        if cond not in conds:
            conds[cond] = {"name": CONDITION_NAMES.get(cond, cond),
                           "summary": {"success": 0, "actions": 0, "consults": 0, "experiments": 0}, "episodes": []}
            arts[cond] = _knowledge(root, cond)
        c, out, to_success = conds[cond], [], None
        for a in (x for x in actions if x["episode_id"] == ep["episode_id"]):
            if a["kind"] == "consult":
                ex = consults.get(a["action_id"], {})
                resp = ex.get("response") or {}
                cited = [_cite(arts[cond], i) for i in resp.get("cited_source_ids") or []]
                cited += [_obs_cite(obs, i) for i in resp.get("cited_observation_ids") or []]
                out.append({"seq": a["seq"], "kind": "consult", "question": {"en": ex.get("question", ""), "ko": None},
                            "answer": {"en": resp.get("answer", ""), "ko": None}, "cited": cited})
                c["summary"]["consults"] += 1
            else:
                args = json.loads(a["payload_json"] or "{}").get("args", {})
                o = obs.get(a["action_id"])
                ok = bool(o and o.get("meets_success_criteria"))
                out.append({"seq": a["seq"], "kind": "experiment",
                            "note": {"en": args.get("hypothesis", ""), "ko": None},
                            "parameters": o["parameters"] if o else args.get("parameters", {}),
                            "results": {k: round(v, 2) for k, v in o["results"].items()} if o else None,
                            "success": ok})
                c["summary"]["experiments"] += 1
                if ok and to_success is None:
                    to_success = len(out)
            c["summary"]["actions"] += 1
        c["summary"]["success"] += int(ep.get("outcome") == "success")
        c["episodes"].append({"task_id": ep["task_id"], "outcome": ep.get("outcome"),
                              "actions_to_success": to_success, "actions": out})
    return {"run_id": run, "label": label, "date": date, "action_budget": budget,
            "tasks": list(tasks.values()), "conditions": conds}


def _texts(rep: dict) -> list[dict]:
    return [d for c in rep["conditions"].values() for ep in c["episodes"] for a in ep["actions"]
            for d in (a.get("question"), a.get("answer"), a.get("note")) if d and d.get("en")]


def reuse_korean(rep: dict, old: dict) -> None:
    """기존 재생 JSON의 번역을 같은 원문에 다시 붙인다 — 다시 내보내도 번역 호출을 반복하지 않는다."""
    known = {d["en"]: d["ko"] for d in _texts(old) if d.get("ko")}
    for d in _texts(rep):
        d["ko"] = d.get("ko") or known.get(d["en"])


def translate_replay(rep: dict, cfg) -> int:
    todo = [d for d in _texts(rep) if not d.get("ko")]
    for start in range(0, len(todo), BATCH):
        part = todo[start:start + BATCH]
        user = "다음 글을 한국어로 번역하라.\n" + json.dumps(
            [{"i": i, "en": d["en"]} for i, d in enumerate(part)], ensure_ascii=False)
        for it in generate_parsed(cfg, TRANSLATE_SYSTEM, user, Translations).items:
            if 0 <= it.i < len(part):
                part[it.i]["ko"] = it.ko
    return len(todo)


def main() -> None:
    ap = argparse.ArgumentParser(description="하네스 본실험 원장 → horcrux 시연 볼트·실험 재생 JSON")
    ap.add_argument("--labgene", required=True, help="labgene 저장소 루트")
    ap.add_argument("--run", default="pilot-02", help="artifacts 아래 실행 id (본실험 v1 = pilot-02)")
    ap.add_argument("--vault", help="레코드를 쓸 빈 볼트 경로")
    ap.add_argument("--replay", help="재생 JSON 경로 (예: web/public/replays/main-v1.json)")
    ap.add_argument("--translate", action="store_true", help="질문·답·메모를 llm.py로 한국어 번역")
    ap.add_argument("--label", default="본실험 v1", help="재생 화면에 보일 실행 이름")
    ap.add_argument("--date", default="2026-09-29", help="레코드 날짜 (본실험 v1 실행일)")
    args = ap.parse_args()
    if not args.vault and not args.replay:
        ap.error("--vault나 --replay 중 하나는 필요합니다")
    if args.vault:
        run = load_run(Path(args.labgene), args.run)
        ids = write_vault(run, Path(args.vault), args.date, f"labgene {args.run}")
        print(f"레코드 {len(ids)}건 → {Path(args.vault) / 'raw' / 'experiments'}")
    if args.replay:
        out = Path(args.replay)
        rep = load_replay(Path(args.labgene), args.run, args.label, args.date)
        if out.exists():
            reuse_korean(rep, json.loads(out.read_text(encoding="utf-8")))
        if args.translate:
            print(f"번역 {translate_replay(rep, load_config())}건")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"재생 JSON → {out}")


if __name__ == "__main__":
    main()
