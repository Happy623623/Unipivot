// 로그인·캘린더 연결 뒤에 돌아갈 경로. 다른 사이트로 보내지 않게 우리 사이트 안의 경로만 받는다
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value;
}

// 경로에 쿼리 값을 하나 붙인다: withQuery("/settings?tab=1", "calendar", "connected") → "/settings?tab=1&calendar=connected"
export function withQuery(path: string, key: string, value: string): string {
  const url = new URL(path, "http://localhost");
  url.searchParams.set(key, value);
  return `${url.pathname}${url.search}${url.hash}`;
}
