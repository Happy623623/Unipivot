import type { ChangeEvent, RefObject } from "react";

// 숨긴 파일 입력 하나(계획서 PDF). 고른 뒤 값을 비워 **같은 파일을 다시 고를 수 있게** 한다 —
// 올리다 실패한 뒤 같은 파일을 다시 고르는 것이 가장 흔한 되돌리기다(PosterFileInputs와 같은 방식)
export default function SyllabusFileInput({
  inputRef,
  onPick,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  onPick: (file?: File) => void;
}) {
  const handle = (event: ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    event.target.value = "";
    onPick(picked);
  };
  return (
    <input
      ref={inputRef}
      type="file"
      accept="application/pdf,.pdf"
      className="hidden"
      onChange={handle}
    />
  );
}
