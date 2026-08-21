import json, glob, os, re

d = r"F:\CSUProgram\smart-medical-analysis-platform\智慧医疗项目\代码实现\3.AI交互"
files = sorted(glob.glob(os.path.join(d, "resp_*.json")))
for f in files:
    base = os.path.basename(f)  # resp_1_profit_difference.json
    m = re.match(r"resp_(\d+)_(.+)\.json", base)
    if not m:
        continue
    idx, name = m.group(1), m.group(2)
    with open(f, encoding="utf-8") as fh:
        obj = json.load(fh)
    intent = obj.get("intent", {}) or {}
    meta = obj.get("meta", {}) or {}
    ans = obj.get("answer", "")
    src = intent.get("_source", "")
    hint = intent.get("chart_hint", "")
    ctype = (obj.get("chart") or {}).get("chart_type", "")
    agent_out = meta.get("agent_output", "") if isinstance(meta, dict) else ""
    q = ""
    # recover question from answer text if possible
    mm = re.search(r"「(.+?)」", ans)
    if mm:
        q = mm.group(1)
    out = []
    out.append("Q: " + q)
    out.append("intent_source: " + src)
    out.append("chart_hint: " + str(hint) + "  chart_type: " + str(ctype))
    out.append("")
    out.append("----- answer (user-facing, reliable) -----")
    out.append(ans)
    if agent_out:
        out.append("")
        out.append("----- agent_output (LangChain free-form, hallucination risk) -----")
        out.append(agent_out)
    out_path = os.path.join(d, "answer_%s_%s.txt" % (idx, name))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("wrote", out_path)
print("done, files:", len(files))
