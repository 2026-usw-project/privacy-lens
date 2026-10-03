import { useCallback, useMemo, useState } from "react";
import { analyze, type ApiError } from "./api";
import { download, renderMasked } from "./mask";
import type { AnalyzeResponse, BBox, Finding } from "./types.gen";
import Viewer from "./Viewer";

const LABEL_KO: Record<string, string> = {
  parcel_label: "택배 송장", student_id: "학생증", name_tag: "명찰", payment_card: "카드", screen: "화면",
  license_plate: "번호판", receipt: "영수증", document: "문서", qr_barcode: "QR코드",
};
const TYPE_KO: Record<string, string> = {
  person_name: "이름", address: "주소", phone: "전화번호", tracking_number: "송장번호", student_number: "학번",
  affiliation: "소속", url: "링크", rrn: "주민번호", card_number: "카드번호", plate_number: "차량번호", email: "이메일",
  account_number: "계좌번호", gps: "GPS", device: "기기", other: "기타",
};
const LEVEL_KO: Record<string, string> = { high: "위험", medium: "주의", low: "낮음", none: "안전" };

type State =
  | { kind: "idle" }
  | { kind: "busy"; name: string }
  | { kind: "done"; res: AnalyzeResponse; img: ImageBitmap; name: string }
  | { kind: "error"; err: ApiError };

/** 마스킹 대상: 개인정보 항목 박스가 있으면 그 줄만, 없으면 영역 전체 */
function boxesOf(f: Finding): BBox[] {
  const b = (f.pii ?? []).flatMap((p) => (p.bbox ? [p.bbox] : []));
  return b.length ? b : [f.bbox];
}

export default function App() {
  const [st, setSt] = useState<State>({ kind: "idle" });
  const [masked, setMasked] = useState<Set<number>>(new Set());
  const [showMask, setShowMask] = useState(true);
  const [active, setActive] = useState<number | null>(null);
  const [drag, setDrag] = useState(false);

  const run = useCallback(async (file: File) => {
    setSt({ kind: "busy", name: file.name });
    setActive(null);
    try {
      // imageOrientation: 'from-image' → 서버의 exif_transpose 와 같은 방향으로 맞춤
      const [res, img] = await Promise.all([analyze(file), createImageBitmap(file, { imageOrientation: "from-image" })]);
      setMasked(new Set(res.findings.filter((f) => f.risk.level !== "low").map((f) => f.id)));
      setSt({ kind: "done", res, img, name: file.name });
    } catch (e) {
      setSt({ kind: "error", err: (e as ApiError).message ? (e as ApiError) : { code: "DECODE", message: "이미지를 열 수 없습니다." } });
    }
  }, []);

  const onFiles = (fl: FileList | null) => fl?.[0] && run(fl[0]);

  const maskBoxes = useMemo(
    () => (st.kind === "done" ? st.res.findings.filter((f) => masked.has(f.id)).flatMap(boxesOf) : []),
    [st, masked],
  );

  const toggle = (id: number) =>
    setMasked((m) => {
      const n = new Set(m);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });

  return (
    <div className="app" onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}>
      <header>
        <div className="brand"><span className="lens" />Privacy Lens</div>
        <p>사진을 올리기 전에, 내가 놓친 개인정보를 찾아드립니다</p>
        {st.kind === "done" && (
          <label className="btn ghost">다른 사진<input type="file" accept="image/*" hidden onChange={(e) => onFiles(e.target.files)} /></label>
        )}
      </header>

      {(st.kind === "idle" || st.kind === "error") && (
        <label className={`drop ${drag ? "over" : ""}`}>
          <input type="file" accept="image/*" hidden onChange={(e) => onFiles(e.target.files)} />
          <div className="drop-icon">＋</div>
          <strong>사진을 끌어다 놓거나 클릭해서 선택</strong>
          <span>JPG · PNG · WEBP, 20MB 이하 · 분석 후 원본은 서버에 저장되지 않습니다</span>
          {st.kind === "error" && <div className="err">{st.err.message}</div>}
        </label>
      )}

      {st.kind === "busy" && (
        <div className="busy">
          <div className="spinner" />
          <strong>{st.name} 분석 중</strong>
          <span>메타데이터 → 글자 인식 → QR → 개인정보 판정</span>
        </div>
      )}

      {st.kind === "done" && (
        <main>
          <Viewer img={st.img} findings={st.res.findings} maskBoxes={maskBoxes} showMask={showMask}
            activeId={active} onPick={setActive} />
          <aside>
            <div className={`summary lv-${st.res.summary.level}`}>
              <span className="badge">{LEVEL_KO[st.res.summary.level]}</span>
              <p>{st.res.summary.headline}</p>
            </div>

            {st.res.exif.gps && (
              <div className="card lv-high">
                <div className="card-h"><span className="dot" />촬영 위치 (EXIF)</div>
                <p>{st.res.exif.risk.reason}</p>
                <small>{st.res.exif.device ?? "기기 정보 없음"} · 안전본 저장 시 자동 제거</small>
              </div>
            )}

            {st.res.findings.map((f) => (
              <div key={f.id} className={`card lv-${f.risk.level} ${active === f.id ? "on" : ""}`}
                onMouseEnter={() => setActive(f.id)} onMouseLeave={() => setActive(null)}>
                <div className="card-h">
                  <span className="num">{f.id + 1}</span>
                  {LABEL_KO[f.label]}
                  <span className="lv">{LEVEL_KO[f.risk.level]} {Math.round(f.risk.score * 100)}</span>
                  <label className="chk"><input type="checkbox" checked={masked.has(f.id)} onChange={() => toggle(f.id)} />가리기</label>
                </div>
                <p>{f.risk.reason}</p>
                <div className="chips">
                  {(f.pii ?? []).map((p, i) => (
                    <span key={i} className="chip"><b>{TYPE_KO[p.type]}</b>{p.value_masked}</span>
                  ))}
                </div>
              </div>
            ))}

            {st.res.findings.length === 0 && <div className="card"><p>검출된 영역이 없습니다.</p></div>}

            <div className="actions">
              <label className="chk"><input type="checkbox" checked={showMask} onChange={(e) => setShowMask(e.target.checked)} />가림 미리보기</label>
              <button className="btn" onClick={() => download(renderMasked(st.img, maskBoxes), `safe_${st.name.replace(/\.\w+$/, "")}.jpg`)}>
                안전 버전 저장
              </button>
            </div>
            <small className="meta">
              분석 {(st.res.timing.total_ms / 1000).toFixed(1)}초 · {st.res.models.ocr} · 저장본은 EXIF가 제거된 새 JPEG
            </small>
          </aside>
        </main>
      )}
    </div>
  );
}
