# 로컬 AI 업데이트: Open WebUI, MCP 서버, 모델
$ErrorActionPreference='Continue'
$d="$env:USERPROFILE\LocalAI"
$ol="$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
Write-Host "1/4 실행 중인 Open WebUI/MCP 종료" -ForegroundColor Cyan
& "$d\stop-localai.ps1" -quiet
Write-Host "2/4 Open WebUI 업데이트" -ForegroundColor Cyan
Copy-Item "$d\webui-data\webui.db" "$d\webui-data\webui.db.bak-update" -Force -EA SilentlyContinue
uv tool upgrade open-webui
Write-Host '※ Open WebUI 가 새로 설치되면 루프 감지 패치를 다시 적용해야 합니다 (사용법.txt 참고)' -ForegroundColor Yellow
Write-Host "3/4 MCP 서버 업데이트" -ForegroundColor Cyan
# 예전엔 uv 캐시를 지워서 start-localai.ps1 / mcp-config.json 에 적힌 실행 파일 경로가 사라졌음.
# uv tool 로 설치된 것만 올린다 (경로가 %USERPROFILE%\.local\bin 으로 고정)
foreach($t in 'mcpo','mcp-server-time','mcp-server-fetch'){
  if(Test-Path "$env:USERPROFILE\.local\bin\$t.exe"){ uv tool upgrade $t }
}
Write-Host "4/4 모델 다시 만들기 (설정 반영)" -ForegroundColor Cyan
$env:OLLAMA_FLASH_ATTENTION='1'; $env:OLLAMA_KV_CACHE_TYPE='q8_0'
$sv=Start-Process $ol -ArgumentList 'serve' -WindowStyle Hidden -PassThru; Start-Sleep 5
foreach($n in 'qwen-heretic-16k','qwen-heretic-32k','qwen-heretic-64k','qwen-heretic-262k','task-model'){
  if(Test-Path "$d\$n.Modelfile"){ & $ol create $n -f "$d\$n.Modelfile" }
}
Stop-Process -Id $sv.Id -Force -EA SilentlyContinue
Write-Host "완료. 로컬 AI를 다시 실행합니다." -ForegroundColor Green
& "$d\start-localai.ps1"
Read-Host "엔터를 누르면 창이 닫힙니다"
