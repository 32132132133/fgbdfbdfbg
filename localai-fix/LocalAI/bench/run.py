import json,sys,time,sqlite3,httpx,re,os
OL="http://127.0.0.1:11434/api/chat"; MC="http://127.0.0.1:8765/desktop"
_kf=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),".mcpo_key")
HD={"Authorization":"Bearer "+open(_kf,encoding="utf-8").read().strip()} if os.path.exists(_kf) else {}
specs={k:httpx.get(f"http://127.0.0.1:8765/{k}/openapi.json").json() for k in ("tools",)}; route={}; spec=None
def res(o):
    if isinstance(o,dict):
        if "$ref" in o:
            n=o["$ref"].split("/")[-1]; return res(spec["components"]["schemas"][n])
        return {k:res(v) for k,v in o.items()}
    if isinstance(o,list): return [res(x) for x in o]
    return o
tools=[]
for srv,sp in specs.items():
  spec=sp
  for path,ops in sp["paths"].items():
    route[path.strip("/")]=srv; op=ops["post"]; sch=res(op.get("requestBody",{}).get("content",{}).get("application/json",{}).get("schema",{"type":"object","properties":{}}))
    tools.append({"type":"function","function":{"name":path.strip("/"),"description":op.get("description") or op.get("summary",""),"parameters":sch}})
c=sqlite3.connect(r"C:\Users\gu214\LocalAI\webui-data\webui.db")
sysmsg=json.loads(c.execute("select params from model where id='qwen-heretic-32k:latest'").fetchone()[0])["system"]
sysmsg=sysmsg.replace("{{CURRENT_DATE}}","2026-09-22").replace("{{CURRENT_WEEKDAY}}","화").replace("{{CURRENT_TIME}}","12:00")
skill=c.execute("select content from skill where id='windows-control'").fetchone()[0]
if os.environ.get("WITHSKILL"): sysmsg+="\n\n"+skill
model=os.environ.get("M","qwen-heretic-32k")
task=json.load(open(os.path.join(os.path.dirname(__file__),"tasks.json"),encoding="utf-8"))[sys.argv[1]]; maxit=int(os.environ.get("MAXIT","25"))
msgs=[{"role":"system","content":sysmsg},{"role":"user","content":task}]
t0=time.time()
for it in range(maxit):
    r=httpx.post(OL,json={"model":model,"messages":msgs,"tools":tools,"stream":False,"think":False,"options":{"temperature":0.3}},timeout=600).json()
    m=r["message"]; msgs.append(m)
    tcs=m.get("tool_calls") or []
    if not tcs:
        print(f"[{time.time()-t0:.0f}s] FINAL:",m.get("content","")[:600]); break
    for tc in tcs:
        f=tc["function"]; a=f.get("arguments") or {}
        try:
            out=httpx.post(f"http://127.0.0.1:8765/{route.get(f['name'],'desktop')}/{f['name']}",json=a,headers=HD,timeout=600).text
        except Exception as e: out=f"ERR {e}"
        try:
            v=json.loads(out); out=v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)
        except: pass
        print(f"[{time.time()-t0:.0f}s] #{it} {f['name']} {json.dumps(a,ensure_ascii=False)[:200]}\n   -> {out[:250].replace(chr(10),' | ')} ... {out[-200:].replace(chr(10),' | ')}")
        msgs.append({"role":"tool","content":out[:8000],"tool_name":f["name"]})
else: print("MAXIT reached")