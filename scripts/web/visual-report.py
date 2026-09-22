#!/usr/bin/env python3
"""Generate a self-contained HTML QA report from a folder with evidence.json and screenshots.

Usage: python scripts/web/visual-report.py docs/test-results/<run>
The folder's evidence.json describes the run:
  {"title", "label", "intro", "flow": [..], "checks": [..], "limits": [..],
   "scenarios": [{"title", "text", "screenshots": [{"file", "title", "text"}]}], "footer"}
Screenshots are embedded as data URIs so the report works offline. Reports are
delivered separately and never committed (docs/test-results is ignored).
"""
import base64
import html
import json
from pathlib import Path
import sys

STYLE = '''
*{box-sizing:border-box}body{margin:0;background:#0c1017;color:#dce3ed;font:16px/1.65 system-ui,sans-serif}main{max-width:1340px;margin:auto;padding:45px 30px}
header{margin-bottom:38px}.label{color:#b0f0cb;font-size:12px;letter-spacing:2px}h1{font-size:clamp(28px,4vw,48px);line-height:1.15;max-width:1000px}
h2{font-size:26px;margin-top:56px;border-top:1px solid #344153;padding-top:28px}h3{font-size:20px}p{color:#a6b4c5;max-width:1000px}section{margin:34px 0}
img{display:block;width:100%;height:auto;border:1px solid #344153;border-radius:12px;background:#000}
.flow{display:flex;gap:16px;align-items:center;flex-wrap:wrap;background:#121c28;border:1px solid #344153;border-radius:12px;padding:22px}.flow strong{color:#b0f0cb}.flow span{color:#8497ac}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:32px}.card{background:#121a25;border:1px solid #293a4c;border-radius:12px;padding:20px 28px}li{margin:10px 0}code{font-size:14px;color:#b0f0cb}
footer{border-top:1px solid #344153;padding-top:24px;color:#8497ac;margin-top:48px}@media(max-width:750px){main{padding:24px 16px}.grid{grid-template-columns:1fr}}
'''


def render(folder):
    evidence = json.loads((folder / 'evidence.json').read_text())
    e = html.escape
    parts = [f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<title>{e(evidence["title"])}</title><style>{STYLE}</style><main>'
             f'<header><div class="label">{e(evidence["label"])}</div><h1>{e(evidence["title"])}</h1><p>{e(evidence["intro"])}</p></header>']
    flow = '<span>→</span>'.join(f'<strong>{e(step)}</strong>' for step in evidence['flow'])
    parts.append(f'<div class="flow">{flow}</div>')
    checks = ''.join(f'<li>{e(c)}</li>' for c in evidence['checks'])
    limits = ''.join(f'<li>{e(c)}</li>' for c in evidence['limits'])
    parts.append(f'<div class="grid"><section class="card"><h3>Проверено</h3><ul>{checks}</ul></section>'
                 f'<section class="card"><h3>Границы результата</h3><ul>{limits}</ul></section></div>')
    for scenario in evidence['scenarios']:
        parts.append(f'<h2>{e(scenario["title"])}</h2><p>{e(scenario["text"])}</p>')
        for shot in scenario['screenshots']:
            data = base64.b64encode((folder / shot['file']).read_bytes()).decode()
            parts.append(f'<section><h3>{e(shot["title"])}</h3><p>{e(shot["text"])}</p>'
                         f'<img src="data:image/png;base64,{data}" alt="{e(shot["title"])}"></section>')
    parts.append(f'<footer>{e(evidence["footer"])}</footer></main></html>')
    output = folder / 'index.html'
    output.write_text(''.join(parts))
    return output


if __name__ == '__main__':
    print(render(Path(sys.argv[1])))
