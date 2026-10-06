"""실행 기록 — 워크플로 뷰가 재생하는 단계 이벤트를 kg.sqlite에 쌓는다.

기록 실패는 삼키고 로그만 남긴다. 실행 기록 때문에 저장·질의가 멈추면 안 된다.
데이터에는 id·개수·짧은 샘플만 넣는다. 프롬프트 본문은 저장하지 않는다.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .kg import db

MAX_RUNS = 300
MAX_DATA = 2048   # 이벤트 data JSON 바이트 상한 (2KB)


def start(vault: Path, kind: str, title: str, run_id: str | None = None) -> str:
    rid = run_id or uuid.uuid4().hex
    try:
        with db(vault) as conn:
            conn.execute("insert or replace into trace_run values(?,?,?,?,?,?)",
                         (rid, kind, title[:120], "running", time.time(), None))
            keep = "select run_id from trace_run order by started_at desc, rowid desc limit ?"
            conn.execute(f"delete from trace_event where run_id not in ({keep})", (MAX_RUNS,))
            conn.execute(f"delete from trace_run where run_id not in ({keep})", (MAX_RUNS,))
    except Exception as e:
        print(f"(실행 기록 실패: {e})")
    return rid


def event(vault: Path, run_id: str | None, stage: str, status: str, summary: str,
          data: dict | None = None, ms: int | None = None) -> None:
    if not run_id:
        return
    try:
        blob = json.dumps(data or {}, ensure_ascii=False, default=str)
        if len(blob.encode("utf-8")) > MAX_DATA:
            blob = json.dumps({"truncated": True})
        with db(vault) as conn:
            seq = conn.execute("select coalesce(max(seq), 0) + 1 from trace_event where run_id=?",
                               (run_id,)).fetchone()[0]
            conn.execute("insert into trace_event values(?,?,?,?,?,?,?,?)",
                         (run_id, seq, time.time(), stage, status, summary[:300], blob, ms))
    except Exception as e:
        print(f"(실행 기록 실패: {e})")


def finish(vault: Path, run_id: str | None, status: str = "done") -> None:
    if not run_id:
        return
    try:
        with db(vault) as conn:
            conn.execute("update trace_run set status=?, ended_at=? where run_id=?", (status, time.time(), run_id))
    except Exception as e:
        print(f"(실행 기록 실패: {e})")


def list_runs(vault: Path, limit: int = 30) -> list[dict]:
    with db(vault) as conn:
        rows = conn.execute(
            "select r.*, (select count(*) from trace_event e where e.run_id=r.run_id) as n_events "
            "from trace_run r order by started_at desc, rowid desc limit ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_run(vault: Path, run_id: str, after: int = 0) -> dict | None:
    with db(vault) as conn:
        run = conn.execute("select * from trace_run where run_id=?", (run_id,)).fetchone()
        if run is None:
            return None
        events = conn.execute("select * from trace_event where run_id=? and seq>? order by seq",
                              (run_id, after)).fetchall()
    return {"run": dict(run),
            "events": [{**dict(e), "data": json.loads(e["data"] or "{}")} for e in events]}
