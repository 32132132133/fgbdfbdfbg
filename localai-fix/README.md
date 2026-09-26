# 로컬 AI 오류 수정 (2026-09-26 로그 기준)

`ollama-serve.log`, `webui.log`, `mcpo.log`, `llama-server.log`에서 에러와 모델 로드 기록만 보고 정리했습니다. 대화 내용(webui.db, summaries, memory)은 보지 않았습니다.

## 원인

### 1. 압축할 때마다 모델이 VRAM에서 내려감 ← 맞습니다
`ollama-serve.log`에 32K 모델과 `task-model`(CPU용 2B)이 번갈아 올라온 기록이 있습니다.

```
16:48:53  qwen-heretic-32k 로드
17:04:37  task-model 로드  ← 32K 모델이 내려감 (로그의 "llama-server terminated"는 이 언로드)
17:08:24  qwen-heretic-32k 다시 로드 (약 11GB)
17:10:07  task-model 로드
17:12:27  qwen-heretic-32k 다시 로드
17:15:52  task-model 로드
17:17:53  qwen-heretic-32k 다시 로드
```

- `OLLAMA_MAX_LOADED_MODELS=1`로 되어 있어서, task-model이 CPU 전용인데도 한 번에 모델 하나만 둘 수 있습니다. 그래서 메인 모델을 내리고 task-model을 올립니다.
- Open WebUI 기본 "컨텍스트 압축"은 요약을 task-model에게 시킵니다. 그런데 task-model의 문맥이 4096이라 입력이 잘립니다(`truncating input prompt limit=2050 prompt=4535`). 그래서 **요약 품질도 나쁩니다.**
- 17:04에 32K 모델이 내려가고 17:08에 다시 올라올 때까지 약 4분이 걸렸습니다.

### 2. `No user query found in messages` (500), 그리고 "이전 응답에 에러가 있었던 것 같습니다" 후 이어지지 않음
Qwen 모델에 내장된 채팅 템플릿은 메시지 안에 **사용자 질문이 하나도 없으면** 에러를 냅니다. 사용자 질문이 사라지는 경로는 두 가지입니다.
- Open WebUI 기본 압축이 `dropped=4 kept=2`처럼 최근 2개만 남깁니다. 도구를 연속으로 쓰는 중이면 그 2개가 도구 호출과 도구 결과뿐이라 질문이 빠집니다. 17:08:31 압축 직후 17:09:08에 에러가 났습니다.
- `auto_summary` 필터는 자르는 지점 뒤에 사용자 메시지가 없으면 자르는 지점을 마지막 메시지까지 밀어서, 질문까지 요약에 넣어 버립니다.

한 번 이렇게 되면 그 채팅은 매번 같은 에러가 납니다. 17:09:08과 17:09:40에 같은 에러가 반복됐고, 17:34:46에도 다시 났습니다.

### 3. 문맥 초과 `33842 > 32768`
- 도구 결과를 받고 이어서 답을 만드는 단계에서 32K를 넘었습니다.
- `extras` 도구의 결과 한도가 24,000자라서 한국어로는 결과 하나가 2만 토큰 가까이 됩니다.
- `auto_summary`는 토큰을 글자 수의 0.6배로 계산해서 한국어를 적게 셉니다. `ctx_map`에 `32k`, `262k`가 없어서 32K/262K 모델을 12K로 봅니다.

### 4. 압축이 세 개 겹쳐 있음
Open WebUI 기본 압축, `auto_summary`, `context_guard`가 동시에 돕니다. 서로 다른 기준으로 대화를 자르고 있습니다.

### 5. `start-llama-server.bat`는 실행 자체가 안 됨
- 새 llama.cpp에서는 `-fa`에 값이 필요합니다(`-fa on`).
- Ollama 폴더의 llama-server를 따로 실행하면 CUDA를 못 불러와 CPU로만 돕니다.
- 8000번 포트를 쓰는 다른 프로그램과 부딪힙니다.

### 6. 그 밖에
- `update-localai.ps1`이 이미 안 쓰는 옛 무검열 모델(14GB)을 다시 받습니다.
- `WEBUI_SECRET_KEY`가 스크립트에 그대로 적혀 있습니다.
- `find_files` 도구에 PowerShell 명령을 끼워넣을 수 있습니다.
- 보호 폴더 검사를 `..` 경로로 우회할 수 있습니다.

## 수정 내용

| 파일 | 수정 |
|---|---|
| `start-localai.ps1` | `OLLAMA_MAX_LOADED_MODELS` 1 → **2** (task-model은 CPU·RAM에 따로 상주하고 메인 모델은 VRAM에 계속 남음). 비밀키는 처음 실행할 때 새로 만들어 `webui-data\.webui_secret_key`에 저장 |
| `task-model.Modelfile` | `num_ctx` 4096 → 8192 (제목·태그 생성 입력이 잘리지 않게) |
| `extras/server.py` | 결과 한도 24,000 → 8,000자. `find_files` 명령 끼워넣기 차단. 보호 폴더를 실제 경로(`..` 풀어서)로 검사 |
| `webbrowser/server.py` | 결과 한도 14,000 → 8,000자 |
| `windows/server.py` | 보호 폴더 검사 전에 `폴더\..` 형태를 풀어서 검사 |
| `start-llama-server.bat` | `-fa on`, Ollama CUDA 백엔드 불러오기, 포트 8001, 모델 파일이 없으면 Heretic GGUF로 대체 |
| `update-localai.ps1` | 옛 모델 다시 받기 삭제. heretic 16/32/64/262K와 task-model을 다시 만들도록 변경 |
| `openwebui-functions/context_guard.py` | 사용자 질문이 없으면 이어가기 지시를 넣음(2번 에러 차단). 시스템 메시지는 맨 앞에 합침 |
| `openwebui-functions/auto_summary.py` | 사용자 질문은 요약하지 않음. `ctx_map`에 16/32/64/262K 추가. 한국어 토큰 추정 보정. 시스템 메시지는 맨 앞에 합침 |

## 적용 방법

1. 이 `localai-fix` 폴더를 PC에 받습니다.
2. PowerShell에서 실행합니다.
   ```powershell
   cd <받은 폴더>\localai-fix
   powershell -ExecutionPolicy Bypass -File .\apply-fix.ps1
   ```
   바뀌는 파일은 모두 `*.bak-날짜` 파일로 백업됩니다.

### Open WebUI에서 할 일 (스크립트로 못 하는 부분)
1. **관리자 패널 → 함수(Functions)**
   - `context_guard`: 코드를 `openwebui-functions/context_guard.py` 내용으로 바꾸고 저장합니다.
   - `auto_summary`: 코드를 `openwebui-functions/auto_summary.py` 내용으로 바꾸고 저장합니다.
   - 각 함수의 **밸브(Valves)**에 예전 값이 저장돼 있으면 코드 기본값이 적용되지 않습니다. `ctx_map`과 `tokens_per_char`를 기본값으로 초기화하세요.
2. **Open WebUI 기본 "컨텍스트 압축(Context Compaction)" 끄기** (관리자 설정)
   - 압축은 `auto_summary`(메인 모델로 GPU에서 요약)와 `context_guard`(최종 안전장치) 두 개만 씁니다.
   - 메뉴 이름은 버전에 따라 다를 수 있습니다. 못 찾으면 버전을 알려주세요.
3. 이미 에러가 나서 멈춘 채팅은 **새 채팅**으로 시작하세요. 기존 채팅에는 잘못된 압축 기록이 남아 있습니다.

### 적용 후 확인
- 긴 대화에서 압축이 된 뒤 `ollama ps`를 실행해 `qwen-heretic-32k`와 `task-model`이 **둘 다** 떠 있으면 정상입니다.
- `ollama-serve.log`에 `loading model ... f8babfae`(32K 메인 모델)가 한 번만 나와야 합니다.

## 16 / 32 / 64 / 262K 비교 (RTX 5070 Ti 16GB, 로그 수치로 계산)

네 모델은 **같은 GGUF 파일**(IQ3_S, 가중치 11.3GB)이고 문맥 크기만 다릅니다.
- 이 모델은 64층 중 16층만 어텐션이라 KV 캐시가 작습니다. q8_0 기준으로 **1K 토큰당 약 34MB**입니다.
- Ollama는 사용 가능한 VRAM 14.9GB에서 1.6GB(화면용 여유 1.5GB 포함)를 남기고 모델을 배치합니다.

| 모델 | KV 캐시 | 예상 VRAM | 결과 | 비고 |
|---|---|---|---|---|
| 16K | 0.5 GB | 약 12.2 GB | 전부 GPU | 도구 설명과 시스템 프롬프트만으로도 빠듯해서 도구 작업엔 부족 |
| **32K** | 1.1 GB | **12.7 GB (로그 실측)** | 전부 GPU, 약 41 tok/s | **도구·PC 작업 기본값으로 가장 적합** |
| 64K | 2.2 GB | 약 13.8 GB | 여유가 1.6GB보다 적어 **일부 층이 CPU로 감** → 느림 | 예전 64K 벤치: CPU 18% / GPU 82%, 약 10 tok/s |
| 262K | 8.7 GB | 약 20 GB | VRAM보다 커서 **많은 층이 CPU로 감** → 매우 느림 | 16GB 카드에서는 어쩔 수 없음 |

- **모델을 바꿀 때마다 새로 로드됩니다.** 같은 파일이어도 문맥 크기가 다르면 Ollama는 다른 모델로 봅니다. 한 채팅에서는 모델 하나만 쓰세요.
- 64K를 전부 GPU에 올리고 싶다면 `start-localai.ps1`의 `OLLAMA_KV_CACHE_TYPE`를 `q4_0`으로 바꾸는 방법이 있습니다. KV 캐시가 절반이 되어 64K가 지금 32K와 같은 크기가 됩니다. 다만 모든 모델에 적용되고 긴 문서 정확도가 조금 떨어질 수 있어서 **이번 수정에는 넣지 않았습니다.** 실험해 볼 만합니다.
- 262K는 `start-llama-server.bat`처럼 llama-server를 직접 돌리는 편이 낫습니다(KV K=q8, V=q4, `--cache-ram`).

## 직접 해야 하는 보안 조치
- 바탕화면 전체를 `http.server`와 cloudflared로 공개하고 있었습니다. **다 쓴 뒤에는 둘 다 끄세요.**
- 공개되는 동안 다음 파일들도 노출됐습니다. 새로 발급하거나 로그아웃하세요.
  - `local\share\opencode\auth.json`의 키
  - Jupyter 토큰
  - 자동화 크롬 프로필(`LocalAI\webbrowser\profile`)에서 로그인해 둔 사이트
- 옛 `WEBUI_SECRET_KEY`는 이번 수정에서 자동으로 새 키로 바뀝니다.
