import { useEffect, useRef } from "react";
import type { Finding } from "./types.gen";
import { renderMasked, type Shape } from "./mask";

const COLOR: Record<string, string> = { high: "#e5383b", medium: "#f4a261", low: "#8d99ae", none: "#8d99ae" };

interface Props {
  img: ImageBitmap;
  findings: Finding[];
  maskShapes: Shape[];
  showMask: boolean;
  fit: boolean;
  activeId: number | null;
  onPick: (id: number | null) => void;
}

/** 사진 + 검출 박스 오버레이. 좌표는 서버 응답(원본 해상도) 기준 → 화면 크기로 비례 변환 */
export default function Viewer({ img, findings, maskShapes, showMask, fit, activeId, onPick }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const c = ref.current!;
    const box = c.parentElement!.getBoundingClientRect();
    const s = Math.min(box.width / img.width, (window.innerHeight * 0.78) / img.height);
    const dpr = window.devicePixelRatio || 1;
    c.style.width = `${img.width * s}px`;
    c.style.height = `${img.height * s}px`;
    c.width = Math.round(img.width * s * dpr);
    c.height = Math.round(img.height * s * dpr);
    const ctx = c.getContext("2d")!;
    const src = showMask ? renderMasked(img, maskShapes, fit) : img;
    ctx.drawImage(src, 0, 0, c.width, c.height);
    const k = s * dpr;
    for (const f of findings) {
      const b = f.bbox;
      const on = f.id === activeId;
      ctx.lineWidth = (on ? 5 : 3) * dpr;
      ctx.strokeStyle = COLOR[f.risk.level];
      ctx.setLineDash(f.risk.level === "low" ? [8 * dpr, 6 * dpr] : []);
      ctx.strokeRect(b.x1 * k, b.y1 * k, (b.x2 - b.x1) * k, (b.y2 - b.y1) * k);
      // 번호 배지
      const r = 13 * dpr;
      ctx.setLineDash([]);
      ctx.fillStyle = COLOR[f.risk.level];
      ctx.beginPath();
      ctx.arc(b.x1 * k, b.y1 * k, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = `700 ${14 * dpr}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(f.id + 1), b.x1 * k, b.y1 * k + dpr);
      if (on) {
        ctx.fillStyle = "rgba(229,56,59,0.12)";
        ctx.fillRect(b.x1 * k, b.y1 * k, (b.x2 - b.x1) * k, (b.y2 - b.y1) * k);
      }
    }
    // 가림 미리보기를 끈 상태에서는 가릴 모양(회전 사각형)을 얇은 선으로 표시
    if (!showMask && fit) {
      ctx.setLineDash([]);
      ctx.lineWidth = 1.5 * dpr;
      ctx.strokeStyle = "rgba(229,56,59,0.9)";
      for (const s of maskShapes) {
        if (!s.quad || s.quad.length !== 4) continue;
        ctx.beginPath();
        s.quad.forEach((p, i) => (i ? ctx.lineTo(p.x * k, p.y * k) : ctx.moveTo(p.x * k, p.y * k)));
        ctx.closePath();
        ctx.stroke();
      }
    }
  }, [img, findings, maskShapes, showMask, fit, activeId]);

  const click = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const c = ref.current!;
    const rect = c.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * img.width;
    const y = ((e.clientY - rect.top) / rect.height) * img.height;
    const hit = findings.find((f) => x >= f.bbox.x1 && x <= f.bbox.x2 && y >= f.bbox.y1 && y <= f.bbox.y2);
    onPick(hit ? hit.id : null);
  };

  return (
    <div className="viewer">
      <canvas ref={ref} onClick={click} />
    </div>
  );
}
