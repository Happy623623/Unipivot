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
      className="flex h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-dashed border-[#e5e7eb] bg-white"
    >
      <span className="text-[34px] font-bold text-[#4f6ef7]">↑</span>
      <p className="text-[18px] font-semibold">이미지 또는 PDF를 업로드해주세요</p>
      <p className="text-[13px] text-[#667085]">JPG · PNG · WEBP 또는 2쪽 이하 PDF · 20MB 이하</p>
      <div className="flex gap-2">
        <Button onClick={onChooseFile}>파일 선택</Button>
        <span className="hidden max-[760px]:inline-flex">
          <Button secondary onClick={onUseCamera}>사진 찍기</Button>
        </span>
      </div>
    </section>
  );
}
