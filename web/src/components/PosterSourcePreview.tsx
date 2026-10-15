// 올린 포스터 미리보기. PDF는 그릴 수 없어 파일 이름만 보여 준다
export default function PosterSourcePreview({
  previewUrl,
  fileName,
  isPdf,
}: {
  previewUrl: string;
  fileName: string;
  isPdf: boolean;
}) {
  return (
    <section className="flex min-h-[520px] items-center justify-center overflow-hidden rounded-[18px] border border-[#e5e7eb] bg-white p-5">
      {isPdf ? (
        <div className="text-center">
          <div className="mx-auto flex size-20 items-center justify-center rounded-[14px] bg-[#fef2f2] text-[18px] font-bold text-[#c53030]">PDF</div>
          <p className="mt-3 text-[13px] text-[#667085]">{fileName}</p>
        </div>
      ) : (
        <img src={previewUrl || "/assets/mock-opportunity-poster.svg"} alt="업로드한 포스터 미리보기" className="max-h-[640px] rounded-[14px] object-contain" />
      )}
    </section>
  );
}
