from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from pydantic import BaseModel

from .config import Config

PROVIDERS = ("claude", "gemini", "codex", "api")
_TIMEOUT = 300  # 초 — CLI 무응답 행 방지
_API_DEFAULT_MODEL = "claude-sonnet-4-5"


def _exe(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(
            f"'{name}' CLI를 찾을 수 없음 — 설치·로그인 후 재시도 (HORCRUX_PROVIDER={name})"
        )
    return path


def _run(cmd: list[str], prompt: str, env: dict[str, str] | None = None) -> str:
    if env:
        # 연구실 자체 크레덴셜 사용 — 중앙 ANTHROPIC_API_KEY가 상속되면 claude CLI가
        # 그쪽을 우선해 중앙 키로 과금된다. 상속 목록에서 제거 후 연구실 값 주입.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"} | env
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env,
    )
    try:
        out, err = p.communicate(prompt, timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        # npm .cmd shim은 실제 CLI가 손자 프로세스 — 직계만 죽이면 파이프 대기로 무한 블록.
        # Windows는 taskkill /T로 프로세스 트리 전체 종료.
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.kill()
        p.communicate()
        raise RuntimeError(f"{cmd[0]} 응답 없음 — {_TIMEOUT}초 초과") from None
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 실패 (exit {p.returncode}): {err.strip()[-500:]}")
    return out.strip()


def _anthropic_client(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _generate_api(cfg: Config, system: str, user: str) -> str:
    key = cfg.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("api provider에는 ANTHROPIC_API_KEY(또는 연구실 키)가 필요합니다")
    resp = _anthropic_client(key).messages.create(
        model=cfg.model or _API_DEFAULT_MODEL, max_tokens=16000,
        system=system, messages=[{"role": "user", "content": user}],
    )
    return next(b.text for b in resp.content if b.type == "text").strip()


def generate(cfg: Config, system: str, user: str) -> str:
    if cfg.provider == "api":
        return _generate_api(cfg, system, user)
    # 프롬프트는 stdin으로 전달 — Windows 커맨드라인 길이 제한 회피
    prompt = f"{system}\n\n{user}"
    model = ["--model", cfg.model] if cfg.model else []
    if cfg.provider == "claude":
        return _run([_exe("claude"), "-p", *model], prompt, env=cfg.extra_env)
    if cfg.provider == "gemini":
        return _run([_exe("gemini"), *model], prompt, env=cfg.extra_env)  # stdin 파이프 = headless
    if cfg.provider == "codex":
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "last.txt"
            _run(
                [_exe("codex"), "exec", "-", "--skip-git-repo-check", "--ephemeral",
                 "--sandbox", "read-only", "-o", str(out), *model],
                prompt,
                env=cfg.extra_env,
            )
            # codex stdout은 진행 로그 포함 — 최종 메시지는 -o 파일이 정본
            return out.read_text(encoding="utf-8").strip()
    raise NotImplementedError(f"provider '{cfg.provider}' 미지원 — {PROVIDERS} 중 선택")


_JSON_INSTR = (
    "\n\n응답은 아래 JSON 스키마에 맞는 JSON 객체 하나만 출력하라. 코드펜스·설명·주석 금지.\n"
    "스키마: {schema}"
)


def _extract_json(text: str) -> str:
    # 후보 순서대로 json.loads로 검증해 첫 유효 JSON 반환 — 펜스 태그 대소문자,
    # 문자열 필드 안 ``` 절단, 전후 산문 케이스 전부 커버
    candidates = []
    m = re.search(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        candidates.append(text[s:e + 1])
    candidates.append(text.strip())
    for c in candidates:
        try:
            json.loads(c)
            return c
        except ValueError:
            continue
    return candidates[-1]


def generate_parsed(cfg: Config, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    instr = _JSON_INSTR.format(
        schema=json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )
    raw = generate(cfg, system + instr, user)
    try:
        return schema.model_validate_json(_extract_json(raw))
    except Exception:
        # CLI는 스키마 강제가 없어 파싱 실패가 일상적 — 어댑터에서 1회 재생성 (모든 호출부 커버)
        raw = generate(cfg, system + instr, user)
        return schema.model_validate_json(_extract_json(raw))


# ---------------------------------------------------------------- 임베딩 (온톨로지 구축 단계 전용)
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIMS = 3072
_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:batchEmbedContents"


def embed(texts: list[str], kind: str) -> list[list[float]] | None:
    """하네스 GeminiEmbedder 이식(표준 라이브러리 HTTP). 키가 없거나 실패하면 None — 호출자는 대체 경로로 간다.

    질의는 'task: search result | query: …', 문서는 'title: none | text: …' 형식이다. 요청당 100개."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    out: list[list[float]] = []
    for i in range(0, len(texts), 100):
        part = [f"task: search result | query: {t}" if kind == "query" else f"title: none | text: {t}"
                for t in texts[i:i + 100]]
        body = {"requests": [{"model": f"models/{EMBED_MODEL}", "content": {"parts": [{"text": t}]},
                              "output_dimensionality": EMBED_DIMS} for t in part]}
        req = urllib.request.Request(_EMBED_URL.format(m=EMBED_MODEL), data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"(임베딩 실패 — 대체 경로로 진행: {e})")
            return None
        vecs = [e.get("values") for e in data.get("embeddings") or [] if isinstance(e, dict)]
        if len(vecs) != len(part) or not all(isinstance(v, list) and v for v in vecs):
            return None
        out += [[float(x) for x in v] for v in vecs]
    return out
