import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from horcrux import llm
from horcrux.config import GATEABLE_FIELDS, Config, load_config, load_vault_config
from horcrux.llm import _extract_json, generate, generate_parsed


def test_load_config_defaults(isolated_config):
    cfg = load_config()
    assert cfg.provider == "claude"
    assert cfg.model is None
    assert str(cfg.vault) == "example-vault"


def test_load_config_env_override(isolated_config, monkeypatch):
    monkeypatch.setenv("HORCRUX_VAULT", "my-lab")
    monkeypatch.setenv("HORCRUX_PROVIDER", "gemini")
    monkeypatch.setenv("HORCRUX_MODEL", "gemini-2.5-pro")
    cfg = load_config()
    assert str(cfg.vault) == "my-lab"
    assert cfg.provider == "gemini"
    assert cfg.model == "gemini-2.5-pro"


def test_load_config_from_file(isolated_config):
    isolated_config.write_text(yaml.safe_dump({
        "vault": "C:/lab/v", "provider": "codex",
    }, allow_unicode=True), encoding="utf-8")
    cfg = load_config()
    assert cfg.vault == Path("C:/lab/v")
    assert cfg.provider == "codex"


def test_env_beats_file(isolated_config, monkeypatch):
    isolated_config.write_text(yaml.safe_dump({"provider": "codex"}), encoding="utf-8")
    monkeypatch.setenv("HORCRUX_PROVIDER", "claude")
    assert load_config().provider == "claude"


def test_save_config_roundtrip(isolated_config):
    from horcrux.config import save_config
    path = save_config({"vault": "C:/v", "provider": "claude", "model": None})
    assert path == isolated_config
    cfg = load_config()
    assert cfg.vault == Path("C:/v")


def test_save_config_creates_parent_dir(monkeypatch, tmp_path):
    from horcrux import config as config_mod
    p = tmp_path / "deep" / "config.yaml"
    monkeypatch.setattr(config_mod, "_config_path", lambda: p, raising=False)
    from horcrux.config import save_config
    save_config({"provider": "claude"})
    assert p.exists()


def test_load_config_ignores_corrupt_file(isolated_config):
    isolated_config.write_text("그냥 문자열", encoding="utf-8")  # dict 아닌 YAML
    assert load_config().provider == "claude"  # 트레이스백 없이 기본값


def test_load_config_ignores_malformed_yaml(isolated_config):
    isolated_config.write_text("provider: [unclosed\n  key: :bad", encoding="utf-8")  # 구문 오류
    assert load_config().provider == "claude"  # 트레이스백 없이 기본값


def test_vault_config_defaults(tmp_path):
    vc = load_vault_config(tmp_path)
    assert vc.required_fields == GATEABLE_FIELDS
    assert vc.required_parameters == []


def test_vault_config_from_yaml(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "required_fields: [objective, results]\nrequired_parameters:\n  - 챔버 습도\n",
        encoding="utf-8",
    )
    vc = load_vault_config(tmp_path)
    assert vc.required_fields == ["objective", "results"]
    assert vc.required_parameters == ["챔버 습도"]


def test_vault_config_null_keys(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "required_fields:\nrequired_parameters:\n", encoding="utf-8")
    vc = load_vault_config(tmp_path)
    assert vc.required_fields == GATEABLE_FIELDS
    assert vc.required_parameters == []


# --- CLI 어댑터: 프로바이더별 커맨드 구성 (_run 모킹) ---

class FakeRunFn:
    def __init__(self, out="응답"):
        self.calls = []
        self.out = out

    def __call__(self, cmd, prompt, env=None):
        self.calls.append((cmd, prompt, env))
        return self.out if isinstance(self.out, str) else self.out(cmd)


@pytest.fixture
def fake_run(monkeypatch):
    fr = FakeRunFn()
    monkeypatch.setattr(llm, "_run", fr)
    monkeypatch.setattr(llm.shutil, "which", lambda name: f"/bin/{name}")
    return fr


def test_generate_claude_command(fake_run):
    out = generate(Config(vault="v", provider="claude", model="opus"), "시스템", "유저")
    assert out == "응답"
    cmd, prompt, _ = fake_run.calls[0]
    assert cmd == ["/bin/claude", "-p", "--model", "opus"]
    assert prompt == "시스템\n\n유저"


def test_generate_no_model_omits_flag(fake_run):
    generate(Config(vault="v", provider="claude"), "s", "u")
    assert "--model" not in fake_run.calls[0][0]


def test_generate_gemini_command(fake_run):
    generate(Config(vault="v", provider="gemini"), "s", "u")
    cmd, prompt, _ = fake_run.calls[0]
    assert cmd == ["/bin/gemini"]
    assert prompt == "s\n\nu"


def test_generate_codex_command_and_last_message_file(fake_run):
    def write_and_return(cmd):
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("최종 메시지")
        return "진행 로그"

    fake_run.out = write_and_return
    out = generate(Config(vault="v", provider="codex"), "s", "u")
    assert out == "최종 메시지"  # stdout(진행 로그) 아닌 -o 파일이 정본
    cmd, _, _ = fake_run.calls[0]
    out_path = cmd[cmd.index("-o") + 1]
    assert cmd == ["/bin/codex", "exec", "-", "--skip-git-repo-check", "--ephemeral",
                   "--sandbox", "read-only", "-o", out_path]


def test_generate_missing_cli_raises(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="찾을 수 없음"):
        generate(Config(vault="v", provider="gemini"), "s", "u")


def test_unknown_provider_raises(fake_run):
    with pytest.raises(NotImplementedError):
        generate(Config(vault="v", provider="hal9000"), "s", "u")


# --- _run 내부: 종료 코드·타임아웃 (Popen 모킹) ---

class FakePopen:
    def __init__(self, out="응답", err="", returncode=0, hang=False):
        self.out, self.err, self.returncode, self.hang = out, err, returncode, hang
        self.pid = 123
        self.killed = False

    def __call__(self, cmd, **kw):
        return self

    def communicate(self, prompt=None, timeout=None):
        if self.hang and not self.killed:
            self.killed = True  # kill 후 2차 communicate는 반환
            raise subprocess.TimeoutExpired("cmd", timeout)
        return self.out, self.err

    def kill(self):
        self.killed = True


def test_run_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(llm.subprocess, "Popen", FakePopen(err="로그인 필요", returncode=1))
    with pytest.raises(RuntimeError, match="로그인 필요"):
        llm._run(["x"], "p")


def test_run_timeout_kills_tree_and_raises(monkeypatch):
    monkeypatch.setattr(llm.subprocess, "Popen", FakePopen(hang=True))
    killer = FakeRunFn()  # taskkill 호출 기록
    monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: killer.calls.append(cmd))
    with pytest.raises(RuntimeError, match="초과"):
        llm._run(["x"], "p")
    if llm.os.name == "nt":
        assert killer.calls and killer.calls[0][:3] == ["taskkill", "/F", "/T"]


# --- generate_parsed ---

class Out(BaseModel):
    x: int


def test_generate_parsed_validates_json(fake_run):
    fake_run.out = '{"x": 3}'
    got = generate_parsed(Config(vault="v", provider="claude"), "s", "u", Out)
    assert got.x == 3
    # 스키마가 프롬프트에 포함됐는지
    assert '"x"' in fake_run.calls[0][1]


def test_generate_parsed_retries_once_then_succeeds(fake_run):
    outs = iter(["JSON 아님", '{"x": 7}'])
    fake_run.out = lambda cmd: next(outs)
    got = generate_parsed(Config(vault="v", provider="claude"), "s", "u", Out)
    assert got.x == 7
    assert len(fake_run.calls) == 2


def test_generate_parsed_bad_json_raises_after_retry(fake_run):
    fake_run.out = "JSON 아님"
    with pytest.raises(Exception):
        generate_parsed(Config(vault="v", provider="claude"), "s", "u", Out)
    assert len(fake_run.calls) == 2


@pytest.mark.parametrize("raw,expect", [
    ('```json\n{"x": 1}\n```', '{"x": 1}'),
    ('```JSON\n{"x": 1}\n```', '{"x": 1}'),          # 대문자 태그
    ('```\n{"x": 1}\n```', '{"x": 1}'),
    ('설명입니다.\n{"x": 1}\n이상입니다.', '{"x": 1}'),
    ('{"x": 1}', '{"x": 1}'),
    # 문자열 필드 안에 ```가 있으면 펜스 매칭이 절단되지만 brace-scan 폴백이 복구
    ('```json\n{"x": 1, "s": "code ``` fence"}\n```', '{"x": 1, "s": "code ``` fence"}'),
])
def test_extract_json(raw, expect):
    assert _extract_json(raw) == expect


# --- api provider: anthropic SDK (중앙 모드, _anthropic_client 모킹) ---


def test_generate_api_provider(monkeypatch):
    calls = {}

    class FakeMsg:
        content = [type("B", (), {"type": "text", "text": "응답"})()]

    class FakeClient:
        def __init__(self, api_key):
            calls["key"] = api_key
            self.messages = type("M", (), {"create": self._create})()

        def _create(self, **kw):
            calls["kw"] = kw
            return FakeMsg()

    import horcrux.llm as llm_mod
    monkeypatch.setattr(llm_mod, "_anthropic_client", lambda key: FakeClient(key))
    out = generate(Config(vault="v", provider="api", model="claude-sonnet-4-5",
                          api_key="sk-test"), "시스템", "유저")
    assert out == "응답"
    assert calls["key"] == "sk-test"
    assert calls["kw"]["system"] == "시스템"


def test_generate_api_without_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        generate(Config(vault="v", provider="api"), "s", "u")


# --- extra_env: 연구실별 크레덴셜 주입 ---


def test_run_merges_extra_env(monkeypatch):
    captured = {}

    class P:
        pid = 1
        returncode = 0
        def communicate(self, prompt=None, timeout=None):
            return "ok", ""

    def fake_popen(cmd, **kw):
        captured["env"] = kw.get("env")
        return P()

    monkeypatch.setattr(llm.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "중앙키")
    llm._run(["x"], "p", env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"})
    assert captured["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"
    assert "PATH" in captured["env"]  # os.environ 병합 확인
    # 연구실 자체 크레덴셜을 쓸 땐 중앙 키가 우선하면 안 됨 (중앙 과금 방지)
    assert "ANTHROPIC_API_KEY" not in captured["env"]

    llm._run(["x"], "p")   # 중앙 모드는 그대로 상속 (env=None → os.environ)
    assert captured["env"] is None
    assert os.environ["ANTHROPIC_API_KEY"] == "중앙키"


def test_generate_passes_extra_env(fake_run):
    generate(Config(vault="v", provider="claude",
                    extra_env={"CLAUDE_CODE_OAUTH_TOKEN": "tok"}), "s", "u")
    # fake_run이 (cmd, prompt, env) 3-튜플을 기록하도록 FakeRunFn.__call__ 시그니처에 env=None 추가
    assert fake_run.calls[0][2] == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}


def test_web_search_claude_uses_only_web_tools(fake_run):
    fake_run.out = '{"results": [{"title": "T", "url": "https://x.org/a", "quote": "q", "summary": "s"}]}'
    hits = llm.web_search(Config(vault="v", provider="claude"), "질문", ["SPhos Pd G4"])
    assert [(h.title, h.url) for h in hits] == [("T", "https://x.org/a")]
    cmd, prompt, _ = fake_run.calls[0]
    assert cmd == ["/bin/claude", "-p", "--tools", "WebSearch", "WebFetch", "--allowedTools", "WebSearch",
                   "WebFetch", "--strict-mcp-config"]
    assert "SPhos Pd G4" in prompt and "질문" in prompt


def test_web_search_unsupported_providers(fake_run):
    for p in ("gemini", "codex"):
        with pytest.raises(llm.WebUnsupported):
            llm.web_search(Config(vault="v", provider=p), "질문")

