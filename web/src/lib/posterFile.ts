const allowedExtensions = /\.(jpe?g|png|webp|pdf)$/i;
const heicExtension = /\.(heic|heif)$/i;

async function getPdfPageCount(file: File): Promise<number> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const source = new TextDecoder("latin1").decode(bytes);
  return source.match(/\/Type\s*\/Page\b/g)?.length ?? 0;
}

// 서버(POST /files)와 같은 기준으로 먼저 거른다. 20MB 파일을 올렸다가 413을 받지 않게 한다
export async function validatePosterFile(file: File): Promise<string | null> {
  if (heicExtension.test(file.name)) {
    return "아이폰 사진 형식(HEIC)은 아직 올릴 수 없어요. 사진을 JPG로 바꿔서 올려 주세요.";
  }
  if (!allowedExtensions.test(file.name)) {
    return "JPG·PNG·WEBP 사진이나 2쪽 이하 PDF만 올릴 수 있어요.";
  }
  if (file.size > 20 * 1024 * 1024) {
    return "파일이 20MB를 넘어요. 더 작은 파일을 올려 주세요.";
  }
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (isPdf && (await getPdfPageCount(file)) > 2) {
    return "PDF는 2쪽까지만 올릴 수 있어요. 포스터가 있는 쪽만 남겨서 올려 주세요.";
  }
  return null;
}
