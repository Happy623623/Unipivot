// 공고에서 온 바깥 주소(원문·첨부·양식)는 http·https만 링크로 건다. 그 밖이면 null
export function webUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}
