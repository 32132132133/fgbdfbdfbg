# 로컬 AI 종합 개선 (기능은 그대로)

2026-09-26 로그(`ollama-serve.log`, `webui.log`, `mcpo.log`, `llama-server.log`)를 분석해서 만들었습니다. 대화 내용(webui.db의 채팅, summaries, memory)은 보지 않았고, 스크립트도 대화 테이블은 건드리지 않습니다.

## 실행

```powershell
cd <받은 폴더>\localai-fix
powershell -ExecutionPolicy Bypass -File .\improve-localai.ps1          # 적용 + 자동 검증
powershell -ExecutionPolicy Bypass -File .\improve-localai.ps1 -Bench   # 적용 + 16/32/64/262K 측정 (10~20분 추가)
```

| 옵션 | 하는 일 |
|---|---|
| (없음) | 백업 → 교체 → 설정 반영 → 켜기 → 검증. 실패하면 "이번 실행 전 상태로 되돌릴까요?"라고 물어봄 |
| `-Bench` / `-BenchOnly` | 16/32/64/262K를 하나씩 올려서 GPU 비율, VRAM, 로드 시간, 입력·생성 속도를 측정. 결과는 `LocalAI\bench-variants.log`. `-BenchOnly`는 아무것도 안 바꾸고 측정만 |
| `-Rollback` | **처음 적용하기 전 원래 상태**로 전부 되돌림. 특정 백업으로 가려면 `-From improve-날짜` |
| `-NoMcpoKey` | 도구 서버 인증키를 걸지 않음 (설치된 mcpo가 키 옵션을 모르는 경우) |
| `-InstallUvTools` | mcpo, time, fetch를 `uv tool`로 설치해서 실행 파일 경로를 고정 (인터넷 필요) |
| `-SkipModelTest` | 적용 후 32K 모델과 task-model이 함께 뜨는지 확인하는 단계(약 1분)를 생략 |
| `-Yes` | 확인 질문 없이 진행 |

- 백업 위치: `LocalAI\_backup\improve-날짜\` (파일과 webui.db 포함)
- 실행 결과 요약: `LocalAI\improve-report.txt`

## 스크립트가 하는 일

| 단계 | 내용 |
|---|---|
| 0 사전 점검 | Ollama와 파이썬이 있는지 확인. 분석한 뒤에 직접 고친 파일이 있으면 알려주고 물어봄 |
| 1 백업 | 로컬 AI를 끄고, 바꿀 파일 전부와 DB를 백업 |
| 2 파일 교체 | 아래 "고친 것" 표 |
| 3 도구 서버 | 인증키(`LocalAI\.mcpo_key`)를 만들고 `tool-servers.json`에 반영 |
| 4 Open WebUI DB | `context_guard`와 `auto_summary` 코드 교체 + 밸브 초기화. 기본 "컨텍스트 압축" 끄기(DB 설정, 그리고 필요하면 환경변수 `webui-env.ps1`). DB에 저장된 도구 서버 연결에 인증키 반영. **채팅 테이블은 열지 않음** |
| 5 켜기 | 로컬 AI를 켜고 task-model을 다시 만듦 |
| 6 검증 | 포트 11434, 8765, 8080, 8890 응답 / 키 있는 도구 호출 성공 / 키 없는 호출 거부 / 게이트웨이 경유 호출 / 필터 검사 17개 / **32K 모델과 task-model 동시 상주** / 32K 모델 100% GPU |

## 원인과 고친 것

### 압축할 때마다 모델이 VRAM에서 내려감
- **원인:** `OLLAMA_MAX_LOADED_MODELS=1`이라서, 제목·요약용 task-model(CPU 전용)이 올라올 때마다 11GB 메인 모델을 내렸습니다. 로그에서 17:04, 17:10, 17:15에 내리고 17:08, 17:12, 17:17에 다시 올렸습니다.
- **수정:** `MAX_LOADED_MODELS=2`. task-model은 RAM에, 메인 모델은 VRAM에 계속 남습니다.
- **수정:** `KEEP_ALIVE`를 15분에서 60분으로 늘렸습니다. 제어판의 [GPU 메모리 비우기]는 그대로 동작합니다.

### "이런! 이전 응답에 에러가 있었던 것 같습니다" + 이어지지 않음 (`No user query found in messages`)
- **원인:** 압축하면서 사용자 질문이 메시지에서 빠졌습니다. 두 경로가 있었습니다.
  - Open WebUI 기본 압축이 최근 2개(도구 호출·결과)만 남겼습니다.
  - `auto_summary`가 도구 루프 중에는 질문까지 요약에 넣었습니다.
- 한 번 이렇게 되면 그 채팅은 계속 같은 에러가 났습니다.
- **수정:** 기본 압축을 끄고, `auto_summary`는 질문을 절대 요약하지 않게 했습니다. `context_guard`는 마지막 안전장치로, 질문이 없으면 이어가기 지시를 넣습니다. 시스템 메시지는 맨 앞에만 둡니다.

### 문맥 초과 (`33842 > 32768`)
- **원인:** 도구 결과 한 개가 최대 24,000자였습니다. `auto_summary`는 한국어 토큰을 적게 셌고(0.6/글자), 32K/262K 모델을 12K로 잘못 봤습니다.
- **수정:** 도구 결과 한도를 8,000자로 줄였습니다. 토큰 추정을 `context_guard`와 같은 방식으로 맞췄고, 16/32/64/262K를 모두 인식하게 했습니다.

### 그 밖의 오류
- **`start-llama-server.bat`:** `-fa on`으로 고치고, Ollama의 CUDA 백엔드를 불러오게 하고(원래는 CPU로만 돌았음), 포트를 8001로 바꿨습니다. 옛 모델 파일이 없으면 Heretic GGUF로 대체합니다.
- **`update-localai.ps1`:** `uv cache clean`이 mcpo와 도구의 실행 파일 경로를 지워서, 업데이트 후 켜지지 않을 수 있었습니다. 이 줄을 없앴습니다. 이미 안 쓰는 옛 모델(14GB) 다시 받기도 없앴고, heretic 4종과 task-model을 다시 만들도록 바꿨습니다. 업데이트 전에 DB를 백업합니다.
- **`start-localai.ps1`:** mcpo 경로가 사라져도 찾아서 실행합니다. 로그는 켤 때마다 `*.prev.log`로 한 번 보관합니다. 비밀키는 파일로 옮겼습니다.

### 안전
- **도구 서버 인증키:** 키 없는 프로그램이나 웹페이지는 PowerShell 같은 PC 조작 도구를 부를 수 없습니다. Open WebUI, 게이트웨이, `bench\run.py`는 키를 자동으로 씁니다.
- **`find_files`:** 작은따옴표로 PowerShell 명령을 끼워넣는 것을 막았습니다.
- **보호 폴더:** `local\..\project`처럼 우회하는 경로를 풀어서 검사합니다(`extras`, `windows`).

### 바뀌지 않는 것 (기능 유지)
모델 5종(16/32/64/262K, 작업용), 이미지 입력, 도구 8종 42개, 게이트웨이의 tool_search/tool_call, 스킬, 기억, 문서 변환, 검색, 영상·음악 생성기, 제어판 버튼은 그대로입니다. 압축도 계속 합니다. 다만 메인 모델이 GPU에서 합니다.

## 16 / 32 / 64 / 262K (RTX 5070 Ti 16GB, 로그 수치로 계산)

네 모델은 같은 GGUF 파일(IQ3_S, 11.3GB)이고 문맥 크기만 다릅니다. KV 캐시는 q8 기준 1K 토큰당 약 34MB입니다(64층 중 어텐션 16층).

| 모델 | 예상 VRAM | 예상 결과 |
|---|---|---|
| 16K | 약 12.2 GB | 전부 GPU. 도구 설명만으로도 빠듯해서 도구 작업엔 부족 |
| **32K** | **12.7 GB (실측)** | **전부 GPU, 약 41 tok/s. 기본으로 가장 적합** |
| 64K | 약 13.8 GB | 여유 1.6GB 규칙에 걸려 일부 층이 CPU로 감 → 느림 |
| 262K | 약 20 GB | VRAM을 넘어서 CPU 비중이 큼 → 매우 느림 |

- 실제 수치는 `-Bench`로 측정하세요.
- 모델을 바꿀 때마다 새로 로드됩니다. 한 채팅에서는 모델 하나만 쓰세요.
- 64K를 전부 GPU에 올리는 방법으로 `OLLAMA_KV_CACHE_TYPE=q4_0`이 있습니다. 모든 모델에 적용되고 긴 문서 정확도가 조금 떨어질 수 있어서 이번에는 넣지 않았습니다.

## 직접 해야 하는 것
- **바탕화면을 공개하던 `http.server`와 cloudflared를 끄세요.**
- 노출됐던 키를 새로 발급하세요: `local\share\opencode\auth.json`의 키, Jupyter 토큰, 자동화 크롬 프로필에서 로그인해 둔 사이트.
- 에러로 멈췄던 예전 채팅은 새 채팅으로 시작하세요.
- Open WebUI를 업데이트했다면 루프 감지 패치를 다시 적용하세요(사용법.txt).
