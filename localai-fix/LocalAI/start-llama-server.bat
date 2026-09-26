@echo off
chcp 65001 > nul
setlocal

set "LLAMA_SERVER=%LOCALAPPDATA%\Programs\Ollama\lib\ollama\llama-server.exe"
set "MODEL=%USERPROFILE%\.ollama\models\blobs\sha256-2bdecffabba9fedd93f383ce834b2d185db32a7fa0cc6cddbbadcf56097cd4ae"
rem 예전 모델 파일이 지워졌으면 지금 쓰는 Heretic GGUF 로 대신 실행
if not exist "%MODEL%" set "MODEL=%USERPROFILE%\LocalAI\gguf\Qwen3.8-27B-Heretic-RVN-IQ3_S-multilingual.gguf"
rem Ollama 폴더의 llama-server 는 CUDA 백엔드를 따로 불러와야 GPU 를 씀 (안 하면 "no usable GPU found" 로 CPU 실행)
set "OLLAMA_LIB=%LOCALAPPDATA%\Programs\Ollama\lib\ollama"
for /d %%D in ("%OLLAMA_LIB%\cuda_v*") do if exist "%%D\ggml-cuda.dll" set "CUDA_DIR=%%D"
if defined CUDA_DIR (
    set "PATH=%CUDA_DIR%;%OLLAMA_LIB%;%PATH%"
    set "GGML_BACKEND_PATH=%CUDA_DIR%\ggml-cuda.dll"
) else (
    echo [경고] Ollama CUDA 백엔드를 못 찾음 - CPU 로 실행될 수 있습니다.
)
set "TEMPLATE=%USERPROFILE%\LocalAI\chat_template.jinja"

echo ================================================================
echo   Qwen 3.8 27B - 262K 풀 컨텍스트 모드 (llama-server 직접 구동)
echo   GPU: RTX 5070 Ti 16GB ^| RAM 캐시: 16GB ^| KV: K=q8 V=q4
echo   템플릿: froggeric 고정 패치 (무한생각 루프 차단)
echo   API: http://127.0.0.1:8001 (OpenAI 호환)
echo ================================================================
echo.

if not exist "%LLAMA_SERVER%" (
    echo [오류] llama-server.exe 를 찾을 수 없습니다.
    echo 경로: %LLAMA_SERVER%
    pause & exit /b 1
)
if not exist "%MODEL%" (
    echo [오류] 모델 GGUF 파일을 찾을 수 없습니다.
    pause & exit /b 1
)
if not exist "%TEMPLATE%" (
    echo [경고] chat_template.jinja 없음 - 기본 템플릿으로 실행합니다.
    set "TPL_FLAG="
) else (
    set "TPL_FLAG=--jinja --chat-template-file "%TEMPLATE%""
)

echo [시작] llama-server 262K 모드 가동 중...
"%LLAMA_SERVER%" ^
  -m "%MODEL%" ^
  -c 262144 ^
  -ngl 99 ^
  -fa on ^
  -ctk q8_0 ^
  -ctv q4_0 ^
  --cache-ram 16384 ^
  -np 1 ^
  -b 256 -ub 256 ^
  --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 --presence-penalty 0.0 ^
  %TPL_FLAG% ^
  --reasoning-preserve --reasoning-format deepseek ^
  --host 127.0.0.1 --port 8001

pause
