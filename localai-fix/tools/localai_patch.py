"""improve-localai.ps1 도우미 (LocalAI 의 파이썬으로 실행).

  db      : Open WebUI DB 의 필터 코드 교체·밸브 초기화, 기본 컨텍스트 압축 끄기, 도구 서버 인증키 반영
            (대화 테이블(chat 등)은 읽지도 쓰지도 않는다. function / config / user.settings / model 만 다룸)
  json    : tool-servers.json 인증키, mcp-config.json 실행 파일 경로 갱신
  verify  : 새 필터 코드가 '사용자 질문 사라짐'·'문맥 초과'를 막는지 가짜 대화로 검사

결과는 마지막 줄에 JSON 한 줄로 출력한다.
"""
import argparse, asyncio, json, os, re, sqlite3, sys, tempfile, time, importlib.util, pathlib

COMPACT = re.compile(r"compaction", re.I)  # 화면용 "compact" 모드 같은 건 건드리지 않게
DISABLE = re.compile(r"disable", re.I)
ONOFF = re.compile(r"^(enable|enabled|on|active|auto)$|^enable_", re.I)
MCPO = "http://127.0.0.1:8765"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def turn_off_compaction(obj, path, changed):
    """JSON 안에서 'compaction' 이 들어간 설정을 찾아 끈다. disable_* 는 반대로 켠다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if COMPACT.search(k):
                if isinstance(v, bool):
                    want = bool(DISABLE.search(k))
                    if v != want:
                        obj[k] = want; changed.append(f"{p}: {v} -> {want}")
                    continue
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        if isinstance(v2, bool) and (ONOFF.search(k2) or DISABLE.search(k2)):
                            want = bool(DISABLE.search(k2))
                            if v2 != want:
                                v[k2] = want; changed.append(f"{p}.{k2}: {v2} -> {want}")
            turn_off_compaction(v, p, changed)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            turn_off_compaction(v, f"{path}[{i}]", changed)


def set_tool_keys(obj, key, changed, path=""):
    if isinstance(obj, dict):
        u = obj.get("url")
        if isinstance(u, str) and u.startswith(MCPO) and "auth_type" in obj:
            if obj.get("auth_type") != "bearer" or obj.get("key") != key:
                obj["auth_type"] = "bearer"; obj["key"] = key; changed.append(f"{path or 'root'} ({u})")
        for k, v in obj.items():
            set_tool_keys(v, key, changed, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            set_tool_keys(v, key, changed, f"{path}[{i}]")


def cols(con, table):
    return [r[1] for r in con.execute(f"pragma table_info({table})")]


FUNC_HINT = {  # id 로 못 찾을 때 코드 안의 특징 문자열로 찾음
    "context_guard": "def _drop_oldest",
    "auto_summary": "이전 대화 요약 중",
}


def cmd_db(a):
    rep = {"functions": {}, "compaction_off": [], "tool_server_keys": [], "env_disable": [], "errors": []}
    con = sqlite3.connect(a.db, timeout=30)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    # 1) 필터 코드 교체 + 밸브 초기화
    if "function" in tables:
        fc = cols(con, "function")
        for f in sorted(pathlib.Path(a.functions).glob("*.py")):
            fid = f.stem
            row = con.execute("select id from function where id=?", (fid,)).fetchone()
            if not row:
                hint = FUNC_HINT.get(fid)
                row = con.execute("select id from function where content like ?", (f"%{hint}%",)).fetchone() if hint else None
            if not row:
                rep["functions"][fid] = "없음(건너뜀)"; continue
            sets, vals = ["content=?"], [f.read_text(encoding="utf-8")]
            if "valves" in fc: sets.append("valves=NULL")
            if "updated_at" in fc: sets.append("updated_at=?"); vals.append(int(time.time()))
            con.execute(f"update function set {', '.join(sets)} where id=?", (*vals, row[0]))
            rep["functions"][fid] = f"교체됨(id={row[0]}, 밸브 초기화)"
    else:
        rep["errors"].append("function 테이블 없음")
    # 2) 전역 설정: 기본 압축 끄기 + 도구 서버 인증키
    if "config" in tables and "data" in cols(con, "config"):
        for cid, data in con.execute("select id, data from config").fetchall():
            try:
                j = json.loads(data) if isinstance(data, str) else None
            except Exception:
                j = None
            if not isinstance(j, (dict, list)):
                continue
            ch, tk = [], []
            if a.compaction_off: turn_off_compaction(j, "", ch)
            if a.mcpo_key: set_tool_keys(j, a.mcpo_key, tk)
            if ch or tk:
                con.execute("update config set data=? where id=?", (json.dumps(j, ensure_ascii=False), cid))
                rep["compaction_off"] += [f"config:{c}" for c in ch]; rep["tool_server_keys"] += [f"config:{t}" for t in tk]
    # 3) 사용자별 설정 / 모델별 설정에 들어 있는 압축 스위치
    if a.compaction_off:
        for table, col in (("user", "settings"), ("model", "params"), ("model", "meta")):
            if table in tables and col in cols(con, table):
                for rid, data in con.execute(f"select id, {col} from {table}").fetchall():
                    try:
                        j = json.loads(data) if isinstance(data, str) else None
                    except Exception:
                        j = None
                    if not isinstance(j, dict):
                        continue
                    ch = []
                    turn_off_compaction(j, "", ch)
                    if ch:
                        con.execute(f"update {table} set {col}=? where id=?", (json.dumps(j, ensure_ascii=False), rid))
                        rep["compaction_off"] += [f"{table}.{col}[{rid}]:{c}" for c in ch]
    con.commit(); con.close()
    # 4) 아직 DB 에 저장된 적 없는 설정은 환경변수로 끈다: Open WebUI 소스에서 이름을 찾음
    if a.compaction_off and a.webui_src and os.path.isdir(a.webui_src):
        names = set()
        for py in pathlib.Path(a.webui_src).rglob("*.py"):
            try:
                t = py.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if "COMPACTION" not in t:
                continue
            names.update(re.findall(r"""["']([A-Z][A-Z0-9_]*COMPACTION[A-Z0-9_]*)["']""", t))
        rep["env_disable"] = sorted(n for n in names if n.startswith("ENABLE"))
        rep["env_enable"] = sorted(n for n in names if n.startswith("DISABLE"))
    print(json.dumps(rep, ensure_ascii=False))


def write_json(path, obj):
    txt = json.dumps(obj, ensure_ascii=False, indent=2).replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:  # BOM 없이 (Open WebUI 가 env 로 읽음)
        f.write(txt)


def cmd_json(a):
    rep = {"tool_servers": [], "mcp_config": []}
    if a.tool_servers and a.mcpo_key and os.path.exists(a.tool_servers):
        j = json.load(open(a.tool_servers, encoding="utf-8-sig"))
        ch = []
        set_tool_keys(j, a.mcpo_key, ch)
        if ch: write_json(a.tool_servers, j)
        rep["tool_servers"] = ch
    if a.mcp_config and a.bin and os.path.exists(a.mcp_config):
        j = json.load(open(a.mcp_config, encoding="utf-8-sig"))
        for name, exe in (("time", "mcp-server-time.exe"), ("fetch", "mcp-server-fetch.exe")):
            s = j.get("mcpServers", {}).get(name)
            new = os.path.join(a.bin, exe)
            if s and os.path.exists(new) and s.get("command") != new:
                rep["mcp_config"].append(f"{name}: {s.get('command')} -> {new}")
                s["command"] = new
        if rep["mcp_config"]: write_json(a.mcp_config, j)
    print(json.dumps(rep, ensure_ascii=False))


def load(path):
    spec = importlib.util.spec_from_file_location(pathlib.Path(path).stem + "_t", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def cmd_verify(a):
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    fd = pathlib.Path(a.functions)
    res, ok = {}, True

    def check(name, cond):
        nonlocal ok
        res[name] = "통과" if cond else "실패"; ok = ok and bool(cond)

    g = load(fd / "context_guard.py").Filter()
    s = load(fd / "auto_summary.py").Filter()

    async def fake(model, prev, msgs):
        return "요약"
    s._summarize = fake
    roles = lambda b: [m["role"] for m in b["messages"]]
    # 1) 도구 연속 호출 중 요약해도 사용자 질문이 남는가
    loop = [{"role": "system", "content": "S"}, {"role": "user", "content": "old"}, {"role": "assistant", "content": "a" * 3000},
            {"role": "user", "content": "작업해줘"}] + [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "x", "arguments": "{}"}}]},
                                                       {"role": "tool", "content": "가" * 4000}] * 6
    for model in ("qwen-heretic-16k:latest", "qwen-heretic-32k:latest"):
        out = asyncio.run(s.inlet({"model": model, "messages": json.loads(json.dumps(loop))}, __chat_id__="verify-" + model))
        r = roles(out)
        check(f"auto_summary {model.split(':')[0]}: 사용자 질문 유지", "user" in r)
        check(f"auto_summary {model.split(':')[0]}: system 은 맨 앞 하나", r.count("system") == 1 and r[0] == "system")
    # 2) 문맥 크기 인식 (16/32/64/262K)
    for k, v in (("16k", 16384), ("32k", 32768), ("64k", 65536), ("262k", 262144)):
        check(f"auto_summary 문맥 인식 {k}", s._ctx(f"qwen-heretic-{k}:latest") == v)
        check(f"context_guard 문맥 인식 {k}", g._ctx({"model": f"qwen-heretic-{k}:latest"}, None) == v)
    # 3) 사용자 질문이 하나도 없으면 채워 넣는가 (No user query found 방지)
    b = g.inlet({"model": "qwen-heretic-32k:latest", "messages": [{"role": "system", "content": "S"}, {"role": "assistant", "content": "x"}, {"role": "tool", "content": "y"}]})
    check("context_guard: 사용자 질문 없을 때 채움", "user" in roles(b))
    # 4) 넘치는 대화를 예산 안으로 줄이는가
    for k, ctx in (("16k", 16384), ("32k", 32768)):
        big = {"model": f"qwen-heretic-{k}:latest", "messages": [{"role": "system", "content": "S"}] +
               [{"role": "user", "content": "질문" * 10}, {"role": "assistant", "content": "답" * 6000}] * 8 + [{"role": "user", "content": "마지막"}]}
        r = g.inlet(big)
        check(f"context_guard {k}: 예산 안으로 줄임", g._total(r) <= int(ctx * g.valves.fill_ratio) - g.valves.reserve_output)
        check(f"context_guard {k}: 마지막 질문 유지", r["messages"][-1]["content"] == "마지막")
    print(json.dumps({"ok": ok, "results": res}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("db"); d.add_argument("--db", required=True); d.add_argument("--functions", required=True)
    d.add_argument("--mcpo-key", default=""); d.add_argument("--webui-src", default=""); d.add_argument("--compaction-off", action="store_true")
    j = sp.add_parser("json"); j.add_argument("--tool-servers"); j.add_argument("--mcp-config"); j.add_argument("--mcpo-key", default=""); j.add_argument("--bin", default="")
    v = sp.add_parser("verify"); v.add_argument("--functions", required=True)
    a = ap.parse_args()
    {"db": cmd_db, "json": cmd_json, "verify": cmd_verify}[a.cmd](a)
