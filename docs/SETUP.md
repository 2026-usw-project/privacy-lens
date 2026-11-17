# 설치와 운영

[README](../README.md)의 빠른 시작보다 자세한 내용입니다. 설치(CPU·GPU), 모델 적용, 엔진 서버 늘리기, 배포·https, 환경변수, API 를 다룹니다.
판정 규칙·설계 원칙·측정 기록은 [개발 노트](DEVELOPMENT.md), 처리 흐름은 [아키텍처](ARCHITECTURE.md)에 있습니다.

- [1. 설치](#1-설치)
- [2. 모델 받기·적용](#2-모델-받기적용)
- [3. 실행 구조와 엔진 서버](#3-실행-구조와-엔진-서버)
- [4. 화면 배포와 https](#4-화면-배포와-https)
- [5. 환경변수](#5-환경변수)
- [6. API](#6-api)

## 1. 설치

기본 OCR 엔진은 PaddleOCR이며, 처음 실행할 때 모델 가중치를 내려받습니다. 아래 안내는 **일반 CPython 3.10~3.13**을 기준으로 합니다.
Linux용 PaddlePaddle 3.2.2 패키지는 이 범위의 `x86_64`·`aarch64` 환경에 제공되며, Python 3.14 이상이나 다른 환경에 그대로 적용할 수 없습니다.
패키지 제공 여부는 [공식 CPU 배포 목록](https://www.paddlepaddle.org.cn/packages/stable/cpu/paddlepaddle/)에서 확인할 수 있습니다.

```bash
git clone https://github.com/2026-usw-project/privacy-lens.git
cd privacy-lens
```

아래 명령은 **Python 3.12, x86-64** 기준입니다. ① 가상환경을 만들어 켜고, ② 실행 장치(CPU·NVIDIA GPU)에 맞는 설치 블록 하나를 실행한 뒤, ③ 모델을 받고 실행합니다.

### ① 가상환경 만들기·켜기

**Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

- Ubuntu·Debian에서 `ensurepip is not available` 오류가 나면 `sudo apt install python3.12-venv`로 venv 모듈을 설치한 뒤 다시 만듭니다.
- 새로 설치한 Ubuntu에는 한글 폰트가 없어 `run.py`가 `[실패] 한글 폰트`로 멈춥니다. `sudo apt install fonts-nanum`으로 설치합니다.

**Windows (PowerShell)**

먼저 `python --version`이 3.10~3.13인지 확인합니다. 다른 버전이면 [python.org](https://www.python.org/downloads/)에서 3.12를 설치합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

- `스크립트를 실행할 수 없으므로…`(running scripts is disabled) 오류가 나면 `Set-ExecutionPolicy -Scope Process Bypass`를 실행한 뒤 다시 켭니다. 지금 연 창에만 적용됩니다.
- cmd에서는 `.venv\Scripts\activate.bat`, Git Bash에서는 `source .venv/Scripts/activate`로 켭니다.
- 켜지면 입력줄 앞에 `(.venv)`가 붙습니다. 새 창을 열면 다시 켭니다.

### ② 패키지 설치 — 실행 장치에 맞는 블록 하나

**CPU (Linux·Windows)**

YOLO용 PyTorch를 CPU 빌드로 먼저 설치합니다. 먼저 설치하지 않으면 `requirements.txt`가 기본 PyTorch를 설치하며, Linux에서는 GPU 빌드(수 GB)가 설치됩니다.
다른 플랫폼은 [PyTorch 설치 안내](https://pytorch.org/get-started/locally/)에서 CPU용 명령을 확인하세요.

```bash
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python -m pip install paddlepaddle==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install paddleocr
```

PaddlePaddle 3.3.x 는 CPU 추론이 `NotImplementedError` 로 멈춰서 CPU 는 3.2.2 로 고정합니다.

**NVIDIA GPU (Linux·Windows)**

글자 인식·YOLO·ONNX 를 모두 GPU 로 돌립니다. **드라이버가 CUDA 13.0 이상**을 지원해야 합니다(`nvidia-smi` 오른쪽 위 `CUDA Version`).
CUDA 13 은 Turing(RTX 20 시리즈) 이후 GPU 를 지원하며, 그보다 오래된 GPU 나 드라이버를 올릴 수 없는 PC 는 위의 CPU 설치를 씁니다.

```bash
python -m pip install --upgrade pip
python -m pip install torch==2.12.1 torchvision --index-url https://download.pytorch.org/whl/cu130
python -m pip install -r requirements.txt
python -m pip uninstall -y onnxruntime
python -m pip install onnxruntime-gpu
python -m pip install paddlepaddle-gpu==3.4.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu130/ --extra-index-url https://pypi.org/simple
python -m pip install paddleocr
python -m pip install nvidia-cudnn-cu13==9.20.0.48
```

<details>
<summary><b>왜 이 버전인가 (GPU)</b></summary>

- Paddle 과 PyTorch 는 같은 프로세스에서 cuDNN 등 NVIDIA 라이브러리를 함께 쓰므로 버전이 같아야 합니다. PyTorch 2.12.1 cu130 과 PaddlePaddle 3.4.0 cu130 은 `cuda-toolkit 13.0.2`·cuDNN `9.20.0.48`·cuBLAS 13.1 로 맞습니다. ONNX Runtime 최신판도 CUDA 13·cuDNN 9 를 씁니다.
- **마지막 줄(cuDNN 9.20)**: Windows 판 Paddle 3.4.0 은 cuDNN 9.15 를 고정하는데, Windows 판 PyTorch 2.12.1 은 cuDNN 9.20 을 직접 들고 있어 그대로 두면 `OSError: [WinError 127]`로 멈춥니다. Paddle 쪽을 9.20 으로 맞춥니다. Linux 에서는 이미 9.20 이라 바뀌는 것이 없습니다.
- **`pip check` 가 알리는 한 줄은 정상입니다**: Linux 는 `torch … requires nvidia-nccl-cu13==2.29.7, but you have 2.30.7`(NCCL 은 여러 GPU 통신용, 한 GPU 분석에서는 쓰지 않음), Windows 는 `paddlepaddle-gpu … requires nvidia-cudnn-cu13==9.15.1.9, but you have 9.20.0.48`. 이 한 줄 외의 충돌이 있으면 설치를 다시 확인하세요.
- Paddle 배포 목록에는 `cuda-toolkit` 이 없어서 `--extra-index-url https://pypi.org/simple` 이 꼭 필요합니다.
- PaddlePaddle 은 GPU 에서 **3.4.0**, CPU 에서 3.2.2 를 씁니다. 3.4.0 과 3.2.2 의 글자 인식 결과를 비교하지는 않았습니다.
- CUDA 12 빌드는 Paddle 과 PyTorch 가 cuDNN·NCCL 을 서로 다른 버전으로 고정하고, CUDA 버전이 다른 nvidia 패키지끼리는 같은 파일(`libnccl.so.2`·`libcudnn.so.9`)을 덮어써서 함께 GPU 로 쓸 수 없었습니다. 그래서 GPU 설치는 CUDA 13 하나만 둡니다.
- Windows 에서는 서버가 PyTorch 를 Paddle 보다 먼저 불러옵니다(반대 순서는 `shm.dll` 충돌, `pipeline/ultra.py`).

</details>

> **확인한 환경(2026-11-15)** — 새 가상환경에서 위 명령 그대로 설치한 뒤 `run.py`로 가상 샘플을 분석했습니다. 글자 인식·YOLO(`cuda:0`)·ONNX(`CUDAExecutionProvider`) 모두 GPU.
> Linux: Ubuntu 24.04 · RTX 5070 · 드라이버 615(CUDA 13.4), 두 번째 분석 1.3초.
> Windows: Windows 11 · RTX 3070 Laptop · 드라이버 621(CUDA 13.5), 두 번째 분석 2.3초.
> CPU 설치는 Linux(Ubuntu 24.04, 16코어, 약 3초)·Windows 에서 확인했습니다.

**GPU 사용 확인**

```bash
python -c "import paddle; paddle.utils.run_check(); print(paddle.device.get_device())"
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch, onnxruntime as ort; s = ort.InferenceSession('models/daily.onnx', providers=['CUDAExecutionProvider', 'CPUExecutionProvider']); print(s.get_providers()); assert 'CUDAExecutionProvider' in s.get_providers()"
```

`gpu:0`·`True`·`CUDAExecutionProvider`가 나오면 됩니다. 마지막 명령은 [모델](#2-모델-받기적용)에 따라 `models/daily.onnx`를 둔 뒤 실행합니다.
끝으로 `python run.py --check`가 `[OK]`로 끝나는지 확인합니다(PaddleOCR과 YOLO를 한 프로세스에서 함께 불러옵니다).

### ③ 모델 받기 및 실행

```bash
python -m pipeline.objects download
python run.py
```

[http://127.0.0.1:8000](http://127.0.0.1:8000)에 접속합니다.

- `run.py`는 필요한 패키지, 한글 폰트와 OCR 환경을 점검한 뒤 **게이트웨이**(화면 + 대기열, 8000)와 **엔진 서버 1개**(이 PC 안, 8001)를 함께 띄웁니다. 점검만 하려면 `python run.py --check`.
- **포트가 쓰는 중이면 1 씩 올려 빈 포트로 엽니다.** 바뀌면 콘솔에 알리니, 터널 등이 예전 포트를 가리키면 함께 바꿉니다.
- 화면 상단의 `OCR 엔진 준비 중` 표시가 `엔진 1대 · 대기열 비어 있음`으로 바뀌면 분석을 시작할 수 있습니다.
- HEIC 사진은 `pillow-heif`가 설치된 환경에서 지원합니다.
- 이 문서의 `이름=값 명령`은 bash 문법입니다. PowerShell 에서는 `$env:이름 = "값"; 명령`, cmd 에서는 `set 이름=값` 뒤에 명령을 실행합니다.

### 문제 해결

<details>
<summary><b>Linux에서 No matching distribution found가 발생할 때</b></summary>

pip가 현재 환경과 버전 조건에 맞는 설치 파일을 찾지 못했다는 뜻입니다. 먼저 환경을 확인합니다.

```bash
python --version
uname -m
python -m pip --version
```

- **Python 버전:** 3.14 이상이면 3.10~3.13으로 새 가상환경을 만듭니다. 기존 가상환경의 Python 버전은 pip 업그레이드로 바뀌지 않습니다.
- **CPU·배포판:** 32비트 환경이나 Alpine Linux처럼 musl을 사용하는 환경은 일반 Linux 패키지와 호환되지 않을 수 있습니다. [공식 Linux 설치 조건](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/linux-pip_en.html)을 확인합니다.
- **패키지 저장소:** 지원 환경에서도 오류가 나면 위 설치 명령처럼 공식 CPU 인덱스를 지정합니다. 앞선 로그에 연결·인증서·프록시 오류가 있는지도 확인합니다.

설치 후 `python -c "import paddle; paddle.utils.run_check()"` 로 추론 엔진을 확인할 수 있습니다.

</details>

<details>
<summary><b>Tesseract로 실행하기</b></summary>

[Tesseract와 한국어 데이터](DEVELOPMENT.md#tesseract-설치)를 설치한 뒤 OCR 엔진을 지정합니다.

```bash
PL_OCR=tesseract python run.py
```

</details>

## 2. 모델 받기·적용

모델이 없어도 OCR·판단·가림은 그대로 동작합니다. 모델을 두면 글자가 아닌 것(일상 물건, 문서·카드 영역, 증명사진, 번호판)도 찾습니다.
가중치는 저장소에 올리지 않고 팀 구글 드라이브 `PrivacyLens-YOLO` 에만 둡니다(`models/` 폴더는 git 이 무시합니다).

| 모델 | 받을 곳 | 저장소에 둘 곳 | 서버가 쓰는 방법 |
|---|---|---|---|
| 얼굴·증명사진(YuNet) | OpenCV 공식 저장소 | `models/face_detection_yunet_2023mar.onnx` | `python -m pipeline.objects download` 가 받고 SHA-256 을 확인 |
| 일상 사진 물건(YOLO) | 드라이브 `objects/daily_vNNN/best.onnx` | `models/daily.onnx` | 있으면 문서 모델과 함께 사용(`PL_DAILY_MODEL`) |
| 증명사진 전용(YOLO) | 드라이브 `objects/face_photo_vNNN/best.onnx` | `models/face_photo.onnx` | 있으면 YuNet 보다 먼저 사용(`PL_FACE_PHOTO_MODEL`) |
| 번호판(YOLO) | 드라이브 `objects/plate_vNNN/best.onnx` | `models/plate.onnx` | 있으면 자동 사용(`PL_PLATE_MODEL`) |
| 문서·카드 검출(YOLO) | 드라이브 `models/vNNN/` 의 `best.pt` 와 `metrics.json` | `models/vNNN/` | 가장 큰 번호 폴더를 자동 사용(`PL_YOLO_WEIGHTS` 로 고정) |

각 모델은 경로 변수에 `off` 를 주면 끕니다(문서 검출은 `PL_YOLO=off`). 버전별 성능과 어느 버전을 쓸지는 [vision/README.md](../vision/README.md)와 [이미지 객체 작업 기록](OBJECTS_REPORT.md)을 봅니다.

확인: `python run.py --check` 에서 `얼굴 검출 YuNet (card)`, `번호판 검출 …plate.onnx` 등이 `[OK]` 로 나오면 됩니다. 문서 검출 모델은 분석 화면 하단에 버전이 보입니다.

알아 둘 것

- **시연 서버는 문서 검출 버전을 고정하세요.** 서버는 `models/` 에서 가장 큰 번호 폴더를 그냥 씁니다. 새 폴더를 복사하는 순간 검증 안 된 모델로 바뀔 수 있으니 `PL_YOLO_WEIGHTS=models/vNNN/best.pt` 로 고정합니다(D-14).
- **돌려 찾기는 기본으로 켜져 있습니다.** 회전 정보가 지워진 누운 사진에서 놓침이 크게 줄지만 얼굴·번호판 검출 시간이 약 3배입니다. `PL_PLATE_ROTATE=0`, `PL_FACE_ROTATE=0` 으로 끕니다(D-18).
- **서버는 Ultralytics 자동 설치를 끕니다**(`YOLO_AUTOINSTALL=false`). 검출 패키지를 먼저 설치해야 하고, 빠졌으면 `run.py --check` 가 알려 줍니다.
- **CPU 로도 충분합니다.** 작은 YOLO(n) 는 Ryzen 9 5900HS CPU 에서 사진 한 장 0.13~0.17초로 OCR(약 7초)보다 훨씬 짧습니다.

## 3. 실행 구조와 엔진 서버

```
사용자 ──▶ 게이트웨이(화면 + 대기열 + 분산 + 상태 확인) ──▶ 엔진 서버 1..N (1 서버 1 엔진)
```

엔진(OCR) 하나가 CPU 를 거의 다 쓰므로, 한 PC 에서 작업자를 늘리기보다 **엔진 서버를 PC 마다 하나씩** 두고 게이트웨이가 나눠 보냅니다(D-20).
`run.py`는 이 구조를 한 PC 에서 엔진 1개로 띄운 것입니다.

| 스크립트 | 하는 일 | 주요 옵션 |
|---|---|---|
| `run.py` | 환경 점검 → 엔진 서버 1개(이 PC 안) + 게이트웨이 | `--check` `--samples`, 환경변수 `HOST` `PORT` `PL_ENGINE_PORT` `PL_GATEWAY_TOKEN` `PL_ADMIN_KEY` |
| `run_gateway.py` | 게이트웨이만. OCR·모델이 필요 없습니다. | `--backend`(여러 번) `--token` `--admin-key` `--host` `--port` `--no-front` `--cors` `--ssl-cert` `--ssl-key` `--queue-max` |
| `run_backend.py` | 엔진 서버만(화면 없음) | `--host` `--port` `--token` `--cors` `--check` |

- **대기열은 게이트웨이에 하나**입니다. 들어온 순서대로, 비어 있는 엔진이 생길 때 한 건씩 보냅니다. 차례가 안 된 요청에는 게이트웨이가 '앞에 N건 · 약 N초'를 알려 줍니다.
- **번호표마다 엔진을 고정**합니다. 분석을 맡은 엔진이 그 번호표의 진행 상황·취소도 맡습니다.
- **상태 확인**: 5초마다 엔진의 `/health` 를 묻습니다. 연결 거부는 바로, 늦음·오류는 두 번 연속일 때 뺍니다. 살아나면 다시 넣고, 처리 전에 연결이 안 되면 다른 엔진에 다시 보냅니다.
- **엔진 토큰은 선택 사항입니다.** 엔진에 `--token`(또는 `PL_GATEWAY_TOKEN`)을 설정하면 같은 값을 보낸 요청만 처리합니다. 다른 PC 의 엔진을 붙일 때는 꼭 설정합니다.
- 사진은 메모리에서만 엔진으로 넘기고 디스크·로그에 남기지 않습니다. 양쪽 콘솔에는 연결 요청·수락·거절·끊김만 남습니다.

### 화면에서 엔진 더하고 빼기

화면 오른쪽 위의 `엔진 N대` 칩이나 왼쪽 메뉴의 **분석 엔진**을 누르면 엔진 목록이 열립니다. 주소를 넣어 **추가**하고, **X** 로 빼고, 끌어서 순서를 정합니다(맨 위 엔진이 먼저 맡음).

- **관리 키가 있어야 합니다.** 게이트웨이를 켜면 콘솔에 `엔진 관리 키(이번 실행에만): …`가 나옵니다. 고정하려면 `PL_ADMIN_KEY`(또는 `--admin-key`)를 정합니다. 화면은 키를 저장하지 않습니다.
- 바꾼 목록은 메모리에만 있습니다. 게이트웨이를 다시 켜면 실행 옵션의 목록으로 돌아갑니다.

### 엔진 서버 여러 대로 늘리기

```bash
# 엔진 PC 마다
python run_backend.py --host 0.0.0.0 --token <비밀값>
# 게이트웨이 PC (엔진 주소를 --backend 로 여러 번)
python run_gateway.py --host 0.0.0.0 --backend http://192.168.0.21:8000 --backend http://192.168.0.22:8000 --token <비밀값>
```

사용자는 게이트웨이 주소(`http://<게이트웨이 IP>:8000`)로 접속합니다. 같은 PC 에서 따로 띄울 때는 엔진에 `--port 8001`, 게이트웨이에 `--backend http://127.0.0.1:8001` 을 줍니다.
`run.py` 를 쓰면서 엔진만 더하려면 `HOST=0.0.0.0 PL_GATEWAY_TOKEN=<비밀값> python run.py` 로 켜고 화면에서 엔진 주소를 추가합니다.

## 4. 화면 배포와 https

### 화면을 정적 배포로 올리기

GitHub Pages·Netlify 같은 곳에 화면만 올리고, 게이트웨이는 API 만 냅니다.

```bash
cd web/frontend-demo && node scripts/build.mjs --api https://<게이트웨이 주소>
python run_gateway.py --host 0.0.0.0 --no-front --cors https://<화면 주소> --backend http://<엔진>:8000 --token <비밀값>
```

- `build.mjs --api` 가 `web/frontend-demo/site/`(`index.html` + `dist/fonts/` + `.nojekyll`)를 만듭니다. 이 폴더를 그대로 올립니다(`--out` 으로 위치 변경, 커밋하지 않음).
- 화면이 https 면 게이트웨이도 https 여야 합니다. PC 웹캠·휴대폰 카메라도 https(또는 localhost)에서만 됩니다.

### 게이트웨이를 https 로 열기

| 방법 | 언제 | 사진이 지나는 길 |
|---|---|---|
| **A. Caddy 앞단** (`deploy/Caddyfile`) | 도메인이 있고 80·443 포트를 열 수 있을 때. 인증서 자동 발급·갱신 | 이 PC 에서 암호가 풀립니다 |
| **B. 게이트웨이가 직접** (`--ssl-cert`, `--ssl-key`) | 인증서 파일이 있을 때. 교내망 시연은 `mkcert` | 이 PC 에서 암호가 풀립니다 |
| **C. Cloudflare Tunnel** (`cloudflared tunnel --url http://127.0.0.1:8000`) | 도메인·포트 개방 없이 바로 https 가 필요할 때 | **Cloudflare 에서 암호가 풀립니다.** 가상 사진 시연에만 씁니다 |

```bash
# A. Caddyfile 의 도메인을 바꾼 뒤
python run_gateway.py --backend http://<엔진>:8000 --token <비밀값>
caddy run --config deploy/Caddyfile
# B.
python run_gateway.py --host 0.0.0.0 --port 8443 --ssl-cert cert.pem --ssl-key key.pem --backend http://<엔진>:8000 --token <비밀값>
```

- C 의 임시 주소는 실행할 때마다 바뀌므로, 정적 배포보다 게이트웨이가 화면을 내주는 방식과 같이 쓰는 편이 편합니다.
- 인증서·개인 키 파일은 저장소에 넣지 않습니다(`*.pem` 은 무시 목록에 있습니다).

## 5. 환경변수

설정은 저장소 맨 위 `.env` 파일에 모아 둘 수 있습니다(`cp .env.example .env`). `run.py`·`run_backend.py`·`run_gateway.py`·`server.py` 가 켤 때 읽고, 셸에서 준 값이 이깁니다.
다른 위치는 `PL_ENV_FILE` 로 지정합니다. `.env` 는 커밋되지 않습니다. 값을 바꾸면 서버를 다시 켜야 적용됩니다.

**실행·연결**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `HOST` | `127.0.0.1` | `run.py` 게이트웨이 주소. `0.0.0.0` 이면 다른 기기에서 접속 |
| `PORT` | `8000` | `run.py` 게이트웨이 포트(`run_backend.py` 는 엔진 포트). 쓰는 중이면 1 씩 올림 |
| `PL_ENGINE_PORT` | 게이트웨이 다음 번호 | `run.py` 가 이 PC 안에 띄우는 엔진 포트 |
| `PL_GATEWAY_TOKEN` | 없음 | 게이트웨이 ↔ 엔진 공유 비밀값(`--token`) |
| `PL_ADMIN_KEY` | 실행마다 새로 | 화면에서 엔진을 더하고 뺄 때 쓰는 관리 키 |
| `PL_BACKENDS` | 없음 | `run_gateway.py` 엔진 목록(쉼표로 여러 개) |
| `PL_CORS_ORIGINS` | 없음 | 화면을 따로 올렸을 때 그 주소(쉼표로 여러 개) |
| `PL_SSL_CERT` · `PL_SSL_KEY` | 없음 | 게이트웨이 https 인증서·키 |
| `PL_SERVE_FRONT` | `1` | `0` 이면 엔진 서버가 화면을 내주지 않고 API 만 |
| `PL_QUEUE_MAX` | `12` | 엔진 한 대의 최대 대기 요청 수. 초과 시 503 |
| `PL_GATEWAY_QUEUE_MAX` | `24` | 게이트웨이 대기열 최대 요청 수(`--queue-max`) |
| `PL_ENV_FILE` | `.env` | 읽을 설정 파일 경로 |
| `PL_TIMING` · `PL_TIMING_PATH` | `on` · `~/.privacy-lens/timing.json` | 단계별 걸린 시간 기록(숫자만, D-17). `off` 면 메모리에만 |

**OCR**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PL_OCR` | `paddleocr` | `tesseract` 또는 `none`(글자 OCR 생략) |
| `PL_PADDLE_LANG` | `korean` | PaddleOCR 인식 언어 |
| `PL_PADDLE_DET` | `PP-OCRv6_medium_det` | 검출 모델. `auto`는 언어별 기본 모델 |
| `PL_PADDLE_REC` | 언어별 기본 모델 | 한국어 기본은 `korean_PP-OCRv5_mobile_rec` |
| `PL_PADDLE_TEXTLINE` | `auto` | 글자 줄 방향 판별. `auto`·`on`·`off`. [개발 노트](DEVELOPMENT.md#글자-줄-방향-판별-2026-11-04-pl_paddle_textline) |
| `PL_PADDLE_THREADS` | PaddleOCR 기본 | 엔진 하나가 쓰는 CPU 스레드 수 |
| `PL_TESSERACT` | 자동 탐색 | Tesseract 실행 파일 경로 |

**물건·얼굴·번호판 검출**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PL_DAILY_MODEL` | `models/daily.onnx` 가 있으면 그것 | 일상 사진 물건 모델 경로, `off` 면 끔 |
| `PL_DAILY_IMGSZ` | `640` | 일상 모델 입력 크기 |
| `PL_DAILY_TILES` | `0`(끔) | `2` 면 큰 사진을 겹친 4조각으로 한 번 더 검출(작게 찍힌 물건용, 효과 측정 전) |
| `PL_YOLO_WEIGHTS` | `models` 에서 자동 | 문서 검출 가중치. 미설정이면 `models/v숫자` 중 가장 큰 폴더의 `best.pt`, 없으면 `models/best.pt` |
| `PL_YOLO` | `on` | `off` 면 문서 검출을 끔 |
| `PL_YOLO_IMGSZ` | `metrics.json` 의 값, 없으면 1280 | 문서 검출 입력 크기 |
| `PL_YOLO_CONF` | `0.6` | 문서·일상 검출 기준값. v012 기준으로 정한 값이라 v010 이하에서는 놓침이 늘어남(v010 은 `0.35`) |
| `PL_FACES` | `card` | 얼굴 검출. `card`(증명사진만) · `all`(모든 얼굴 검토 권장) · `off`(D-18) |
| `PL_FACE_MODEL` | `models/face_detection_yunet_2023mar.onnx` | YuNet 얼굴 모델 경로 |
| `PL_FACE_ROTATE` | `1` | 얼굴을 90·270도 돌려서도 찾음(검출 시간 약 3배) |
| `PL_FACE_PHOTO_MODEL` | `models/face_photo.onnx` 가 있으면 그것 | 증명사진 전용 모델 경로, `off` 면 끔 |
| `PL_FACE_PHOTO_ROTATE` | `0` | 증명사진 전용 모델도 돌려서 찾음 |
| `PL_PLATE_MODEL` | `models/plate.onnx` 가 있으면 그것 | 번호판 모델 경로, `off` 면 끔 |
| `PL_PLATE_ROTATE` | `1` | 번호판을 90·270도 돌려서도 찾음(검출 시간 약 3배) |

**판단**

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PL_UNLABELED_NAMES` | `context` | 라벨 없는 이름. `off`(라벨 뒤 이름만) · `context`(연락처·주소·명찰 단서가 있을 때) · `all`(오탐 증가). [D-12](DECISIONS.md#d-12-가림-기준표-확정) |
| `PL_JUDGE_PROVIDER` | `rules` | 서버 기본 판단 모델(D-22). `rules`·`openai`·`gemini`·`gemini_decision`·`anthropic`·`openrouter`·`ollama`·`custom`. 판단 모델 설정을 저장한 적 없는 사용자의 화면이 이 값으로 시작 |
| `PL_JUDGE_MODEL` | 없음 | 기본 판단 모델 이름(`rules` 가 아니면 필수) |
| `PL_JUDGE_REASONING` | `auto` | 추론 정도. 공급자별 허용 값은 `.env.example` |
| `PL_JUDGE_FAST` | `false` | 빠른 처리(요금 추가, `openai`·`anthropic`) |
| `PL_JUDGE_API_KEY` | 없음 | 서버 API 키. 화면으로 내려가지 않고 로그에 남지 않습니다. **모든 사용자의 OCR 원문이 그 회사로 가고 요금이 이 키로 나갑니다** |
| `PL_JUDGE_BASE_URL` | 없음 | `ollama`(기본 `http://127.0.0.1:11434`)·`custom` 주소(엔진 서버 기준) |

모델 선택과 버전별 동작은 [OCR 엔진 교체 안내](DEVELOPMENT.md#ocr-엔진-교체)를 참고하세요.

## 6. API

| 메서드 | 경로 | 용도 |
|---|---|---|
| `POST` | `/analyze` | 사진 분석 |
| `POST` | `/redact/preview` | 가림 처리 미리보기 |
| `POST` | `/redact` | 가림 처리 · 메타데이터 제거 · JPEG 반환 |
| `GET` | `/queue` | 대기열 상태(게이트웨이 뒤면 엔진 수 포함) |
| `POST` | `/queue/cancel` | 대기 요청 취소 |
| `GET` | `/progress` | 번호표별 진행 상황(SSE) |
| `GET` | `/health` | 살아 있는지 · 엔진 준비 여부 |
| `GET` | `/judge/default` | 서버 기본 판단 모델(키 값은 내려보내지 않음, D-22) |
| `POST` | `/llm/models` | 판단 모델 창의 공급자 모델 목록 |
| `GET` · `POST` | `/admin/engines`, `/admin/engines/remove`, `/admin/engines/order` | 게이트웨이 엔진 목록 보기·추가·제거·순서(관리 키 필요) |

요청 필드와 응답 형식은 [API 계약 문서](../web/frontend-demo/API_CONTRACT.md)에 정리되어 있습니다.
