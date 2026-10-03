import type { BBox } from "./types.gen";

/** 영역을 모자이크 처리 (블록 크기는 영역 높이에 비례 → 작은 글자도 확실히 뭉개짐) */
export function pixelate(ctx: CanvasRenderingContext2D, b: BBox, pad = 0.15) {
  const w = b.x2 - b.x1;
  const h = b.y2 - b.y1;
  const px = Math.round(Math.min(w, h) * pad);
  const x = Math.max(0, b.x1 - px);
  const y = Math.max(0, b.y1 - px);
  const W = Math.min(ctx.canvas.width - x, w + px * 2);
  const H = Math.min(ctx.canvas.height - y, h + px * 2);
  const block = Math.max(6, Math.round(Math.min(W, H) / 4));
  const sw = Math.max(1, Math.round(W / block));
  const sh = Math.max(1, Math.round(H / block));
  const tmp = document.createElement("canvas");
  tmp.width = sw;
  tmp.height = sh;
  const t = tmp.getContext("2d")!;
  t.imageSmoothingEnabled = true;
  t.drawImage(ctx.canvas, x, y, W, H, 0, 0, sw, sh);
  ctx.save();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(tmp, 0, 0, sw, sh, x, y, W, H);
  ctx.restore();
}

/** 원본 해상도 캔버스에 사진 + 선택된 영역 마스킹을 그림 */
export function renderMasked(img: ImageBitmap, boxes: BBox[]): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  const ctx = c.getContext("2d")!;
  ctx.drawImage(img, 0, 0);
  for (const b of boxes) pixelate(ctx, b);
  return c;
}

/** 캔버스로 다시 인코딩 → EXIF(GPS 포함)가 남지 않는 새 JPEG */
export function download(canvas: HTMLCanvasElement, name: string) {
  canvas.toBlob(
    (blob) => {
      if (!blob) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    },
    "image/jpeg",
    0.92,
  );
}
