"""whl + exe 빌드 (Windows 전용 — exe 아티팩트명 고정). 릴리스 절차는 docs/RELEASING.md 참조.

사전: pip install -e .[release]
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*cmd: str) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


run(sys.executable, "-m", "build", "--wheel")
run(sys.executable, "-m", "PyInstaller", "--onefile", "--noconfirm", "--name", "horcrux",
    "--paths", str(ROOT / "src"),  # editable 설치 여부와 무관하게 horcrux 패키지 해석
    "--collect-data", "horcrux",   # 공통 온톨로지·도메인 레지스트리 YAML
    str(ROOT / "src" / "horcrux" / "__main__.py"))
run(str(ROOT / "dist" / "horcrux.exe"), "--help")  # 번들 임포트 자체 검증
print("완료 — dist/ 에 whl + horcrux.exe")
