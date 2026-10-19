// 파일을 내려받게 한다(.ics·문서함). 화면 코드 대신 여기서만 문서(DOM)를 만진다
export function saveBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1_000); // 내려받기가 시작된 뒤에 주소를 거둔다
}

export function saveTextFile(filename: string, text: string, type: string): void {
  saveBlob(filename, new Blob([text], { type }));
}

// 받기 주소에서 파일을 받지 못했다. message는 화면에 그대로 보여 주는 안내다(주소는 들어 있지 않다 — 열쇠다)
export class DownloadFailed extends Error {}

const TIMEOUT_MS = 120_000; // 20MB 첨부를 느린 망에서 받을 시간. 넘기면 버튼이 "받는 중…"에 갇히지 않게 끊는다
const OFFLINE = "인터넷에 연결되어 있지 않아요. 연결을 확인하고 다시 눌러 주세요.";
const UNREACHABLE = "파일 저장소에 연결하지 못했어요. 잠시 후 다시 눌러 주세요.";
const TOO_SLOW = "파일을 받는 데 너무 오래 걸려요. 다시 눌러 주세요.";
const GONE = "파일이 그새 없어졌어요. 다시 눌러 주세요."; // 다시 누르면 서버가 어디서 다시 받는지 알려 준다
const REFUSED = "파일 저장소가 파일을 주지 않았어요. 잠시 후 다시 눌러 주세요.";
const NOT_A_URL = "받기 주소가 아니에요. 잠시 후 다시 눌러 주세요.";

// 저장소가 거절한 이유. Supabase Storage는 오류를 JSON 본문의 code로 준다(없는 파일은 `NoSuchKey`)
async function refusal(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  const code = typeof body === "object" && body !== null ? (body as { code?: unknown }).code : null;
  return code === "NoSuchKey" ? GONE : REFUSED;
}

// 서버가 준 5분짜리 받기 주소(문서함, F-44)에서 파일을 받아 `filename`으로 저장한다. 저장소(Supabase Storage)가
// CORS를 열어 두어서(`*`, 10/19 실제 확인) 브라우저가 fetch로 받을 수 있다. 주소를 그냥 열면 저장소가 거절했을 때
// 오류 JSON이 그 탭에 그대로 뜨는데, 여기서 받으면 안내 문구로 바꿀 수 있다. http(s)가 아닌 주소는 열지 않고,
// 우리 주소(Referer)와 쿠키는 보내지 않는다(쿠키를 보내면 CORS `*`와 맞지 않아 브라우저가 막는다). 받는 동안 화면은 그대로다
export async function fetchDownload(url: string, filename: string): Promise<void> {
  if (!/^https?:\/\//i.test(url)) throw new DownloadFailed(NOT_A_URL);
  let blob: Blob;
  try {
    const response = await fetch(url, {
      credentials: "omit",
      referrerPolicy: "no-referrer",
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) throw new DownloadFailed(await refusal(response));
    // 저장소가 준 Content-Type(공지 첨부는 HTML·SVG도 온다)은 쓰지 않는다. blob: 주소는 우리 앱 출처라, download를
    // 무시하는 브라우저(일부 앱 안 브라우저)가 그 주소를 열면 첨부의 HTML이 우리 출처에서 돈다. 타입을 중립으로 두면
    // 열리지 않고 저장만 된다 — 무엇으로 열지는 이름의 확장자가 정한다
    blob = new Blob([await response.arrayBuffer()], { type: "application/octet-stream" });
  } catch (error) {
    if (error instanceof DownloadFailed) throw error;
    if (error instanceof DOMException && error.name === "TimeoutError") throw new DownloadFailed(TOO_SLOW);
    throw new DownloadFailed(typeof navigator !== "undefined" && !navigator.onLine ? OFFLINE : UNREACHABLE);
  }
  saveBlob(filename, blob);
}
