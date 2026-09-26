<#
  로컬 AI 종합 개선 스크립트 (기능은 그대로, 오류·속도·안전만 고침)

  실행:   powershell -ExecutionPolicy Bypass -File .\improve-localai.ps1
  옵션:   -Bench          적용 후 16/32/64/262K 전부 속도·VRAM 측정 (10~20분)
          -BenchOnly      아무것도 안 바꾸고 측정만
          -NoMcpoKey      도구 서버 인증키를 걸지 않음
          -InstallUvTools mcpo·time·fetch 를 uv tool 로 설치해 경로 고정 (인터넷 필요)
          -SkipModelTest  적용 후 모델 동시 상주 확인(약 1분) 생략
          -Rollback       처음 적용하기 전(원래) 상태로 전부 되돌림
          -From 이름      -Rollback 때 특정 백업(_backup\improve-날짜) 으로 되돌림
          -Yes            확인 질문 없이 진행
#>
param([switch]$Bench, [switch]$BenchOnly, [switch]$NoMcpoKey, [switch]$InstallUvTools,
      [switch]$SkipModelTest, [switch]$Rollback, [string]$From = '', [switch]$Yes)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'

$pkg    = $PSScriptRoot
$d      = "$env:USERPROFILE\LocalAI"
$ol     = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$bkRoot = "$d\_backup"
$helper = "$pkg\tools\localai_patch.py"
$fails  = New-Object System.Collections.Generic.List[string]
$notes  = New-Object System.Collections.Generic.List[string]

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Head($m) { Write-Host ''; Write-Host "■ $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [주의] $m" -ForegroundColor Yellow; $notes.Add($m) }
function Bad($m)  { Write-Host "  [실패] $m" -ForegroundColor Red; $fails.Add($m) }
function Ask($q)  { if ($Yes) { return $true }; (Read-Host "$q (Y/N)") -match '^[yY]' }
function Up($u)   { try { (Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }
function Sha($f)  { (Get-FileHash $f -Algorithm SHA256).Hash }
# 외부 프로그램(schtasks·ollama·uv 등)이 에러 출력만 내도 Windows PowerShell 5.1 에서 스크립트가 멈추지 않게
function Q([scriptblock]$sb) { $ErrorActionPreference = 'Continue'; & $sb }
function Api($path, $body, $timeout = 900) {
    $json = $body | ConvertTo-Json -Depth 10 -Compress
    Invoke-RestMethod "http://127.0.0.1:11434$path" -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType 'application/json; charset=utf-8' -TimeoutSec $timeout
}
function Py([string[]]$a) {
    $ErrorActionPreference = 'Continue'
    $out = & $script:py $helper @a 2>&1
    $code = $LASTEXITCODE
    $txt = ($out | ForEach-Object { "$_" }) -join "`n"
    $last = ($out | Where-Object { "$_".Trim().StartsWith('{') } | Select-Object -Last 1)
    $obj = $null; if ($last) { try { $obj = "$last" | ConvertFrom-Json } catch {} }
    [pscustomobject]@{ Code = $code; Obj = $obj; Text = $txt }
}
function Unload-All {
    try { $r = Invoke-RestMethod http://127.0.0.1:11434/api/ps -TimeoutSec 5
          foreach ($x in $r.models) { Api '/api/generate' @{ model = $x.name; keep_alive = 0 } 60 | Out-Null } } catch {}
    Start-Sleep 2
}

# 교체할 파일과, 분석할 때 본 원본(1번째 값)·1차 수정본(2번째 값)의 해시
$files = [ordered]@{
  'start-localai.ps1'      = @('C3F570D2985A34107CDEF7A0D4263513377091D84A92196B9D94ED106299DBD8','378243C8C2EC3A945DAEE873774986AC715694731ED516E18BCD1FEB9452851B')
  'update-localai.ps1'     = @('DA8C528C55D5E81D15A947212471024F216028FC47A2B448CBD3053D41D7CD29','72FBBF513F34C2CE48C388B2D902F4CC88C898CE0FE4C9638C430295607AFEEE')
  'start-llama-server.bat' = @('5A18A38569DC8C6D4C4618D0D4ED6C83B234C82E2260C58BE69701FF481D6881','FB562FC2712376E6599C5DE0A3DF9E6ED054FAD8796E0E2F3A3CBA7982D835C1')
  'task-model.Modelfile'   = @('56CBD0A737A22E2A413C647901440CA61285162E1ADB17659F097F61B7D6175A','31B57A4E7295256F42A390D93E026A6F34A7837B84DB56D5464A03B441237773')
  '_warm.ps1'              = @('82070262A48614D779B94978A3A32726750B03F4ABC1DC40D18DB6DBD1B2B216')
  'extras\server.py'       = @('2160EF565FBE28F6CCC76C129F780FC4DC9B2BB16C4E86862F83965D8150D0E9','CEC9B15C935B779D9A7D0FE5F974C087F432FD592CFDB206862DB808758F25C5')
  'windows\server.py'      = @('85BA6E27A2EFD75B9BCAD2F4C52B7DA1F281F5DE17BAD9B6F2AEEAF2954897F6','D26D74881C26AF074621D67A033AB34DBFD908D92D64BE606D30B53A0B051AD7')
  'webbrowser\server.py'   = @('5FDFE362517C60AC1FC4B006EAE67DD6C0A06579C5E07ACC9C257C3AD2D1BBF0','FCCD6D61E42FD18369EC0F64F293A26D9E05F2AAE6B9A202DE089B3C941ADADC')
  'gateway\server.py'      = @('24BEBCF9321C0C4C0EC37E43A8A42BCA47DD2F20332B8E0B3C11787B9F870164')
  'bench\run.py'           = @('B98719DD299AA66DD413C4DDC1DCF3B8CE1416B3D5EBE2F0BB9A3E761EE0BEA6')
}
# 수정·생성될 수 있는 나머지 (백업·되돌리기 대상)
$extra = 'tool-servers.json', 'mcp-config.json', '.mcpo_key', 'webui-env.ps1',
         'webui-data\webui.db', 'webui-data\webui.db-wal', 'webui-data\webui.db-shm', 'webui-data\.webui_secret_key'

if (-not (Test-Path $d)) { throw "LocalAI 폴더가 없습니다: $d" }
$uvTools = ''
try { $uvTools = "$(Q { & uv tool dir 2>$null } | Select-Object -First 1)".Trim() } catch {}
if (-not $uvTools) { $uvTools = "$env:APPDATA\uv\tools" }
$script:py = @("$d\windows\venv\Scripts\python.exe", "$d\extras\venv\Scripts\python.exe", "$uvTools\open-webui\Scripts\python.exe") |
             Where-Object { Test-Path $_ } | Select-Object -First 1

# ============================================================ 되돌리기
if ($Rollback) {
    # 기본은 가장 오래된 백업 = 처음 적용하기 전 원래 상태
    $all = @(Get-ChildItem $bkRoot -Directory -Filter 'improve-*' -EA SilentlyContinue | Sort-Object Name)
    $bk = if ($From) { $all | Where-Object { $_.Name -eq $From } | Select-Object -First 1 } else { $all | Select-Object -First 1 }
    if (-not $bk) { throw "백업이 없습니다: $bkRoot $From" }
    $man = Get-Content "$($bk.FullName)\manifest.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    Head "되돌리기: $($bk.Name)"
    Say '  주의: 적용 이후 새로 한 대화도 DB 와 함께 이전 상태로 돌아갑니다.' Yellow
    if (-not (Ask '로컬 AI 를 끄고 이 백업으로 되돌릴까요?')) { return }
    Q { & "$d\stop-localai.ps1" -quiet }
    foreach ($e in $man.items) {
        $to = Join-Path $d $e.rel
        if ($e.existed) { New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null; Copy-Item "$($bk.FullName)\files\$($e.rel)" $to -Force; Say "  복원: $($e.rel)" }
        elseif (Test-Path $to) { Remove-Item $to -Force; Say "  삭제(새로 생긴 파일): $($e.rel)" }
    }
    if (Test-Path $ol) {
        Q { & "$d\start-localai.ps1" -noopen }
        Q { & $ol create task-model -f "$d\task-model.Modelfile" 2>&1 | Out-Null }
    }
    # 이 백업과 그 뒤 백업은 다 쓴 것으로 표시 → 다음에 다시 적용하면 그때 상태가 새 '원래 상태'가 됨
    foreach ($x in $all) { if ($x.Name -ge $bk.Name) { Rename-Item $x.FullName ('used-' + $x.Name) -EA SilentlyContinue } }
    Say '되돌리기 완료.' Green
    return
}

# ============================================================ 측정 (16/32/64/262K)
function Run-Bench {
    Head '모델별 측정 (16/32/64/262K) — 모델마다 새로 올려서 속도·VRAM 을 잽니다'
    if (-not (Up 'http://127.0.0.1:11434/api/version')) { Q { & "$d\start-localai.ps1" -noopen } }
    $tags = (Invoke-RestMethod http://127.0.0.1:11434/api/tags).models.name
    $para = '기술보증기금은 기술력은 있으나 담보가 부족한 중소기업에 보증을 제공하는 공공기관이다. 기술평가를 통해 기업의 미래 가치를 판단하고 금융기관 대출을 지원한다. '
    $prompt = ($para * 25) + "`n위 글을 두 문장으로 요약해줘."
    $rows = @()
    foreach ($m in 'qwen-heretic-16k', 'qwen-heretic-32k', 'qwen-heretic-64k', 'qwen-heretic-262k') {
        if (-not ($tags -contains "$m`:latest")) { Say "  $m 없음 — 건너뜀" Yellow; continue }
        Unload-All
        Say "  $m 측정 중..."
        try {
            $r = Api '/api/generate' @{ model = $m; prompt = $prompt; stream = $false; think = $false; keep_alive = '5m'; options = @{ num_predict = 128 } } 1800
            $p = (Invoke-RestMethod http://127.0.0.1:11434/api/ps).models | Where-Object { $_.name -like "$m*" } | Select-Object -First 1
            $gpu = if ($p -and $p.size) { [math]::Round(100 * $p.size_vram / $p.size) } else { 0 }
            $vram = ''; try { $vram = "$(Q { & nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>$null })".Trim() } catch {}
            $rows += [pscustomobject]@{
                모델 = $m; 'GPU비율%' = $gpu; 'VRAM사용' = $vram
                '로드(초)' = [math]::Round($r.load_duration / 1e9, 1)
                '입력읽기(tok/s)' = [math]::Round($r.prompt_eval_count / ($r.prompt_eval_duration / 1e9))
                '생성(tok/s)' = [math]::Round($r.eval_count / ($r.eval_duration / 1e9), 1)
            }
        } catch { Say "  $m 실패: $($_.Exception.Message)" Red }
    }
    Unload-All
    $tbl = $rows | Format-Table -AutoSize | Out-String -Width 200
    Write-Host $tbl
    ("측정 " + (Get-Date -Format 'yyyy-MM-dd HH:mm') + $tbl) | Out-File "$d\bench-variants.log" -Encoding UTF8
    Say "  결과 저장: $d\bench-variants.log"
    Say '  GPU비율이 100 이면 전부 그래픽카드, 그보다 낮으면 일부가 CPU 로 가서 느립니다.'
    try { Q { & "$d\_warm.ps1" } } catch {}
}
if ($BenchOnly) { Run-Bench; return }

# ============================================================ 0. 사전 점검
Head '0/6 사전 점검'
if (-not (Test-Path $ol)) { throw "Ollama 가 없습니다: $ol" }
if (-not $script:py) { throw 'LocalAI 의 파이썬(windows\venv 등)을 찾지 못했습니다.' }
Ok "도우미 파이썬: $script:py"
$changed = @()
foreach ($rel in $files.Keys) {
    $cur = Join-Path $d $rel; $new = Join-Path "$pkg\LocalAI" $rel
    if (-not (Test-Path $new)) { throw "패키지 파일 없음: $new (폴더째 받았는지 확인)" }
    if (-not (Test-Path $cur)) { Warn "$rel 이 없어 새로 만듭니다"; continue }
    $h = Sha $cur
    if ($h -eq (Sha $new)) { Say "  이미 최신: $rel"; continue }
    if ($files[$rel] -notcontains $h) { $changed += $rel }
}
if ($changed) {
    Warn ("분석 이후 직접 고친 것으로 보이는 파일: " + ($changed -join ', ') + ' — 덮어쓰지만 백업에 남습니다')
    if (-not (Ask '계속할까요?')) { return }
}

# ============================================================ 1. 백업
Head '1/6 로컬 AI 끄고 백업'
Q { & "$d\stop-localai.ps1" -quiet }
$tag = Get-Date -Format 'yyyyMMdd-HHmmss'
$bk = "$bkRoot\improve-$tag"
$items = @()
foreach ($rel in @($files.Keys) + $extra) {
    $src = Join-Path $d $rel
    $ex = Test-Path $src
    if ($ex) { $dst = "$bk\files\$rel"; New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null; Copy-Item $src $dst -Force }
    $items += [pscustomobject]@{ rel = $rel; existed = $ex }
}
New-Item -ItemType Directory -Force $bk | Out-Null
@{ created = $tag; items = $items } | ConvertTo-Json -Depth 5 | Out-File "$bk\manifest.json" -Encoding UTF8
Ok "백업: $bk  (되돌리기: .\improve-localai.ps1 -Rollback)"

$applied = $false
try {
    # ======================================================== 2. 파일 교체
    Head '2/6 파일 교체'
    foreach ($rel in $files.Keys) {
        $to = Join-Path $d $rel
        New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
        Copy-Item (Join-Path "$pkg\LocalAI" $rel) $to -Force
        Say "  교체: $rel"
    }
    $applied = $true

    # ======================================================== 3. 도구 서버 인증키 + 실행 파일 경로
    Head '3/6 도구 서버(mcpo) 설정'
    $key = ''
    if ($NoMcpoKey) {
        if (Test-Path "$d\.mcpo_key") { Remove-Item "$d\.mcpo_key" -Force }
        Say '  인증키 사용 안 함 (-NoMcpoKey)'
    } else {
        if (Test-Path "$d\.mcpo_key") { $key = "$(Get-Content "$d\.mcpo_key" -Raw)".Trim() }
        if (-not $key) { $key = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'); Set-Content "$d\.mcpo_key" $key -Encoding Ascii -NoNewline }
        Ok '인증키 준비 (LocalAI\.mcpo_key) — 키 없는 프로그램·웹페이지는 PC 조작 도구를 못 부름'
    }
    $bin = ''
    if ($InstallUvTools) {
        foreach ($t in 'mcpo', 'mcp-server-time', 'mcp-server-fetch') {
            if (-not (Test-Path "$env:USERPROFILE\.local\bin\$t.exe")) { Q { & uv tool install $t 2>&1 | Out-Null } }
        }
        $bin = "$env:USERPROFILE\.local\bin"
    }
    $a = @('json', '--tool-servers', "$d\tool-servers.json", '--mcp-config', "$d\mcp-config.json")
    if ($key) { $a += @('--mcpo-key', $key) }
    if ($bin) { $a += @('--bin', $bin) }
    $r = Py $a
    if ($r.Code -ne 0 -or -not $r.Obj) { throw "설정 파일 수정 실패:`n$($r.Text)" }
    if ($r.Obj.tool_servers) { Ok "tool-servers.json 에 키 반영 ($(@($r.Obj.tool_servers).Count)개)" }
    foreach ($x in @($r.Obj.mcp_config)) { if ($x) { Ok "mcp-config: $x" } }

    # ======================================================== 4. Open WebUI DB
    Head '4/6 Open WebUI 설정 (필터 코드·밸브, 기본 압축 끄기, 도구 키) — 대화 내용은 건드리지 않음'
    if (-not (Test-Path "$d\webui-data\webui.db")) { throw "Open WebUI DB 가 없습니다: $d\webui-data\webui.db" }
    $a = @('db', '--db', "$d\webui-data\webui.db", '--functions', "$pkg\openwebui-functions", '--compaction-off', '--webui-src', "$uvTools\open-webui\Lib\site-packages\open_webui")
    if ($key) { $a += @('--mcpo-key', $key) }
    $r = Py $a
    if ($r.Code -ne 0 -or -not $r.Obj) { throw "DB 수정 실패:`n$($r.Text)" }
    foreach ($p in $r.Obj.functions.PSObject.Properties) {
        if ($p.Value -like '교체됨*') { Ok "필터 $($p.Name): $($p.Value)" } else { Warn "필터 $($p.Name): $($p.Value) — 관리자 패널 > 함수에서 openwebui-functions\$($p.Name).py 내용을 직접 넣으세요" }
    }
    foreach ($x in @($r.Obj.compaction_off)) { if ($x) { Ok "기본 압축 끔: $x" } }
    $tk = @($r.Obj.tool_server_keys | Where-Object { $_ })
    if ($tk.Count -gt 0) { Ok "DB 의 도구 서버 연결에 키 반영 ($($tk.Count)개)" }
    elseif ($key) { Say '  (DB 에 저장된 도구 서버 목록이 없어 tool-servers.json 으로 적용됨)' }
    $envLines = @()
    foreach ($n in @($r.Obj.env_disable)) { if ($n) { $envLines += "`$env:$n='False'" } }
    foreach ($n in @($r.Obj.env_enable))  { if ($n) { $envLines += "`$env:$n='True'" } }
    if ($envLines) {
        ("# improve-localai.ps1 이 만든 파일: Open WebUI 기본 컨텍스트 압축 끄기 (압축은 auto_summary·context_guard 가 담당)`r`n" + ($envLines -join "`r`n")) |
            Out-File "$d\webui-env.ps1" -Encoding UTF8
        Ok "환경변수로도 끔: $(@($r.Obj.env_disable) + @($r.Obj.env_enable) -join ', ')"
    } elseif (-not @($r.Obj.compaction_off | Where-Object { $_ })) {
        Warn 'Open WebUI 기본 압축 스위치를 자동으로 못 찾았습니다 — 관리자 설정에서 "컨텍스트 압축"이 켜져 있으면 끄세요'
    }

    # ======================================================== 5. 켜기 + task-model
    Head '5/6 로컬 AI 켜기, 작업용 모델 다시 만들기'
    Q { & "$d\start-localai.ps1" -noopen }
    Q { & $ol create task-model -f "$d\task-model.Modelfile" 2>&1 | Out-Null }
    if ($LASTEXITCODE -eq 0) { Ok 'task-model 다시 만듦 (문맥 8192)' } else { Bad 'task-model 만들기 실패' }
} catch {
    Bad $_.Exception.Message
}

# ============================================================ 6. 검증
Head '6/6 검증'
if ($fails.Count -eq 0) {
    foreach ($u in 'http://127.0.0.1:11434/api/version', 'http://127.0.0.1:8765/time/openapi.json', 'http://127.0.0.1:8080/health') {
        if (Up $u) { Ok "켜짐: $u" } else { Bad "응답 없음: $u (로그: $d\mcpo.log, $d\webui.log)" }
    }
    if (Up 'http://127.0.0.1:8890/healthz') { Ok '켜짐: 검색(SearXNG)' } else { Warn '검색(SearXNG) 응답 없음 — 조금 늦게 뜰 수 있음' }

    # 도구 서버 인증: 키 없이 거부, 키로 통과, 게이트웨이(tools)도 키로 통과
    $body = [Text.Encoding]::UTF8.GetBytes('{"timezone":"Asia/Seoul"}')
    function Tool($path, $bytes, $hdr) {
        try { (Invoke-WebRequest "http://127.0.0.1:8765$path" -Method Post -Body $bytes -ContentType 'application/json' -Headers $hdr -UseBasicParsing -TimeoutSec 60).StatusCode }
        catch { if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 } }
    }
    $h = @{}; if ($key) { $h = @{ Authorization = "Bearer $key" } }
    if ((Tool '/time/get_current_time' $body $h) -eq 200) { Ok '도구 호출(time) 정상' } else { Bad '도구 호출(time) 실패' }
    $gw = [Text.Encoding]::UTF8.GetBytes('{"name":"time.get_current_time","arguments":{"timezone":"Asia/Seoul"}}')
    if ((Tool '/tools/tool_call' $gw $h) -eq 200) { Ok '게이트웨이(tools) 경유 호출 정상' } else { Bad '게이트웨이(tools) 경유 호출 실패' }
    if ($key) {
        $c = Tool '/time/get_current_time' $body @{}
        if ($c -eq 401 -or $c -eq 403) { Ok "키 없는 호출 거부됨 ($c)" } else { Warn "키 없는 호출이 거부되지 않음 ($c) — 설치된 mcpo 가 --api-key 를 지원하지 않는 버전일 수 있음" }
    }

    # 필터 동작 (가짜 대화로)
    $r = Py @('verify', '--functions', "$pkg\openwebui-functions")
    if ($r.Obj -and $r.Obj.ok) { Ok "필터 검사 $(@($r.Obj.results.PSObject.Properties).Count)개 모두 통과 (사용자 질문 유지·문맥 인식 16/32/64/262K·예산 맞춤)" }
    else { Bad "필터 검사 실패:`n$($r.Text)" }

    # 메인 모델 + task-model 동시 상주 (= 압축·제목 생성 때 VRAM 에서 안 내려감)
    if (-not $SkipModelTest) {
        Say '  모델 동시 상주 확인 중 (32K 로드 약 10~30초)...'
        try {
            Api '/api/generate' @{ model = 'qwen-heretic-32k'; prompt = 'hi'; stream = $false; think = $false; options = @{ num_predict = 1 } } | Out-Null
            Api '/api/generate' @{ model = 'task-model'; prompt = 'hi'; stream = $false; think = $false; options = @{ num_predict = 1 } } | Out-Null
            $ps = (Invoke-RestMethod http://127.0.0.1:11434/api/ps).models
            $main = $ps | Where-Object { $_.name -like 'qwen-heretic-32k*' }
            if ($main -and ($ps | Where-Object { $_.name -like 'task-model*' })) {
                Ok "32K 모델과 task-model 이 함께 떠 있음 → 압축·제목 생성 때 메인 모델이 안 내려감"
                $g = [math]::Round(100 * $main.size_vram / $main.size)
                if ($g -ge 99) { Ok "32K 모델 100% GPU" } else { Warn "32K 모델 GPU $g% — 다른 프로그램이 VRAM 을 쓰는 중일 수 있음" }
            } else { Bad "동시 상주 실패: 지금 떠 있는 모델 = $(($ps.name) -join ', ')" }
        } catch { Bad "모델 확인 실패: $($_.Exception.Message)" }
    }
}

# ============================================================ 결과
Write-Host ''
if ($fails.Count -gt 0) {
    Say "문제 $($fails.Count)개:" Red; $fails | ForEach-Object { Say "  - $_" Red }
    if ($applied -and (Ask '이번 실행 전 상태로 되돌릴까요?')) { & $PSCommandPath -Rollback -From "improve-$tag" -Yes; return }
    if ($fails -match '8765|도구') { Say '도구 서버(mcpo)가 인증키 옵션을 지원하지 않는 버전일 수 있습니다 → .\improve-localai.ps1 -NoMcpoKey 로 다시 실행해 보세요' Yellow }
    Say "원래 상태로 되돌리려면: .\improve-localai.ps1 -Rollback" Yellow
} else {
    Say '모든 개선 적용·검증 완료.' Green
    Say '  - 에러로 멈췄던 예전 채팅은 새 채팅으로 시작하세요 (그 채팅엔 잘못된 압축 기록이 남아 있음)'
    Say '  - 채팅 화면: http://127.0.0.1:8080'
}
if ($notes.Count -gt 0) { Say '참고:' Yellow; $notes | ForEach-Object { Say "  - $_" Yellow } }
$rep = "$d\improve-report.txt"
@("improve-localai $tag", "실패: $($fails -join ' | ')", "참고: $($notes -join ' | ')", "백업: $bk") | Out-File $rep -Encoding UTF8
if ($fails.Count -eq 0 -and $Bench) { Run-Bench }
