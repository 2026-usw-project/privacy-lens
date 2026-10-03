import type { BBox, Point } from "./types.gen";

/** 가릴 영역: 직사각형(bbox)은 항상 있고, 회전 사각형(quad)은 있을 때만 */
export interface Shape {
  box: BBox;
  quad?: Point[] | null;
}

/** 직사각형 모자이크 (블록 크기는 영역 높이에 비례 → 작은 글자도 확실히 뭉개짐) */
export function pixelate(ctx: CanvasRenderingContext2D, b: BBox, pad = 0.35) {
  // 여백은 글자 높이 기준 — 기울어진 사진에서 글자 끝이 박스 밖으로 살짝 나오는 것까지 덮음
  const w = b.x2 - b.x1;
  const h = b.y2 - b.y1;
  // 상한 48px: 여러 줄을 합친 큰 박스에서 여백이 커져 아래 줄(고객센터 번호 등)까지 덮지 않도록
  const px = Math.round(Math.min(Math.min(w, h) * pad, 48));
  const x = Math.max(0, b.x1 - px);
  const y = Math.max(0, b.y1 - px);
  const W = Math.min(ctx.canvas.width - x, w + px * 2);
  const H = Math.min(ctx.canvas.height - y, h + px * 2);
  mosaic(ctx, x, y, W, H, Math.max(6, Math.round(Math.min(W, H) / 4)));
}

/** 회전 사각형을 자기 축 방향으로 여백만큼 키움 (네 점: 좌상, 우상, 우하, 좌하) */
export function expandQuad(q: Point[], padRatio = 0.22, maxPad = 36): { quad: Point[]; height: number } {
  const [p0, p1, , p3] = q;
  const ux = p1.x - p0.x, uy = p1.y - p0.y;
  const vx = p3.x - p0.x, vy = p3.y - p0.y;
  const wl = Math.hypot(ux, uy) || 1;
  const hl = Math.hypot(vx, vy) || 1;
  const pad = Math.min(hl * padRatio, maxPad);
  const ax = (ux / wl) * pad, ay = (uy / wl) * pad;
  const bx = (vx / hl) * pad, by = (vy / hl) * pad;
  const sign = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
  return {
    quad: q.map((p, i) => ({ x: p.x + sign[i][0] * ax + sign[i][1] * bx, y: p.y + sign[i][0] * ay + sign[i][1] * by })),
    height: hl + pad * 2,
  };
}

/** 회전 사각형 모양 그대로 모자이크 — 바깥은 원본 유지 */
export function pixelateQuad(ctx: CanvasRenderingContext2D, q: Point[]) {
  const { quad, height } = expandQuad(q);
  const xs = quad.map((p) => p.x), ys = quad.map((p) => p.y);
  const x = Math.max(0, Math.floor(Math.min(...xs)));
  const y = Math.max(0, Math.floor(Math.min(...ys)));
  const W = Math.min(ctx.canvas.width, Math.ceil(Math.max(...xs))) - x;
  const H = Math.min(ctx.canvas.height, Math.ceil(Math.max(...ys))) - y;
  if (W <= 0 || H <= 0) return;
  ctx.save();
  ctx.beginPath();
  quad.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.closePath();
  ctx.clip();
  mosaic(ctx, x, y, W, H, Math.max(6, Math.round(height / 3)));
  ctx.restore();
}

function mosaic(ctx: CanvasRenderingContext2D, x: number, y: number, W: number, H: number, block: number) {
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

/** 원본 해상도 캔버스에 사진 + 선택된 영역 마스킹을 그림. fit=true 면 회전 사각형 모양으로 */
export function renderMasked(img: ImageBitmap, shapes: Shape[], fit = true): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  const ctx = c.getContext("2d")!;
  ctx.drawImage(img, 0, 0);
  for (const s of shapes) {
    if (fit && s.quad && s.quad.length === 4) pixelateQuad(ctx, s.quad);
    else pixelate(ctx, s.box);
  }
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
