# 로컬 AI 업데이트: Open WebUI, MCP 서버, 모델
$ErrorActionPreference='Continue'
$d="$env:USERPROFILE\LocalAI"
Write-Host "1/4 실행 중인 Open WebUI/MCP 종료" -ForegroundColor Cyan
& "$d\stop-localai.ps1" -quiet
Write-Host "2/4 Open WebUI 업데이트" -ForegroundColor Cyan
uv tool upgrade open-webui
Write-Host '※ Open WebUI 가 새로 설치되면 루프 감지 패치를 다시 적용해야 합니다 (사용법.txt 참고)' -ForegroundColor Yellow
Write-Host "3/4 MCP 서버 캐시 갱신" -ForegroundColor Cyan
uv cache clean mcpo mcp-server-time mcp-server-fetch duckduckgo-mcp-server
Write-Host "4/4 모델 업데이트 확인" -ForegroundColor Cyan
$env:OLLAMA_FLASH_ATTENTION='1'; $env:OLLAMA_KV_CACHE_TYPE='q8_0'
$sv=Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList 'serve' -WindowStyle Hidden -PassThru; Start-Sleep 5
foreach($n in 'qwen-heretic-16k','qwen-heretic-32k','qwen-heretic-64k','qwen-heretic-262k','task-model'){ & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" create $n -f "$d\$n.Modelfile" }
Stop-Process -Id $sv.Id -Force -EA SilentlyContinue
Write-Host "완료. 로컬 AI를 다시 실행합니다." -ForegroundColor Green
& "$d\start-localai.ps1"
Read-Host "엔터를 누르면 창이 닫힙니다"