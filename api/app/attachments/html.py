"""HTML → 글자. 원문 페이지 다시 읽기(fetch_original)와 게시판 본문에 쓴다.

표는 행마다 "셀 | 셀" 한 줄로 만든다. 스크립트·스타일과 <head>는 버린다.
메뉴(nav)·바닥글(footer)은 버리지 않는다. 닫는 태그가 빠진 페이지에서 본문까지 사라질 수 있어서다.
"""

from html.parser import HTMLParser

from app.attachments.reader import clean_text

_SKIP = frozenset({"script", "style", "noscript", "template", "svg"})
# <head> 안에 올 수 있는 태그. 다른 태그가 나오면 </head>가 빠졌어도 머리가 끝난 것으로 본다(HTML5 규칙)
_HEAD_TAGS = frozenset({"title", "meta", "link", "base", "style", "script", "noscript", "template"})
_BLOCK = frozenset(
    {
        "address", "article", "aside", "blockquote", "caption", "dd", "div", "dl", "dt",
        "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
        "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "thead",
        "tfoot", "ul",
    }
)  # fmt: skip


def html_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    parser.flush()
    return "\n".join(parser.lines)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        self._skip = 0  # 열린 _SKIP 태그 수
        self._in_head = False
        self._cell = 0  # 열린 td·th 수. 셀 안에서는 줄을 바꾸지 않는다

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self._in_head = True
            return
        if self._in_head and tag not in _HEAD_TAGS:
            self._in_head = False  # <body>나 본문 태그가 나오면 머리는 끝났다
        if tag in _SKIP:
            self._skip += 1
        elif tag in ("td", "th"):
            if self._cell:
                self._buffer.append(" ")  # 셀 안의 표
            elif "".join(self._buffer).strip():
                self._buffer.append(" | ")
            self._cell += 1
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt and alt.strip() and not self._hidden():
                self._buffer.append(f" [이미지: {alt.strip()}] ")
        elif tag in ("br", "tr") or tag in _BLOCK:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th"):
            self._cell = max(0, self._cell - 1)
        elif tag == "tr" or tag in _BLOCK:
            self._break()

    def handle_data(self, data: str) -> None:
        if not self._hidden():
            self._buffer.append(data)

    def _hidden(self) -> bool:
        return bool(self._skip) or self._in_head

    def _break(self) -> None:
        if self._cell:
            self._buffer.append(" ")
        else:
            self.flush()

    def flush(self) -> None:
        line = " ".join(clean_text("".join(self._buffer)).split())
        self._buffer.clear()
        if line:
            self.lines.append(line)
