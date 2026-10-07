import threading
from dataclasses import dataclass
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from horcrux import server
from horcrux.config import Config
from horcrux.server import DeployCtx, create_app

SECRET = "s"


def tok(sub="user-1"):
    return pyjwt.encode({"sub": sub, "aud": "authenticated"}, SECRET, algorithm="HS256")


class FakeDB:
    def __init__(self):
        self.labs, self.members, self.usage_ok = {}, {}, True
        self.credentials = {}
        self.last_limit = None      # bump_usage에 실제로 넘어간 상한 — 천장 적용 확인용

    def create_lab(self, user_id, name):
        lab = {"id": f"lab-{len(self.labs)+1}", "name": name, "invite_code": "abcd1234",
               "llm_mode": "central", "llm_provider": None, "daily_llm_limit": 200,
               "llm_credential": "gAAAAA-fernet-ciphertext"}  # 실제 스키마와 동일 — 응답 유출 감시용
        self.labs[lab["id"]] = lab
        self.members[user_id] = (lab["id"], "admin")
        return lab

    def join_lab(self, user_id, code):
        for lab in self.labs.values():
            if lab["invite_code"] == code:
                self.members[user_id] = (lab["id"], "member")
                return lab
        raise LookupError("bad code")

    def lab_for_user(self, user_id):
        if user_id not in self.members:
            return None
        lab_id, role = self.members[user_id]
        return self.labs[lab_id], role

    def update_settings(self, lab_id, fields):
        self.labs[lab_id].update(fields)

    def get_credential(self, lab_id):
        return self.credentials.get(lab_id)

    def set_credential(self, lab_id, provider, secret):
        self.credentials[lab_id] = (provider, secret)
        self.labs[lab_id].update({"llm_mode": "own", "llm_provider": provider})

    def bump_usage(self, lab_id, limit):
        self.last_limit = limit
        return self.usage_ok

    def get_usage(self, lab_id):
        return 3

    def list_members(self, lab_id):
        return [{"user_id": u, "email": f"{u}@lab.test", "role": r}
                for u, (lid, r) in self.members.items() if lid == lab_id]


@pytest.fixture
def deploy_client(tmp_path):
    db = FakeDB()
    app = create_app(Config(vault=tmp_path / "unused"),
                     DeployCtx(db=db, jwt_secret=SECRET, data_dir=tmp_path))
    return TestClient(app), db


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_requires_token(deploy_client):
    client, _ = deploy_client
    assert client.get("/api/records").status_code == 401


def test_no_lab_403_and_onboarding(deploy_client):
    client, db = deploy_client
    assert client.get("/api/records", headers=auth(tok())).status_code == 403
    r = client.post("/api/labs", json={"name": "랩"}, headers=auth(tok()))
    assert r.status_code == 200
    assert client.get("/api/records", headers=auth(tok())).status_code == 200


def test_join_by_invite_code(deploy_client):
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    r = client.post("/api/labs/join", json={"invite_code": "abcd1234"}, headers=auth(tok("u2")))
    assert r.status_code == 200
    me = client.get("/api/labs/me", headers=auth(tok("u2"))).json()
    assert me["role"] == "member"


def test_vault_isolated_per_lab(deploy_client, tmp_path):
    client, db = deploy_client
    client.post("/api/labs", json={"name": "A"}, headers=auth(tok("u1")))
    lab_id = db.members["u1"][0]
    # 서버가 이 연구실 요청에 쓰는 볼트 경로 검증: parse를 모킹해 cfg.vault 캡처
    seen = {}
    def fake_parse(cfg, text, vcfg):
        seen["vault"] = cfg.vault
        from horcrux.ingest import ParsedLog
        return ParsedLog()
    import horcrux.server as sv
    orig = sv.parse_log
    sv.parse_log = fake_parse
    try:
        client.post("/api/parse", json={"text": "x"}, headers=auth(tok("u1")))
    finally:
        sv.parse_log = orig
    assert seen["vault"] == tmp_path / "vaults" / lab_id


def test_usage_limit_429(deploy_client):
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok()))
    db.usage_ok = False
    r = client.post("/api/ask", json={"text": "q"}, headers=auth(tok()))
    assert r.status_code == 429


def test_feedback_record_id_cannot_escape_own_vault(deploy_client, tmp_path):
    from horcrux.records import ExperimentRecord, record_path, save_record

    client, db = deploy_client
    client.post("/api/labs", json={"name": "A"}, headers=auth(tok("u1")))
    client.post("/api/labs", json={"name": "B"}, headers=auth(tok("u2")))
    victim_vault = tmp_path / "vaults" / db.members["u2"][0]
    rec = ExperimentRecord(id="2026-08-01_x-001", date="2026-08-01")
    save_record(victim_vault, rec, "원문", "정리")
    before = record_path(victim_vault, rec.id).read_text(encoding="utf-8")

    r = client.post("/api/feedback",
                    json={"record_id": f"../../../{db.members['u2'][0]}/raw/experiments/{rec.id}",
                          "resolved": True, "cause": "탈취"},
                    headers=auth(tok("u1")))
    assert 400 <= r.status_code < 500
    assert record_path(victim_vault, rec.id).read_text(encoding="utf-8") == before


def test_lab_response_hides_credential_and_member_invite(deploy_client):
    client, db = deploy_client
    created = client.post("/api/labs", json={"name": "A"}, headers=auth(tok("u1"))).json()["lab"]
    assert "llm_credential" not in created
    assert created["invite_code"] == "abcd1234"          # 관리자는 초대 코드가 필요
    joined = client.post("/api/labs/join", json={"invite_code": "abcd1234"},
                         headers=auth(tok("u2"))).json()["lab"]
    assert "llm_credential" not in joined and "invite_code" not in joined
    member = client.get("/api/labs/me", headers=auth(tok("u2"))).json()["lab"]
    assert "llm_credential" not in member and "invite_code" not in member
    admin = client.get("/api/labs/me", headers=auth(tok("u1"))).json()["lab"]
    assert "llm_credential" not in admin and admin["invite_code"] == "abcd1234"


def test_auth_config_is_public(deploy_client, monkeypatch):
    client, _ = deploy_client
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    r = client.get("/api/auth-config")  # 토큰 없이도 200이어야 프론트가 부팅한다
    assert r.status_code == 200
    assert r.json() == {"deploy": True, "supabase_url": "https://x.supabase.co",
                        "supabase_anon_key": "anon"}


def test_lab_me_usage_and_members(deploy_client):
    client, _ = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    client.post("/api/labs/join", json={"invite_code": "abcd1234"}, headers=auth(tok("u2")))
    admin = client.get("/api/labs/me", headers=auth(tok("u1"))).json()
    assert admin["usage_today"] == 3
    assert {m["role"] for m in admin["members"]} == {"admin", "member"}
    assert "members" not in client.get("/api/labs/me", headers=auth(tok("u2"))).json()


def test_lab_admin_cannot_change_daily_limit(deploy_client):
    # 일일 상한은 운영자 전용 — 연구실 관리자가 보내도 반영되지 않는다
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    r = client.put("/api/labs/settings",
                   json={"name": "새이름", "daily_llm_limit": 5000}, headers=auth(tok("u1")))
    assert r.status_code == 200
    assert db.labs["lab-1"]["daily_llm_limit"] == 200     # 무시됨
    assert db.labs["lab-1"]["name"] == "새이름"           # 같은 요청의 나머지는 반영


def test_usage_uses_operator_set_limit(deploy_client, monkeypatch):
    # 운영자가 DB에서 상한을 바꾸면 다음 호출부터 그 값으로 센다
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    db.labs["lab-1"]["daily_llm_limit"] = 50             # Supabase 대시보드에서 고친 상황
    monkeypatch.setattr(server, "diagnose_data", lambda cfg, t, run_id=None, web_ok=None: {
        "answer": "a", "evidence": "none", "records": [], "wiki": []})
    assert client.post("/api/ask", json={"text": "q"}, headers=auth(tok("u1"))).status_code == 200
    assert db.last_limit == 50


def _captured_cfg(client, db, monkeypatch, headers):
    seen = {}
    def fake_parse(cfg, text, vcfg):
        seen["cfg"] = cfg
        from horcrux.ingest import ParsedLog
        return ParsedLog()
    monkeypatch.setattr(server, "parse_log", fake_parse)
    client.post("/api/parse", json={"text": "x"}, headers=headers)
    return seen["cfg"]


def test_codex_without_credential_uses_machine_login(deploy_client, monkeypatch):
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    r = client.put("/api/labs/settings", json={"llm_mode": "own", "llm_provider": "codex"},
                   headers=auth(tok("u1")))
    assert r.status_code == 200
    assert db.labs["lab-1"]["llm_provider"] == "codex"
    cfg = _captured_cfg(client, db, monkeypatch, auth(tok("u1")))
    assert cfg.provider == "codex" and cfg.extra_env is None


def test_codex_with_key_injects_openai_env(deploy_client, monkeypatch):
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    client.put("/api/labs/settings",
               json={"llm_mode": "own", "llm_provider": "codex", "llm_credential": "sk-openai-x"},
               headers=auth(tok("u1")))
    cfg = _captured_cfg(client, db, monkeypatch, auth(tok("u1")))
    assert cfg.provider == "codex"
    assert cfg.extra_env == {"OPENAI_API_KEY": "sk-openai-x"}


def test_settings_admin_only(deploy_client):
    client, db = deploy_client
    client.post("/api/labs", json={"name": "랩"}, headers=auth(tok("u1")))
    client.post("/api/labs/join", json={"invite_code": "abcd1234"}, headers=auth(tok("u2")))
    assert client.put("/api/labs/settings", json={"name": "새이름"},
                      headers=auth(tok("u2"))).status_code == 403
    assert client.put("/api/labs/settings", json={"name": "새이름"},
                      headers=auth(tok("u1"))).status_code == 200
