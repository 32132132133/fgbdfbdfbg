# 로컬 AI 오류 수정 적용 (2026-09-26)
# 사용법: 이 폴더(localai-fix)에서  powershell -ExecutionPolicy Bypass -File .\apply-fix.ps1
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'LocalAI'
$d   = "$env:USERPROFILE\LocalAI"
$ol  = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$tag = 'bak-' + (Get-Date -Format 'yyyyMMdd-HHmmss')

if (-not (Test-Path $d)) { throw "LocalAI 폴더가 없습니다: $d" }

Write-Host '1/4 로컬 AI 끄는 중...' -ForegroundColor Cyan
& "$d\stop-localai.ps1" -quiet

Write-Host "2/4 파일 교체 (기존 파일은 *.$tag 로 백업)" -ForegroundColor Cyan
$files = 'start-localai.ps1', 'update-localai.ps1', 'start-llama-server.bat', 'task-model.Modelfile',
         'extras\server.py', 'windows\server.py', 'webbrowser\server.py'
foreach ($f in $files) {
    $to = Join-Path $d $f
    if (Test-Path $to) { Copy-Item $to "$to.$tag" -Force }
    Copy-Item (Join-Path $src $f) $to -Force
    Write-Host "  교체: $f"
}

Write-Host '3/4 로컬 AI 켜고 작업용 모델(task-model) 다시 만들기' -ForegroundColor Cyan
& "$d\start-localai.ps1" -noopen
& $ol create task-model -f "$d\task-model.Modelfile"

Write-Host '4/4 완료' -ForegroundColor Green
Write-Host ''
Write-Host '남은 수동 작업 (README.md 의 "Open WebUI 에서 할 일" 참고):' -ForegroundColor Yellow
Write-Host '  1) 관리자 패널 > 함수: context_guard, auto_summary 코드를 openwebui-functions 폴더 파일로 바꾸고 저장'
Write-Host '  2) 두 함수의 밸브(Valves)에 예전 값이 저장돼 있으면 기본값으로 초기화'
Write-Host '  3) Open WebUI 기본 "컨텍스트 압축" 기능 끄기'
Write-Host '  4) 에러 나서 멈춘 채팅은 새 채팅으로 시작'
Write-Host ''
Write-Host "되돌리기: $d 안의 *.$tag 파일을 원래 이름으로 바꾸면 됩니다."
