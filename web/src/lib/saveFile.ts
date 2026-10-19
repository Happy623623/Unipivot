// 파일을 내려받게 한다(.ics·문서함). 화면 코드 대신 여기서만 문서(DOM)를 만진다
export function saveTextFile(filename: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1_000); // 내려받기가 시작된 뒤에 주소를 거둔다
}

// 서버가 준 받기 주소를 연다(문서함, F-44). 저장소가 `Content-Disposition: attachment`로 주므로 지금 화면은
// 그대로 두고 내려받기만 시작된다. http(s)가 아닌 주소는 열지 않는다. 우리 주소(Referer)는 보내지 않는다
export function openDownload(url: string): void {
  if (!/^https?:\/\//i.test(url)) throw new Error("받기 주소가 아니에요.");
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener noreferrer";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}
