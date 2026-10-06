"""하네스 본실험 원장 → horcrux 시연 볼트 레코드.

    PYTHONPATH=src py -3.13 scripts/export_experiment.py --labgene C:/Users/지완/claude/labgene \
        --run pilot-02 --vault demo-vault

가상 실험(run_experiment) 한 건이 레코드 md 한 건이 된다. LLM을 부르지 않는 결정론 변환이다.
같은 에피소드의 실험은 followup_of로 이어져 그래프에서 조건 변화와 결과 변화가 보인다.
재생 JSON(--replay)은 다음 마일스톤에서 붙는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

import yaml

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


def main() -> None:
    ap = argparse.ArgumentParser(description="하네스 본실험 원장 → horcrux 시연 볼트")
    ap.add_argument("--labgene", required=True, help="labgene 저장소 루트")
    ap.add_argument("--run", default="pilot-02", help="artifacts 아래 실행 id (본실험 v1 = pilot-02)")
    ap.add_argument("--vault", required=True, help="레코드를 쓸 빈 볼트 경로")
    ap.add_argument("--date", default="2026-09-29", help="레코드 날짜 (본실험 v1 실행일)")
    args = ap.parse_args()
    run = load_run(Path(args.labgene), args.run)
    ids = write_vault(run, Path(args.vault), args.date, f"labgene {args.run}")
    print(f"레코드 {len(ids)}건 → {Path(args.vault) / 'raw' / 'experiments'}")


if __name__ == "__main__":
    main()
