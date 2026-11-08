# 집 PC(그래픽카드)로 학습하기

Colab 무료 GPU 한도가 모자랄 때 쓴다(2026-11-04 하루에 두 번 바닥남). Colab 노트북과 같은 코드(`vision/next_steps.py`)를
그대로 쓰고, 학습 기록은 드라이브 `objects/runs/` 에 남으므로 **Colab 과 PC 를 오가며 이어서** 할 수 있다.

## 1. 한 번만 설치 (Windows, PowerShell)

1. [Python 3.12](https://www.python.org/downloads/) — 설치할 때 "Add python.exe to PATH" 체크. [Git](https://git-scm.com/download/win).
2. 그래픽카드 드라이버가 최신인지 확인(`nvidia-smi` 가 실행되면 됨).
3. 코드와 패키지 (RTX 50 시리즈는 CUDA 12.8 용 PyTorch 가 필요하다):

```powershell
cd D:\
git clone https://github.com/2026-usw-project/privacy-lens
cd privacy-lens
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt "ultralytics>=8.4" onnxruntime fiftyone pycocotools
```

## 2. 드라이브 연결

[Google Drive 데스크톱](https://www.google.com/drive/download/)을 설치하고 로그인하면 `G:\내 드라이브\PrivacyLens-YOLO`
(팀 폴더 바로가기)가 보인다. 드라이브 문자가 다르면 그에 맞게 바꾼다.

## 3. 실행

```powershell
cd D:\privacy-lens
.venv\Scripts\Activate.ps1
git pull
$env:PL_DRIVE = "G:\내 드라이브\PrivacyLens-YOLO"   # 팀 폴더
$env:PL_WORK  = "D:\pl_work"                        # 임시 파일, 여유 50GB 이상
$env:PL_BATCH = "16"                                # 부하를 줄이려면 8
python -m vision.pc_train check      # 경로·GPU·온도 확인
python -m vision.pc_train daily      # 일상 사진 9종 (드라이브에 daily_ds.zip 이 없으면 먼저 합침, 20GB 안팎 받음)
python -m vision.pc_train plate      # 번호판 v004 + 평가
python -m vision.pc_train face_eval  # 증명사진 평가
```

중간에 끊기거나 창을 닫아도 같은 명령을 다시 치면 끊긴 epoch 부터 이어서 한다.

## 그래픽카드 보호

- **온도 보호(기본 켬)**: 50 배치마다 온도를 보고 80°C 이상이면 72°C 까지 쉬었다가 이어 간다. `$env:PL_GPU_MAX_TEMP = "75"` 처럼 바꿀 수 있다.
- **전력 제한(선택)**: 관리자 PowerShell 에서 `nvidia-smi -q -d POWER` 로 허용 범위를 보고 `nvidia-smi -pl <와트>` 로 낮춘다.
  재부팅하면 원래대로 돌아간다. 열과 소음이 줄고 학습은 조금 느려진다.
- 학습하는 동안 게임 등 다른 GPU 작업은 하지 않는다. 절전 모드는 꺼 둔다(설정 → 시스템 → 전원).
- 드라이버 오류(화면 멈춤·nvlddmkm)가 나면 바로 멈추고(`Ctrl+C`) 배치를 8 로 낮추거나 전력 제한을 건다.

## 무엇이 어디에 남나

| 결과 | 드라이브 |
|---|---|
| 학습 기록(이어서 하기용) | `objects/runs/<이름>/` |
| 모델 | `objects/daily_v001/`, `objects/plate_v004/` (`best.pt`, `best.onnx`) |
| 평가 | `objects/daily_v001_val.json`, `objects/eval_plate_v004.json`, `objects/eval_face_photo.json` |
| 받은 원본 | `objects/raw/` (다시 받지 않게 보관) |

사진·데이터는 드라이브와 `PL_WORK` 에만 둔다. 저장소에 올리지 않는다.
