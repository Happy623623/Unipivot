import Button from "@/components/Button";

// 포스터를 고르거나 끌어다 놓는 자리. 파일 입력은 화면이 들고 있고 여기서는 열기만 한다
export default function PosterDropzone({
  onDropFile,
  onChooseFile,
  onUseCamera,
}: {
  onDropFile: (file?: File) => void;
  onChooseFile: () => void;
  onUseCamera: () => void;
}) {
  return (
    <section
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        onDropFile(event.dataTransfer.files[0]);
      }}
      className="flex h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-dashed border-[#e5e7eb] bg-white max-md:h-auto max-md:min-h-[280px] max-md:rounded-[14px] max-md:px-[18px] max-md:py-7 max-md:text-center"
    >
      <span className="text-[34px] font-bold text-[#4f6ef7]">↑</span>
      <p className="text-[18px] font-semibold max-md:text-[17px]">이미지 또는 PDF를 업로드해주세요</p>
      <p className="text-[13px] text-[#667085]">JPG · PNG · WEBP 또는 2쪽 이하 PDF · 20MB 이하</p>
      {/* 좁은 화면에서는 버튼을 폭에 맞춰 위아래로 둔다. 사진 찍기는 좁은 화면(휴대폰)에서만 보인다 */}
      <div className="flex gap-2 max-md:w-full max-md:flex-col">
        <Button onClick={onChooseFile} className="max-md:min-h-[46px] max-md:w-full">파일 선택</Button>
        <span className="hidden max-md:inline-flex max-md:w-full">
          <Button secondary onClick={onUseCamera} className="max-md:min-h-[46px] max-md:w-full">사진 찍기</Button>
        </span>
      </div>
    </section>
  );
}
