import type { RefObject } from "react";

// 숨긴 파일 입력 둘(파일 선택·사진 찍기). 고른 뒤 값을 비워 같은 파일을 다시 고를 수 있게 한다
export default function PosterFileInputs({
  fileRef,
  cameraRef,
  onPick,
}: {
  fileRef: RefObject<HTMLInputElement | null>;
  cameraRef: RefObject<HTMLInputElement | null>;
  onPick: (file?: File) => void;
}) {
  const handle = (event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0];
    event.target.value = "";
    onPick(picked);
  };
  return (
    <>
      <input ref={fileRef} type="file" accept=".jpg,.jpeg,.png,.webp,.pdf" className="hidden" onChange={handle} />
      <input ref={cameraRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="hidden" onChange={handle} />
    </>
  );
}
