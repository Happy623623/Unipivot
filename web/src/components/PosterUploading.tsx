// 파일을 저장소에 올리는 동안. 읽기(분석)는 PosterAnalyzing이 따로 보여 준다
export default function PosterUploading({ fileName }: { fileName: string }) {
  return (
    <section
      className="flex min-h-[310px] flex-col items-center justify-center gap-3 rounded-[18px] border border-[#e5e7eb] bg-white p-8 text-center"
      role="status"
    >
      <p className="text-[18px] font-semibold">포스터를 올리고 있어요</p>
      <p className="text-[13px] text-[#667085]">{fileName}</p>
    </section>
  );
}
