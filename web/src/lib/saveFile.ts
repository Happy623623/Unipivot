// 글을 파일로 내려받게 한다(.ics 등). 화면 코드 대신 여기서만 문서(DOM)를 만진다
export function saveTextFile(filename: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1_000); // 내려받기가 시작된 뒤에 주소를 거둔다
}
