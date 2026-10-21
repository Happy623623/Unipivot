import { useEffect, useState } from "react";

// 화면을 열 때부터 들어 있는 안내는 화면 읽기 프로그램이 읽지 않는다(live 영역은 바뀐 내용만 읽는다).
// 그래서 빈 영역(role="status"·"alert")을 먼저 그리고, 조금 뒤에 글을 넣는다. 글이 바뀌면 다시 늦춰 넣는다
const DELAY_MS = 150;

export default function useLateAnnouncement(text: string | null): string | null {
  const [shown, setShown] = useState<string | null>(null);

  useEffect(() => {
    setShown(null);
    if (!text) return;
    const timer = setTimeout(() => setShown(text), DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);

  return shown;
}
