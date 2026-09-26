"""로컬 AI 추가 도구: 문서 읽기(Docling/HWP), 웹 크롤링(Crawl4AI), 받아쓰기(faster-whisper), 영상 받기(yt-dlp), 파일 찾기(Everything/ripgrep).
GPU 는 채팅 모델이 쓰므로 여기선 전부 CPU 로만 돈다."""
import os, re, sys, json, asyncio, subprocess, shutil, time, pathlib
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
from fastmcp import FastMCP

OUT = pathlib.Path(r"C:\Users\gu214\OneDrive\바탕 화면\local\AI결과")
DL = pathlib.Path(r"C:\Users\gu214\Downloads\AI다운로드")
OUT.mkdir(parents=True, exist_ok=True); DL.mkdir(parents=True, exist_ok=True)
MAXC = 8000  # 32K 모델에서 도구 결과 하나가 문맥을 다 먹지 않게 (한국어 약 8천 토큰)
PROTECTED = re.compile(r"면준1|바탕\s*화면[\\/]+project|desktop[\\/]+project|03_백업자료|05_복구사진|G:[\\/]+백업|\.ssh|\.gnupg|Credentials|Login Data|key4\.db|logins\.json", re.I)

mcp = FastMCP("docs")

def _guard(p):
    s = str(p)
    cands = [s]
    if s and not re.match(r"https?://", s.strip().strip('"')):
        try:  # '..', 환경변수, ~ 를 풀어 실제 경로로도 검사 (local\..\project 같은 우회 차단)
            cands.append(str(pathlib.Path(os.path.expandvars(os.path.expanduser(s.strip().strip('"')))).resolve()))
        except Exception:
            pass
    if any(PROTECTED.search(c) for c in cands):
        raise ValueError("보호 폴더(사용자가 막아둔 곳)라 접근할 수 없습니다.")

def _clip(text, name):
    text = text or ""
    if len(text) <= MAXC:
        return text
    stem = re.sub(r'[\\/:*?"<>|]', "_", name)[:60] or "result"
    f = OUT / f"{stem}_{time.strftime('%H%M%S')}.md"
    f.write_text(text, encoding="utf-8")
    return text[:MAXC] + f"\n\n...(내용이 길어 앞부분 {MAXC}자만 표시. 전체는 {f} 에 저장함)"

def _hwp(path):
    p = str(path)
    if p.lower().endswith(".hwpx"):
        import zipfile
        z = zipfile.ZipFile(p); parts = []
        for n in sorted(z.namelist()):
            if n.startswith("Contents/section") and n.endswith(".xml"):
                x = z.read(n).decode("utf-8", "ignore")
                paras = re.findall(r"<hp:p\b.*?</hp:p>", x, re.S)
                for para in paras:
                    t = "".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", para, re.S))
                    t = re.sub(r"<[^>]+>", "", t)
                    parts.append(t)
        return "\n".join(parts)
    exe = pathlib.Path(sys.executable).with_name("hwp5txt.exe")
    r = subprocess.run([str(exe), "--output", "-", p], capture_output=True, timeout=180)
    out = r.stdout.decode("utf-8", "ignore")
    if not out.strip():
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-400:])
    return out

_conv = {}
def _docling(path, ocr):
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    key = bool(ocr)
    if key not in _conv:
        po = PdfPipelineOptions()
        po.do_ocr = bool(ocr)
        po.do_table_structure = True
        po.accelerator_options = AcceleratorOptions(num_threads=8, device=AcceleratorDevice.CPU)
        if ocr:
            try:
                from docling.datamodel.pipeline_options import EasyOcrOptions
                po.ocr_options = EasyOcrOptions(lang=["ko", "en"], use_gpu=False)
            except Exception:
                pass
        _conv[key] = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=po)})
    res = _conv[key].convert(str(path))
    return res.document.export_to_markdown()

def _markitdown(src):
    from markitdown import MarkItDown
    return MarkItDown().convert(src).text_content

@mcp.tool
def read_document(path: str, ocr: bool = False) -> str:
    """문서를 읽어 표·제목 구조가 살아있는 마크다운으로 돌려준다. PDF·워드·엑셀·PPT·HWP/HWPX(한글)·HTML·이미지·CSV, 유튜브 링크(자막)도 된다.
    path=파일 경로 또는 URL. 스캔본 PDF·사진처럼 글자가 이미지면 ocr=true."""
    src = path.strip().strip('"')
    _guard(src)
    if re.match(r"https?://", src):
        if re.search(r"youtube\.com|youtu\.be", src):
            return _clip(_markitdown(src), "youtube")
        try:
            return _clip(_docling(src, ocr), "web")
        except Exception:
            return _clip(_markitdown(src), "web")
    p = pathlib.Path(os.path.expandvars(os.path.expanduser(src)))
    if not p.exists():
        return f"파일이 없습니다: {p}"
    ext = p.suffix.lower()
    try:
        if ext in (".hwp", ".hwpx"):
            return _clip(_hwp(p), p.stem)
        if ext in (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".md", ".csv", ".adoc"):
            if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
                ocr = True
            md = _docling(p, ocr)
            if ext == ".pdf" and not ocr and len(md.strip()) < 50:
                md = _docling(p, True)
            return _clip(md, p.stem)
    except Exception as e:
        try:
            return _clip(_markitdown(str(p)), p.stem) + f"\n\n(참고: 정밀 변환 실패로 간단 변환 사용 — {e})"
        except Exception as e2:
            return f"변환 실패: {e2}"
    return _clip(_markitdown(str(p)), p.stem)

@mcp.tool
async def crawl_web(url: str, max_pages: int = 1, keyword: str = "", keep_links: bool = False) -> str:
    """웹페이지를 실제 브라우저로 열어(자바스크립트 실행) 본문만 깔끔한 마크다운으로 가져온다. 광고·메뉴는 걸러낸다.
    max_pages>1 이면 같은 사이트 안의 링크를 따라가며 여러 페이지를 모은다(최대 10). keyword 를 주면 그 단어가 나오는 부분(앞뒤 문맥 포함)만 뽑아 준다. 링크 주소가 필요하면 keep_links=true."""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    from crawl4ai.content_filter_strategy import PruningContentFilter, BM25ContentFilter
    flt = PruningContentFilter(threshold=0.4, threshold_type="fixed")
    kw = dict(cache_mode=CacheMode.BYPASS, markdown_generator=DefaultMarkdownGenerator(content_filter=flt), page_timeout=45000, wait_until="domcontentloaded", delay_before_return_html=1.5)
    n = max(1, min(int(max_pages or 1), 10))
    if n > 1:
        from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
        kw["deep_crawl_strategy"] = BFSDeepCrawlStrategy(max_depth=2, include_external=False, max_pages=n)
    bc = BrowserConfig(headless=True, verbose=False, extra_args=["--disable-gpu"])
    out = []
    async with AsyncWebCrawler(config=bc) as c:
        res = await c.arun(url=url, config=CrawlerRunConfig(**kw))
        items = res if isinstance(res, list) else [res]
        for r in items:
            if not r.success:
                out.append(f"## {r.url}\n(실패: {r.error_message})"); continue
            md = r.markdown
            body = (getattr(md, "fit_markdown", None) or getattr(md, "raw_markdown", None) or str(md) or "").strip()
            if len(body) < 200:
                body = (getattr(md, "raw_markdown", "") or body).strip()
            body = re.sub(r"(?m)^\s*\*\[[^\]]*\]:.*$", "", body)
            if keyword:
                raw = (getattr(md, "raw_markdown", "") or body)
                raw = re.sub(r"(?m)^\s*\*\[[^\]]*\]:.*$", "", raw)
                ls = [l for l in raw.split("\n") if l.strip()]
                keys = [k for k in re.split(r"\s+", keyword.strip()) if k]
                idx = [i for i, l in enumerate(ls) if any(k.lower() in l.lower() for k in keys)]
                keep = sorted({j for i in idx for j in range(max(0, i - 2), min(len(ls), i + 3))})
                pick = []; prev = -2
                for j in keep:
                    if j != prev + 1: pick.append("…")
                    pick.append(ls[j]); prev = j
                body = "\n".join(pick) if pick else body
            if not keep_links:
                body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
                body = re.sub(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)", r"\1", body)
                body = re.sub(r"\n{3,}", "\n\n", body)
            out.append(f"## {r.url}\n{body}")
    return _clip("\n\n".join(out), "crawl")

_wh = {}
@mcp.tool
def transcribe(source: str, language: str = "ko") -> str:
    """음성·영상 파일이나 영상 링크(유튜브 등)의 말을 글로 받아 적는다. 결과 전체는 AI결과 폴더에 txt 로도 저장된다. 영상 길이만큼 시간이 걸릴 수 있다."""
    src = source.strip().strip('"'); _guard(src)
    if re.match(r"https?://", src):
        f = _ytdlp(src, audio_only=True)
        if not f: return "영상 오디오를 받지 못했습니다."
        src = f
    if not os.path.exists(src): return f"파일이 없습니다: {src}"
    from faster_whisper import WhisperModel
    if "m" not in _wh:
        _wh["m"] = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", cpu_threads=max(4, (os.cpu_count() or 8) - 2))
    segs, info = _wh["m"].transcribe(src, language=(language or None), vad_filter=True, beam_size=1)
    lines = []
    for s in segs:
        m, sec = divmod(int(s.start), 60)
        lines.append(f"[{m:02d}:{sec:02d}] {s.text.strip()}")
    text = "\n".join(lines)
    f = OUT / (re.sub(r'[\\/:*?"<>|]', "_", pathlib.Path(src).stem)[:60] + "_받아쓰기.txt")
    f.write_text(text, encoding="utf-8")
    return _clip(text, "transcript") + f"\n\n(전체 저장: {f})"

def _ytdlp(url, audio_only=False):
    import yt_dlp
    opts = {"outtmpl": str(DL / "%(title).80s.%(ext)s"), "quiet": True, "noprogress": True, "restrictfilenames": False, "windowsfilenames": True}
    if audio_only:
        opts.update({"format": "bestaudio/best", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]})
    else:
        opts.update({"format": "bv*[height<=1080]+ba/b[height<=1080]/b", "merge_output_format": "mp4"})
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        fn = y.prepare_filename(info)
    base = os.path.splitext(fn)[0]
    for ext in ([".m4a"] if audio_only else [".mp4", ".mkv", ".webm"]) + [os.path.splitext(fn)[1]]:
        if os.path.exists(base + ext): return base + ext
    return fn if os.path.exists(fn) else None

@mcp.tool
def download_media(url: str, audio_only: bool = False) -> str:
    """유튜브 등 영상 사이트에서 영상(최대 1080p mp4)을 받는다. audio_only=true 면 소리만(m4a). 저장 위치: 다운로드\\AI다운로드."""
    try:
        f = _ytdlp(url, audio_only)
        return f"저장됨: {f}" if f else "받기 실패(파일을 못 찾음)"
    except Exception as e:
        return f"받기 실패: {e}"

@mcp.tool
def find_files(query: str, search_content: bool = False, folder: str = "", limit: int = 30) -> str:
    """컴퓨터에서 파일을 찾는다. 기본은 파일 이름 검색(컴퓨터 전체, 거의 즉시; 예: '보고서 *.pdf', 'ext:hwp 자기소개서').
    search_content=true 면 folder 안 파일들의 '내용'에서 query 문구를 찾는다(folder 필수)."""
    _guard(query); _guard(folder)
    limit = max(1, min(int(limit or 30), 200))
    if search_content:
        if not folder: return "내용 검색은 folder 가 필요합니다."
        rg = shutil.which("rg") or r"C:\Users\gu214\AppData\Local\Microsoft\WinGet\Links\rg.exe"
        r = subprocess.run([rg, "-n", "-i", "--max-count", "3", "-M", "200", "--", query, folder], capture_output=True, timeout=120)
        lines = [l for l in r.stdout.decode("utf-8", "ignore").splitlines() if not PROTECTED.search(l)]
        return "\n".join(lines[:limit * 3]) or "찾은 내용이 없습니다."
    es = shutil.which("es") or next((p for p in [r"C:\Users\gu214\LocalAI\everything\es.exe", r"C:\Program Files\Everything\es.exe", os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\es.exe")] if os.path.exists(p)), None)
    if es:
        args = [es, "-n", str(limit * 2), "-sort", "date-modified-descending"]
        if folder: args += ["-path", folder]
        r = subprocess.run(args + query.split(), capture_output=True, timeout=30)
        out = r.stdout.decode("utf-8", "ignore") or r.stdout.decode("cp949", "ignore")
        if r.returncode == 0 and out.strip():
            lines = [l for l in out.splitlines() if l.strip() and not PROTECTED.search(l)][:limit]
            return "\n".join(lines)
    root = folder or os.path.expanduser("~")
    q2 = re.sub(r"\bext:(\w+)", r"*.\1", query)
    pat = q2.replace(" ", "*").replace("**", "*").strip("*")
    q = lambda s: s.replace("'", "''")  # 작은따옴표로 명령을 끼워넣는 것 차단
    ps = f"Get-ChildItem -LiteralPath '{q(root)}' -Recurse -File -Filter '*{q(pat)}*' -EA SilentlyContinue | Sort LastWriteTime -Desc | Select -First {limit} -Expand FullName"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=120)
    lines = [l for l in r.stdout.decode("utf-8", "ignore").splitlines() if not PROTECTED.search(l)]
    return "\n".join(lines) or "찾은 파일이 없습니다."

_PLAN = {"items": []}
@mcp.tool
def update_plan(steps: list[str], done: list[int] = [], current: int = 0, note: str = "") -> str:
    """여러 단계가 필요한 작업의 계획표. 작업 시작 때 steps=[단계들] 로 계획을 세우고, 한 단계 끝날 때마다
    done=[끝난 단계 번호들](1부터), current=지금 할 단계 번호로 다시 부른다. 계획을 보고 빠뜨림·반복 없이 진행한다."""
    if steps: _PLAN["items"] = [str(x) for x in steps][:20]
    items = _PLAN["items"]
    if not items: return "계획이 비어 있습니다. steps 로 단계를 적으세요."
    lines = []
    for i, st in enumerate(items, 1):
        mark = "[완료]" if i in (done or []) else ("[진행중]" if i == current else "[대기]")
        lines.append(f"{i}. {mark} {st}")
    left = [i for i in range(1, len(items) + 1) if i not in (done or [])]
    tail = "모든 단계 완료 — 이제 사용자에게 결과를 정리해 답하세요." if not left else f"남은 단계: {left}. 다음은 {left[0]}번."
    return "\n".join(lines) + ("\n메모: " + note if note else "") + "\n" + tail

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)