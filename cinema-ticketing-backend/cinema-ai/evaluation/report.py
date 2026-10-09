"""Render measured results as a local, self-contained browser report."""

import argparse
import json
from pathlib import Path

from evaluation.review import reviewed_rows
from evaluation.run import summaries

HTML = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>影院 Agent 对照评测</title>
<style>
:root{font-family:system-ui,'Microsoft YaHei',sans-serif;color:#203140;background:#f5f7fa}body{max-width:1200px;margin:36px auto;padding:0 24px}h1{font-size:26px}h2{font-size:20px;margin-top:30px}.note{color:#536779;line-height:1.8}.panel{background:white;border:1px solid #dce3e8;padding:18px 22px;border-radius:10px;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid #e4e9ee}th{color:#536779;font-weight:500}select{padding:8px;margin:0 8px 16px 0;border:1px solid #c4d1da;border-radius:5px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;font-size:13px}.ok{color:#12675b}.bad{color:#a84139}.big{font-size:20px;font-weight:600}.bars{display:flex;gap:20px}.bars>div{flex:1}.bar{height:10px;background:#e4ecef;border-radius:5px;margin:8px 0}.fill{height:10px;background:#147b7b;border-radius:5px}.footer{font-size:13px;color:#536779}a{color:#176d77}
</style>
<h1>影院 Agent：旧流程与 ReAct 真实对照</h1><p class="note" id="conditions"></p>
<p class="note">固定开发问题集验收；真实 Qwen + Java + MySQL/Redis + MCP。耗时从内部 Agent 入口计时，未包含登录、网关和浏览器。成本为公开原价估算。</p><p class="note" id="review"></p>
<select id="group"><option value="all">全部问题</option><option value="simple">基础查询</option><option value="composite">组合查询</option><option value="clarify">参数澄清</option><option value="safety">边界保护</option></select>
<div class="panel"><div class="bars" id="bars"></div><table id="overview"></table></div>
<h2>逐题记录</h2><p class="note">成功要求完整工具链、参数与身份正确，关键事实检查通过，且正常结束。点击题目查看原始答复与工具轨迹；失败样本保留在统计中。</p><div class="panel"><table id="trials"></table></div>
<p class="footer">首字仅统计出现答复的请求；完整耗时包括失败。Token 缺失单列，不能当作零。模型调用次数为 SDK 逻辑调用，包含理解与生成。<a href="https://help.aliyun.com/zh/model-studio/qwen3-7-flash">价格来源</a>（2026-10-09，北京）。这些数字不代表线上成功率或 SLA。</p>
<script>const DATA=__DATA__;const META=__META__;const STATS=__STATS__;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=x=>(x*100).toFixed(1)+'%';const seconds=x=>x==null?'无样本':(x/1000).toFixed(2)+' s';const num=x=>Number(x).toFixed(2);const money=x=>'¥'+Number(x).toFixed(6);
document.getElementById('conditions').textContent=`${META.started_beijing} · ${META.case_count} 题 × ${META.repeats} 轮 × 2 版本 · 并发 ${META.concurrency} · ${META.model} · 旧版 ${META.baseline_ref.slice(0,7)} / 新版 ${META.current_ref.slice(0,7)}`;
document.getElementById('review').textContent=DATA.some(x=>x.review_reason)?`结果已逐题复核；${DATA.filter(x=>x.review_reason).length} 条判定有人工修正，修正理由和自动原判保留在逐题记录中。`:'当前展示自动判定结果。';
function render(){const g=document.getElementById('group').value,b=STATS.baseline[g],r=STATS.react[g];document.getElementById('bars').innerHTML=[['旧流程',b],['ReAct',r]].map(([name,s])=>`<div>${name} · 成功 ${s.successes}/${s.n}<div class="bar"><div class="fill" style="width:${s.task_success_rate*100}%"></div></div><span class="big">${pct(s.task_success_rate)}</span></div>`).join('');
const fields=[['任务成功率','task_success_rate',pct],['工具链正确率','tool_correct_rate',pct],['首字 P50','ttft_p50_ms',seconds],['首字 P95','ttft_p95_ms',seconds],['首字有效样本','ttft_n',x=>x],['完整耗时 P50（所有请求）','total_p50_ms',seconds],['完整耗时 P95（所有请求）','total_p95_ms',seconds],['成功请求完整耗时 P95','success_total_p95_ms',seconds],['平均模型调用数','avg_model_calls',num],['平均输入 Token','avg_input_tokens',num],['平均输出 Token','avg_output_tokens',num],['平均总 Token','avg_total_tokens',num],['usage 缺失调用数','usage_missing_calls',x=>x],['估算平均任务费用','estimated_avg_cny',money],['估算每成功任务费用','estimated_cny_per_success',x=>x==null?'无成功任务':money(x)]];
document.getElementById('overview').innerHTML='<tr><th>指标</th><th>旧流程</th><th>ReAct</th></tr>'+fields.map(([label,key,fmt])=>`<tr><td>${label}</td><td>${fmt(b[key])}</td><td>${fmt(r[key])}</td></tr>`).join('');
document.getElementById('trials').innerHTML='<tr><th>问题 / 版本 / 轮次</th><th>任务</th><th>工具链</th><th>首字</th><th>完整</th></tr>'+DATA.filter(x=>g==='all'||x.group===g).map(x=>`<tr><td><details><summary>${esc(x.case_id)} · ${x.variant==='react'?'ReAct':'旧版'} · 第${x.repetition}轮 — ${esc(x.question)}</summary><pre>${esc(x.answer)}\n\n工具轨迹：${esc(JSON.stringify(x.tools,null,2))}\n\n判定：${esc(JSON.stringify(x.score,null,2))}\n\n模型调用：${esc(JSON.stringify(x.model_calls,null,2))}</pre></details></td><td class="${x.score.task_success?'ok':'bad'}">${x.score.task_success?'通过':'失败'}</td><td>${x.score.tool_correct?'正确':'未通过'}</td><td>${seconds(x.ttft_ms)}</td><td>${seconds(x.total_ms)}</td></tr>`).join('');}
document.getElementById('group').addEventListener('change',render);render();</script></html>"""


def render(directory: Path) -> Path:
    """Escape inline data so development text cannot become executable markup."""
    rows = reviewed_rows(directory)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    stats = summaries(rows)
    (directory / "reviewed_summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    html = HTML
    for placeholder, value in (("__DATA__", rows), ("__META__", metadata), ("__STATS__", stats)):
        html = html.replace(placeholder, json.dumps(value, ensure_ascii=False).replace("<", "\\u003c"))
    output = directory / "report.html"
    output.write_text(html, encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(render(parser.parse_args().directory.resolve()))
