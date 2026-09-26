$ErrorActionPreference='SilentlyContinue'
$d='C:\Users\gu214\LocalAI'
$env:PYTHONUTF8='1'
$env:OLLAMA_FLASH_ATTENTION='1'; $env:OLLAMA_KV_CACHE_TYPE='q8_0'; $env:OLLAMA_KEEP_ALIVE='15m'; $env:OLLAMA_NUM_PARALLEL='1'; $env:OLLAMA_GPU_OVERHEAD='1610612736'; $env:OLLAMA_MAX_LOADED_MODELS='2'
function Up($u){ try{ (Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }catch{ $false } }
if(-not (Up 'http://127.0.0.1:11434/api/version')){
  Get-Process 'ollama app','ollama' -EA SilentlyContinue | Stop-Process -Force
  Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardError "$d\ollama-serve.log"
  for($i=0;$i -lt 30 -and -not (Up 'http://127.0.0.1:11434/api/version');$i++){ Start-Sleep 1 }
}
if(-not (Up 'http://127.0.0.1:8888/api/status')){ schtasks /run /tn "LocalAI_Jupyter" 2>$null | Out-Null }
if(-not (Up 'http://127.0.0.1:8765/time/openapi.json')){
  $mcpoExe = 'C:\Users\gu214\AppData\Local\uv\cache\archive-v0\EM11r0_vPtdEiLRU1D6GA\Scripts\mcpo.exe'
  Start-Process cmd -ArgumentList "/c `"`"$mcpoExe`" --host 127.0.0.1 --port 8765 --config `"$d\mcp-config.json`" > `"$d\mcpo.log`" 2>&1`"" -WindowStyle Hidden
}
# --- GPU 점유 확인: 다른 프로그램이 그래픽 메모리를 크게 쓰고 있으면 알려준다 (끄지는 않음) ---
try{
  $hogs=(Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -EA Stop).CounterSamples | ? { $_.CookedValue -gt 2GB } | % {
    $procId=[int]($_.InstanceName -replace '^pid_(\d+)_.*','$1'); $p=Get-Process -Id $procId -EA SilentlyContinue
    if($p -and $p.ProcessName -notmatch 'ollama|llama-server'){ "{0} (PID {1}) - {2:N1}GB" -f $p.ProcessName,$procId,($_.CookedValue/1GB) } }
  if($hogs -and $args -notcontains '-noopen'){
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("다른 프로그램이 그래픽 메모리를 많이 쓰고 있습니다:`n`n$($hogs -join "`n")`n`n이대로 쓰면 로컬 AI가 많이 느립니다. 학습 등 GPU 작업을 멈춘 뒤 쓰거나, 가벼운 16K 모델을 쓰세요.",'로컬 AI - 그래픽 메모리 부족') | Out-Null
  }
}catch{}
if(-not (Up 'http://127.0.0.1:8890/healthz')){ Start-Process cmd -ArgumentList "/c ""$env:USERPROFILE\LocalAI\searxng\run.bat""" -WindowStyle Hidden }
if(-not (Up 'http://127.0.0.1:8080/health')){
  $env:DATA_DIR="$d\webui-data"
  $env:WEBUI_AUTH='False'
$env:CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS='60'
  $sk="$d\webui-data\.webui_secret_key"
  if(-not (Test-Path $sk)){ [IO.File]::WriteAllText($sk, ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))) }
  $env:WEBUI_SECRET_KEY=[IO.File]::ReadAllText($sk).Trim()
  $env:OLLAMA_BASE_URL='http://127.0.0.1:11434'
  $env:ENABLE_OPENAI_API='False'
  $env:DEFAULT_MODELS='qwen-uncensored:latest'
  $env:DEFAULT_LOCALE='ko-KR'
  $env:ENABLE_EVALUATION_ARENA_MODELS='False'
  $env:ENABLE_WEB_SEARCH='True'
  $env:WEB_SEARCH_ENGINE='searxng'; $env:SEARXNG_QUERY_URL='http://127.0.0.1:8890/search?q=<query>'
  $env:TOOL_SERVER_CONNECTIONS=[IO.File]::ReadAllText("$d\tool-servers.json")
  $env:AIOHTTP_CLIENT_TIMEOUT='0'
  $env:AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER='600'
  $env:AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA='120'
  $env:OLLAMA_REQUEST_TIMEOUT='600'
  $env:ANONYMIZED_TELEMETRY='False'; $env:DO_NOT_TRACK='True'
  Start-Process cmd -ArgumentList "/c `"`"$env:USERPROFILE\.local\bin\open-webui.exe`" serve --host 127.0.0.1 --port 8080 > `"$d\webui.log`" 2>&1`"" -WindowStyle Hidden
}
function Wait-Up($u,$sec){ for($i=0;$i -lt $sec;$i++){ if(Up $u){ return $true }; Start-Sleep 1 }; $false }
$ok = (Wait-Up 'http://127.0.0.1:11434/api/version' 60) -and (Wait-Up 'http://127.0.0.1:8765/time/openapi.json' 120) -and (Wait-Up 'http://127.0.0.1:8080/health' 180)
if($ok){ if($args -notcontains '-noopen'){ Start-Process 'http://127.0.0.1:8080' } }
else{ Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show("로컬 AI 시작에 실패했습니다.`n로그: $d\webui.log, $d\mcpo.log",'로컬 AI') | Out-Null }