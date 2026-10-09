"""외부 웹 수집. 지금은 페이지 가져오기(fetch)만 있고, ERICA 게시판 크롤러가 S1-4 2부로 들어온다."""

from app.crawl.fetch import Fetched, FetchError, WebFetcher, decode_html

__all__ = ["FetchError", "Fetched", "WebFetcher", "decode_html"]
