from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    vault: Path
    provider: str = "claude"
    model: str | None = None  # None = 각 CLI의 기본 모델 사용
    api_key: str | None = None  # provider == "api"일 때 사용 (없으면 env ANTHROPIC_API_KEY)
    extra_env: dict[str, str] | None = None  # CLI 서브프로세스에 병합할 연구실별 크레덴셜

    def __post_init__(self):
        self.vault = Path(self.vault)


def _config_path() -> Path:
    # 프로그램 설정 — 볼트의 config.yaml(연구실 게이트 설정)과 별개
    return Path.home() / ".horcrux" / "config.yaml"


def load_config() -> Config:
    data = {}
    p = _config_path()
    if p.exists():
        import yaml
        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            loaded = None
        data = loaded if isinstance(loaded, dict) else {}  # 깨진 파일은 무시 — init으로 재작성

    def pick(env_key: str, file_key: str, default):
        return os.environ.get(env_key) or data.get(file_key) or default

    return Config(
        vault=Path(pick("HORCRUX_VAULT", "vault", "example-vault")),
        provider=pick("HORCRUX_PROVIDER", "provider", "claude"),
        model=pick("HORCRUX_MODEL", "model", None),
    )


def save_config(values: dict) -> Path:
    import yaml
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(values, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


# §2a — 구조 카테고리 하드 게이트 후보 (볼트 config.yaml의 required_fields가 이 중에서 선택)
GATEABLE_FIELDS = ["objective", "parameters", "results", "symptom", "actions_taken", "notes"]


@dataclass
class VaultConfig:
    required_fields: list[str]
    required_parameters: list[str]
    domains: list[str] = field(default_factory=list)   # 도메인 선택 (시연 범위 — 실제 어휘는 바뀌지 않는다)


def load_vault_config(vault: Path) -> VaultConfig:
    p = Path(vault) / "config.yaml"
    data = {}
    if p.exists():
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rf = data.get("required_fields")
    rp = data.get("required_parameters")
    return VaultConfig(
        required_fields=list(rf) if rf is not None else list(GATEABLE_FIELDS),
        required_parameters=list(rp) if rp is not None else [],
        domains=list(data.get("domains") or []),
    )
