const allowedExtensions = /\.(jpe?g|png|webp|heic|pdf)$/i;

async function getPdfPageCount(file: File): Promise<number> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const source = new TextDecoder("latin1").decode(bytes);
  return source.match(/\/Type\s*\/Page\b/g)?.length ?? 0;
}

export async function validatePosterFile(file: File): Promise<string | null> {
  if (!allowedExtensions.test(file.name)) {
    return "JPG, PNG, WEBP, HEIC 또는 PDF 파일만 올릴 수 있어요.";
  }
  if (file.size > 20 * 1024 * 1024) {
    return "파일이 20MB를 넘어요. 더 작은 파일을 올려 주세요.";
  }
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (isPdf && (await getPdfPageCount(file)) > 2) {
    return "PDF는 2쪽 이하만 올릴 수 있어요.";
  }
  return null;
}
