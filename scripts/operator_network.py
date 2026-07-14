#!/usr/bin/env python3
"""Operator / template-family network graph — self-contained interactive HTML.

Two overlapping groupings drawn as one node-link graph:
  * operator clusters (operator_matching): members sharing a hard signal
    (cert / favicon / IP / site-name) — SOLID colored edges.
  * template families (site_similarity): members sharing a rare build feature
    (ASN / registrar / server / favicon) — DASHED grey edges.

A site linked by both is a strong "same shop" signal. No external libraries
(inline SVG + a tiny force sim) so it renders as an artifact. Rerun on new data.

    python3 scripts/operator_network.py   # -> results/master/operator_network.html
"""
from __future__ import annotations
import csv
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")


def load(name):
    p = os.path.join(M, name)
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if os.path.exists(p) else []


def g(r, c):
    return (r.get(c) or "").strip()


def main():
    profs = [p for p in load("operator_profiles.csv")
             if str(g(p, "domain_count")).isdigit() and int(g(p, "domain_count")) > 1]
    fams = load("site_similarity_clusters.csv")

    nodes, idx = [], {}
    edges = []

    def node(dom, op=""):
        if dom not in idx:
            idx[dom] = len(nodes)
            nodes.append({"id": dom, "op": op})
        elif op and not nodes[idx[dom]]["op"]:
            nodes[idx[dom]]["op"] = op
        return idx[dom]

    # operator edges (solid, colored by operator)
    for p in profs:
        members = [m for m in g(p, "member_domains").split(";") if m]
        op = g(p, "operator_id")
        basis = g(p, "merge_basis")
        for m in members:
            node(m, op)
        for m in members[1:]:               # star from the first member
            edges.append({"s": idx[members[0]], "t": idx[m], "k": "op",
                          "op": op, "why": basis[:60]})

    # template-family edges (dashed grey)
    for f in fams:
        members = [m for m in g(f, "members").split(";") if m]
        feat = g(f, "shared_features")
        for m in members:
            node(m)
        for m in members[1:]:
            edges.append({"s": idx[members[0]], "t": idx[m], "k": "fam",
                          "op": "", "why": feat[:60]})

    data = {"nodes": nodes, "edges": edges}
    payload = json.dumps(data, ensure_ascii=False)

    n_op = len({n["op"] for n in nodes if n["op"]})
    html = TEMPLATE.replace("/*__DATA__*/", payload) \
                   .replace("__NN__", str(len(nodes))) \
                   .replace("__NE__", str(len(edges))) \
                   .replace("__NO__", str(n_op))
    out = os.path.join(M, "operator_network.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"Wrote {out}  ({len(nodes)} 节点 · {len(edges)} 边 · {n_op} 运营者簇 + {len(fams)} 模板家族)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>运营者 / 模板家族 关系图</title>
<style>
  :root{--bg:#0e1116;--ink:#e8ecf3;--mut:#8b93a3;--line:#3a4150;--fam:#586074;}
  *{margin:0;box-sizing:border-box}
  body{background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
  header{padding:16px 20px;border-bottom:1px solid var(--line)}
  h1{font-size:18px;font-weight:640}
  .sub{color:var(--mut);font-size:13px;margin-top:4px}
  .legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--mut)}
  .legend b{color:var(--ink);font-weight:600}
  svg{width:100vw;height:calc(100vh - 92px);display:block;cursor:grab}
  .lk{stroke:var(--line);stroke-width:1.2}
  .lk.fam{stroke:var(--fam);stroke-dasharray:3 3;stroke-width:1}
  .nd{stroke:#0e1116;stroke-width:1.2;cursor:pointer}
  #tip{position:fixed;pointer-events:none;background:#000;color:#fff;font-size:12px;
    padding:6px 9px;border-radius:6px;opacity:0;white-space:nowrap;transition:opacity .1s;z-index:9}
</style>
</head>
<body>
<header>
  <h1>运营者 / 模板家族 关系图</h1>
  <div class="sub">__NN__ 个站点 · __NE__ 条共享关系 · __NO__ 个多站运营者簇 + 模板家族。拖动画布/节点,悬停看域名与归并依据。</div>
  <div class="legend">
    <span><b style="color:#e8ecf3">●</b> 站点(同色=同一运营者)</span>
    <span><b>——</b> 运营者硬信号(证书/favicon/IP/站名)</span>
    <span><b style="color:#586074">- -</b> 模板家族(共享搭建特征)</span>
  </div>
</header>
<svg id="g"></svg>
<div id="tip"></div>
<script>
const D=/*__DATA__*/;
const svg=document.getElementById("g"), tip=document.getElementById("tip");
let W=svg.clientWidth,H=svg.clientHeight;
const NS="http://www.w3.org/2000/svg";
// color per operator
const ops=[...new Set(D.nodes.map(n=>n.op).filter(Boolean))];
const col=o=>{if(!o)return"#c3cad6";let h=0;for(const c of o)h=(h*31+c.charCodeAt(0))%360;return`hsl(${h},62%,60%)`};
// init positions (deterministic ring, no RNG)
D.nodes.forEach((n,i)=>{const a=i*2.399963;const r=40+8*Math.sqrt(i);
  n.x=W/2+r*Math.cos(a); n.y=H/2+r*Math.sin(a); n.vx=0; n.vy=0;});
// build svg
const gLink=document.createElementNS(NS,"g"), gNode=document.createElementNS(NS,"g");
svg.append(gLink,gNode);
const L=D.edges.map(e=>{const l=document.createElementNS(NS,"line");
  l.setAttribute("class","lk"+(e.k==="fam"?" fam":""));
  if(e.k==="op")l.setAttribute("stroke",col(e.op));
  l.dataset.why=(e.k==="op"?"运营者["+e.op+"]: ":"模板: ")+e.why; gLink.append(l); return l;});
const N=D.nodes.map((n,i)=>{const c=document.createElementNS(NS,"circle");
  const deg=D.edges.filter(e=>e.s===i||e.t===i).length;
  c.setAttribute("r",Math.min(4+deg,10)); c.setAttribute("class","nd");
  c.setAttribute("fill",col(n.op)); gNode.append(c);
  c.addEventListener("mousemove",ev=>{tip.style.opacity=1;tip.style.left=(ev.clientX+12)+"px";
    tip.style.top=(ev.clientY+12)+"px";tip.textContent=n.id+(n.op?"  ·  "+n.op:"");});
  c.addEventListener("mouseleave",()=>tip.style.opacity=0);
  c.addEventListener("mousedown",ev=>{drag=n;ev.stopPropagation();}); return c;});
// force sim
function tick(){
  for(const n of D.nodes){n.vx*=.9;n.vy*=.9;}
  for(let a=0;a<D.nodes.length;a++)for(let b=a+1;b<D.nodes.length;b++){
    const p=D.nodes[a],q=D.nodes[b];let dx=p.x-q.x,dy=p.y-q.y,d=Math.hypot(dx,dy)||1;
    if(d<120){const f=(120-d)/d*.02;p.vx+=dx*f;p.vy+=dy*f;q.vx-=dx*f;q.vy-=dy*f;}}
  for(const e of D.edges){const p=D.nodes[e.s],q=D.nodes[e.t];
    let dx=q.x-p.x,dy=q.y-p.y,d=Math.hypot(dx,dy)||1;const f=(d-46)/d*.03;
    p.vx+=dx*f;p.vy+=dy*f;q.vx-=dx*f;q.vy-=dy*f;}
  for(const n of D.nodes){if(n===drag)continue;n.x+=n.vx;n.y+=n.vy;
    n.x=Math.max(8,Math.min(W-8,n.x));n.y=Math.max(8,Math.min(H-8,n.y));}
  D.edges.forEach((e,i)=>{L[i].setAttribute("x1",D.nodes[e.s].x);L[i].setAttribute("y1",D.nodes[e.s].y);
    L[i].setAttribute("x2",D.nodes[e.t].x);L[i].setAttribute("y2",D.nodes[e.t].y);});
  D.nodes.forEach((n,i)=>{N[i].setAttribute("cx",n.x);N[i].setAttribute("cy",n.y);});
  requestAnimationFrame(tick);
}
let drag=null,pan=null;
svg.addEventListener("mousemove",ev=>{if(drag){drag.x=ev.clientX;drag.y=ev.clientY-70;drag.vx=drag.vy=0;}});
window.addEventListener("mouseup",()=>drag=null);
window.addEventListener("resize",()=>{W=svg.clientWidth;H=svg.clientHeight;});
tick();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
