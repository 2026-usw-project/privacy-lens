import type { AnalyzeResponse } from "./types.gen";

export interface ApiError {
  code: string;
  message: string;
}

export async function analyze(file: File): Promise<AnalyzeResponse> {
  const body = new FormData();
  body.append("file", file);
  let res: Response;
  try {
    res = await fetch("/api/v1/analyze", { method: "POST", body });
  } catch {
    throw { code: "NETWORK", message: "서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인하세요." } as ApiError;
  }
  const data = await res.json();
  if (!res.ok) throw (data.error ?? { code: "INTERNAL", message: "알 수 없는 오류" }) as ApiError;
  return data as AnalyzeResponse;
}
