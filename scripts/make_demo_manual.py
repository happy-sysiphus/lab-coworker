"""시연용 영문 합성 매뉴얼 PDF를 만든다 (외부 라이브러리 없이 손으로 쓴 PDF).

    py -3.13 scripts/make_demo_manual.py [demo/manual-flow-suzuki.pdf]

실제 장비 매뉴얼이 아니다. 본실험 과제(스즈키-미야우라 흐름 합성)의 공개 조건 범위에 맞춰 쓴 시연 자료다.
pdf_bytes()는 테스트 픽스처도 쓴다.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_bytes(pages: list[list[str]], title: str = "") -> bytes:
    """페이지마다 줄 목록을 받아 Helvetica 텍스트 PDF를 만든다. 빈 문자열 줄은 문단 사이 빈 줄이다."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = add(b"")
    kids = []
    for lines in pages:
        wrapped = [w for line in lines for w in (textwrap.wrap(line, 92) or [""])]
        ops = " ".join(f"({_esc(w)}) Tj T*" for w in wrapped)
        stream = f"BT /F1 10 Tf 13 TL 60 750 Td {ops} ET".encode("cp1252", "replace")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
                         f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>").encode()))
    objs[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                          f"/Count {len(kids)} >>").encode()
    info = add(f"<< /Title ({_esc(title)}) >>".encode("cp1252", "replace"))
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


if __name__ == "__main__":
    from demo_manual_text import PAGES, TITLE   # 시연 본문은 별도 파일에 둔다

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo/manual-flow-suzuki.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf_bytes(PAGES, TITLE))
    print(f"wrote {out} ({len(PAGES)} pages)")
