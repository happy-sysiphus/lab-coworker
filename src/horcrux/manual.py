"""Phase 1 매뉴얼 — PDF 바이트 → 페이지 텍스트(pypdf) → 정제 → 청킹 → 볼트 진실 파일 + kg.sqlite 문서·청크·색인.

스캔 PDF·이미지는 다루지 않는다. 글자가 MIN_CHARS 미만인 페이지는 스캔으로 보고 건너뛴다.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import time
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

from . import kg, trace
from .vocab import load_vocabulary, write_atomic

MIN_CHARS = 50
CHUNK_MAX = 1200
_SENT = re.compile(r"(?<=[.!?])\s+")


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    return re.sub(r"[^\w가-힣]+", "-", s).strip("-_") or "doc"


def parse_range(spec: str | None, n: int) -> list[int]:
    """'12-40', '3', '1-3,7' → 1부터 n 사이의 쪽 번호. 비어 있으면 전부."""
    if not spec or spec == "all":
        return list(range(1, n + 1))
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        if a:
            out.update(p for p in range(int(a), int(b or a) + 1) if 1 <= p <= n)
    return sorted(out)


def _reader(data: bytes):
    import pypdf
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as e:
        raise ValueError(f"PDF를 열 수 없습니다: {e}") from None
    if reader.is_encrypted:
        raise ValueError("암호가 걸린 PDF입니다")
    return reader


def extract_pages(data: bytes, page_range: str | None = None) -> list[tuple[int, str]]:
    reader = _reader(data)
    try:
        return [(p, reader.pages[p - 1].extract_text() or "") for p in parse_range(page_range, len(reader.pages))]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"PDF 텍스트를 뽑지 못했습니다: {e}") from None


def _key(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().casefold())


def clean_pages(pages: list[tuple[int, str]]) -> tuple[list[tuple[int, str]], list[int]]:
    """머리말·꼬리말·쪽번호(쪽 절반 이상에서 되풀이되는 첫·끝 두 줄) 제거, 줄 끝 하이픈 연결, 공백 정규화."""
    skipped = [p for p, t in pages if len(re.sub(r"\s", "", t)) < MIN_CHARS]
    kept = [(p, t) for p, t in pages if p not in skipped]
    edge: Counter[str] = Counter()
    for _, t in kept:
        lines = [x for x in t.splitlines() if x.strip()]
        edge.update({_key(x) for x in lines[:2] + lines[-2:]})
    boiler = {k for k, c in edge.items() if c >= 2 and c * 2 >= len(kept)}
    out = []
    for p, t in kept:
        lines = t.splitlines()
        nonblank = [i for i, x in enumerate(lines) if x.strip()]
        edges = set(nonblank[:2] + nonblank[-2:])
        text = "\n".join(x for i, x in enumerate(lines) if not (i in edges and _key(x) in boiler))
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        text = "\n".join(re.sub(r"[ \t]+", " ", x).strip() for x in text.splitlines())
        out.append((p, re.sub(r"\n{3,}", "\n\n", text).strip()))
    return out, skipped


def _split_sentences(para: str) -> list[str]:
    out, cur = [], ""
    for s in _SENT.split(para):
        if cur and len(cur) + 1 + len(s) > CHUNK_MAX:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
        while len(cur) > CHUNK_MAX:   # 문장 하나가 한도보다 길면 자른다
            out.append(cur[:CHUNK_MAX])
            cur = cur[CHUNK_MAX:]
    return out + ([cur] if cur else [])


def chunk_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """페이지 안에서 빈 줄 기준 문단을 CHUNK_MAX자 이하로 묶는다. 넘는 문단은 문장 경계에서 자른다."""
    chunks = []
    for p, text in pages:
        paras = [re.sub(r"\s*\n\s*", " ", x).strip() for x in re.split(r"\n\s*\n", text) if x.strip()]
        cur = ""
        for para in paras:
            for piece in ([para] if len(para) <= CHUNK_MAX else _split_sentences(para)):
                if cur and len(cur) + 1 + len(piece) > CHUNK_MAX:
                    chunks.append((p, cur))
                    cur = piece
                else:
                    cur = f"{cur}\n{piece}" if cur else piece
        if cur:
            chunks.append((p, cur))
    return chunks


def _write_bytes(p: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


def add_manual(vault: Path, filename: str, data: bytes, pages: str | None = None,
               run_id: str | None = None) -> dict:
    """업로드 한 건을 문서로 등록한다. 같은 sha256이면 기존 문서를 돌려준다(멱등). 문서는 queued로 들어간다."""
    vault = Path(vault)
    sha = hashlib.sha256(data).hexdigest()
    with kg.db(vault) as conn:
        row = conn.execute("select doc_id from doc where sha256=?", (sha,)).fetchone()
        if row:
            return {"doc_id": row[0], "created": False}
        base = "man-" + slugify(Path(filename).stem)
        doc_id, n = base, 2
        while conn.execute("select 1 from doc where doc_id=?", (doc_id,)).fetchone():
            doc_id, n = f"{base}-{n}", n + 1
    reader = _reader(data)
    d = vault / "raw" / "manuals"
    d.mkdir(parents=True, exist_ok=True)
    _write_bytes(d / f"{doc_id}.pdf", data)
    trace.event(vault, run_id, "p1.save", "ok", f"원본 저장 · {filename} ({len(data) // 1024} KB)", {"doc_id": doc_id})
    try:
        raw = extract_pages(data, pages)
    except ValueError:
        (d / f"{doc_id}.pdf").unlink(missing_ok=True)
        raise
    trace.event(vault, run_id, "p1.text", "ok", f"{len(raw)}쪽 텍스트 추출", {"pages": len(raw)})
    kept, skipped = clean_pages(raw)
    trace.event(vault, run_id, "p1.clean", "info" if skipped else "ok",
                f"머리말·쪽번호 정제" + (f", 스캔 의심 {len(skipped)}쪽 건너뜀" if skipped else ""), {"skipped": skipped})
    chunks = chunk_pages(kept)
    title = str(reader.metadata.title if reader.metadata and reader.metadata.title else "") or Path(filename).stem
    fm = yaml.safe_dump({"title": title, "source_file": filename, "sha256": sha, "pages": len(raw),
                         "page_range": pages or "all"}, allow_unicode=True, sort_keys=False)
    body = "\n\n".join(f"<!-- page: {p} -->\n{t}" for p, t in kept)
    write_atomic(d / f"{doc_id}.md", f"---\n{fm}---\n\n{body}\n")
    vocab = load_vocabulary(vault)
    with kg.db(vault) as conn:
        conn.execute("insert into doc values(?,?,?,?,?,?,?,?,?,?)",
                     (doc_id, "manual", title, filename, sha, len(raw), pages or "all", "queued", None, time.time()))
        for seq, (p, text) in enumerate(chunks, 1):
            cid = f"{doc_id}#{seq}"
            conn.execute("insert into chunk values(?,?,?,?,?,?,?,?)", (cid, doc_id, p, seq, text, "pending", 0, None))
            conn.execute("insert into chunk_fts values(?,?,?)", (cid, doc_id, text))
        kg.sync_passages(conn, vocab, doc_id)
    trace.event(vault, run_id, "p1.chunk", "ok", f"청크 {len(chunks)}개 · 전문 색인", {"chunks": len(chunks)})
    return {"doc_id": doc_id, "created": True, "title": title, "pages": len(raw), "skipped": skipped,
            "chunks": len(chunks)}
