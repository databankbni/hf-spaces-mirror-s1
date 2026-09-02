"""Streamlit static/index.html 의 <title> 과 OG/twitter 메타태그를 우리 앱 이름으로 교체.

카카오톡·슬랙 등 메신저 link unfurl 크롤러는 JS 를 실행하지 않으므로,
런타임 `st.set_page_config(page_title=...)` 만으로는 미리보기 제목이 "Streamlit"
으로 노출됨. Docker 빌드 시점에 한 번 정적 HTML 자체를 갈아끼우는 방식.
"""
from __future__ import annotations

import pathlib
import re
import sys

import streamlit

TITLE = "사모신용 모니터링"
DESC = "미국 BDC·사모대출 데일리 리스크 대시보드"


def main() -> int:
    p = pathlib.Path(streamlit.__file__).parent / "static" / "index.html"
    if not p.exists():
        print(f"[patch_streamlit_og] not found: {p}", file=sys.stderr)
        return 1

    html = p.read_text(encoding="utf-8")

    html = re.sub(r"<title>[^<]*</title>", f"<title>{TITLE}</title>", html, count=1)

    og_block = (
        f'<meta property="og:title" content="{TITLE}"/>'
        f'<meta property="og:description" content="{DESC}"/>'
        f'<meta property="og:type" content="website"/>'
        f'<meta name="twitter:title" content="{TITLE}"/>'
        f'<meta name="twitter:description" content="{DESC}"/>'
        f'<meta name="description" content="{DESC}"/>'
    )
    if "og:title" not in html:
        html = html.replace("</head>", og_block + "</head>", 1)

    p.write_text(html, encoding="utf-8")
    print(f"[patch_streamlit_og] patched: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
