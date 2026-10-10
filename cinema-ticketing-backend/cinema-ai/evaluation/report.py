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
<h1 id="title">影院 Agent：旧流程与 ReAct 真实对照</h1><p class="note" id="conditions"></p>
<p class="note">固定开发问题集验收；真实 Qwen + Java + MySQL/Redis + MCP。耗时从内部 Agent 入口计时，未包含登录、网关和浏览器。成本为公开原价估算。</p><p class="note">答案指标仅检查预先声明的关键事实和正常完成，需结合逐题人工复核；工具链指标保持严格判定。多余调用按实际业务调用与允许方案的最大一一匹配统计，忽略顺序；漏查和顺序错误不算多查。</p><p class="note" id="review"></p>
<select id="group"><option value="all">全部问题</option><option value="simple">基础查询</option><option value="composite">组合查询</option><option value="clarify">参数澄清</option><option value="safety">边界保护</option></select>
<div class="panel"><div class="bars" id="bars"></div><table id="overview"></table></div>
<div id="loops"></div>
<div id="rerank"></div>
<div id="evidence"></div>
<h2>逐题记录</h2><p class="note">成功要求完整工具链、参数与身份正确，关键事实检查通过，且正常结束。点击题目查看原始答复与工具轨迹；失败样本保留在统计中。</p><div class="panel"><table id="trials"></table></div>
<p class="footer">首字仅统计出现答复的请求；完整耗时包括失败。Token 缺失单列，不能当作零。模型调用次数为 SDK 逻辑调用，包含理解与生成。<a href="https://help.aliyun.com/zh/model-studio/qwen3-7-flash">价格来源</a>（2026-10-09，北京）。这些数字不代表线上成功率或 SLA。</p>
<script>const DATA=__DATA__;const META=__META__;const STATS=__STATS__;const EVIDENCE=__EVIDENCE__;const LOOP=__LOOP__;const RUNTIME=__RUNTIME__;
const labels=META.variant_labels||{baseline:'旧流程',react:'ReAct'};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=x=>(x*100).toFixed(1)+'%';const seconds=x=>x==null?'无样本':(x/1000).toFixed(2)+' s';const num=x=>Number(x).toFixed(2);const money=x=>'¥'+Number(x).toFixed(6);
document.getElementById('title').textContent=`影院 Agent：${labels.baseline} 与 ${labels.react} 真实对照`;
document.getElementById('conditions').textContent=`${META.started_beijing} · ${META.case_count} 题 × ${META.repeats} 轮 × 2 版本 · 并发 ${META.concurrency} · ${META.model} · ${META.baseline_mode==='rerank-off'?'同一工作区源码，仅重排开关不同；源码已留存':`旧版 ${META.baseline_ref.slice(0,7)} / 新版 ${META.current_ref.slice(0,7)}`}`;
document.getElementById('review').textContent=DATA.some(x=>x.review_reason)?`已记录 ${DATA.filter(x=>x.review_reason).length} 条人工判定修正，修正理由和自动原判保留在逐题记录中；不代表完成逐字语义审计。`:'当前展示自动判定结果。';
function render(){const g=document.getElementById('group').value,b=STATS.baseline[g],r=STATS.react[g];document.getElementById('bars').innerHTML=[[labels.baseline,b],[labels.react,r]].map(([name,s])=>`<div>${esc(name)} · 成功 ${s.successes}/${s.n}<div class="bar"><div class="fill" style="width:${s.task_success_rate*100}%"></div></div><span class="big">${pct(s.task_success_rate)}</span></div>`).join('');
const fields=[['严格任务成功率','task_success_rate',pct],['答案关键事实通过率','answer_correct_rate',pct],['工具链正确率','tool_correct_rate',pct],['有多余调用的任务比例','extra_tool_task_rate',pct],['多余调用占业务调用比例','extra_tool_call_rate',pct],['有无效调用的任务比例','rejected_task_rate',pct],['首字 P50','ttft_p50_ms',seconds],['首字 P95','ttft_p95_ms',seconds],['首字有效样本','ttft_n',x=>x],['完整耗时 P50（所有请求）','total_p50_ms',seconds],['完整耗时 P95（所有请求）','total_p95_ms',seconds],['成功请求完整耗时 P95','success_total_p95_ms',seconds],['平均模型调用数','avg_model_calls',num],['平均输入 Token','avg_input_tokens',num],['平均输出 Token','avg_output_tokens',num],['平均总 Token','avg_total_tokens',num],['usage 缺失调用数','usage_missing_calls',x=>x],['估算平均任务费用','estimated_avg_cny',money],['估算每成功任务费用','estimated_cny_per_success',x=>x==null?'无成功任务':money(x)]];
fields.push(['平均调用数（聊天+重排）','avg_all_model_calls',num],['平均 Token（聊天+重排）','avg_all_tokens',num],['平均费用（聊天+重排）','estimated_avg_task_cny',money]);
document.getElementById('overview').innerHTML=`<tr><th>指标</th><th>${esc(labels.baseline)}</th><th>${esc(labels.react)}</th></tr>`+fields.map(([label,key,fmt])=>`<tr><td>${label}</td><td>${fmt(b[key])}</td><td>${fmt(r[key])}</td></tr>`).join('');
if(META.baseline_mode==='rerank-off'){const rb=b.rerank,rr=r.rerank;const rf=[['规则检索次数','policy_retrieval_calls',x=>x],['真实重排请求','provider_attempts',x=>x],['云端成功','provider_successes',x=>x],['回退','fallbacks',x=>x],['重排 usage 缺失','usage_missing_requests',x=>x],['重排总 Token','total_tokens',x=>x],['重排耗时 P50 / P95',null,()=>null],['平均重排费用','estimated_avg_cny',money]];document.getElementById('rerank').innerHTML='<h2>重排观测</h2><p class="note">关闭/跳过不计为云端成功。下方费用已计入任务总费用；缺失 usage 的请求可能造成低估。<a href="https://help.aliyun.com/zh/model-studio/qwen3-7-text-rerank">重排价格来源</a></p><div class="panel"><table><tr><th>指标</th><th>重排关闭</th><th>重排开启</th></tr>'+rf.map(([name,key,fmt])=>`<tr><td>${name}</td><td>${key?fmt(rb[key]):seconds(rb.p50_ms)+' / '+seconds(rb.p95_ms)}</td><td>${key?fmt(rr[key]):seconds(rr.p50_ms)+' / '+seconds(rr.p95_ms)}</td></tr>`).join('')+'</table></div>';}
document.getElementById('trials').innerHTML='<tr><th>问题 / 版本 / 轮次</th><th>任务</th><th>工具链</th><th>首字</th><th>完整</th></tr>'+DATA.filter(x=>g==='all'||x.group===g).map(x=>`<tr><td><details><summary>${esc(x.case_id)} · ${esc(labels[x.variant])} · 第${x.repetition}轮 — ${esc(x.question)}</summary><pre>${esc(x.answer)}\n\n工具轨迹：${esc(JSON.stringify(x.tools,null,2))}\n\n判定：${esc(JSON.stringify(x.score,null,2))}\n\n模型调用：${esc(JSON.stringify(x.model_calls,null,2))}\n\n重排观测：${esc(JSON.stringify(x.rerank_calls||[],null,2))}</pre></details></td><td class="${x.score.task_success?'ok':'bad'}">${x.score.task_success?'通过':'失败'}</td><td>${x.score.tool_correct?'正确':'未通过'}</td><td>${seconds(x.ttft_ms)}</td><td>${seconds(x.total_ms)}</td></tr>`).join('');}
document.getElementById('group').addEventListener('change',render);render();
if(LOOP){const a=LOOP.variants.baseline,b=LOOP.variants.react;
const fields=[['正常结束请求','normal_completion'],['超时请求','timeout_tasks'],['重复执行同参数工具的任务','duplicate_execution_tasks'],['模型重复提议同参数工具的任务','repeated_proposal_tasks'],['单任务最多业务调用','max_business_calls'],['单任务最多无效调用','max_invalid_calls'],['单任务最多工具决策轮数','max_decision_turns']];
document.getElementById('loops').innerHTML='<h2>ReAct 退出检查 · 全部请求</h2><p class="note">正常结束与答案正确分开统计。同一工具查询不同订单或场次是正常多步流程；重复执行按同一请求中的工具名、参数和用户身份判定。模型重复提议与实际执行分列。业务调用上限 '+LOOP.business_call_budget+'，无效调用上限 '+LOOP.invalid_call_budget+'，决策轮数上限 '+LOOP.decision_turn_budget+'。</p><div class="panel"><table><tr><th>指标</th><th>'+esc(labels.baseline)+'</th><th>'+esc(labels.react)+'</th></tr>'+fields.map(([name,key])=>'<tr><td>'+name+'</td><td>'+a[key]+'</td><td>'+b[key]+'</td></tr>').join('')+'</table></div>';
if(RUNTIME){const s=RUNTIME.summary;document.getElementById('loops').innerHTML+='<p class="note">另对当前运行的 '+esc(s.agent_url)+' 服务检查 '+s.count+' 题，正常完成 '+s.completed+' 题，客户端超时 '+s.client_timeouts+' 次，最长 '+seconds(s.max_elapsed_ms)+'。该检查使用当前服务，以上对照使用同源码隔离评测实例。</p><div class="panel">'+RUNTIME.trials.map(x=>'<details><summary>'+esc(x.case_id)+' · '+esc(x.question)+' · '+seconds(x.total_ms)+'</summary><pre>'+esc(x.answer)+'\n工具：'+esc(JSON.stringify(x.tool_calls))+'\n无效调用：'+x.invalid_call_count+'\n结束事件：'+x.complete+'</pre></details>').join('')+'</div>';}}
if(RUNTIME?.summary?.partial_task_cases?.length){document.getElementById('loops').innerHTML+='<p class="note">当前服务边界题 '+esc(RUNTIME.summary.partial_task_cases.join('、'))+' 返回明确标注的部分结果；收到正常结束事件不代表完成全部任务。这些题不计入正式对照成功率。</p>';}
</script></html>"""


def render(directory: Path, evidence_directory: Path | None = None, runtime_directory: Path | None = None) -> Path:
    """Escape inline data so development text cannot become executable markup."""
    rows = reviewed_rows(directory)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    stats = summaries(rows)
    (directory / "reviewed_summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    html = HTML.replace("估算平均任务费用", "估算平均聊天费用").replace("估算每成功任务费用", "估算每成功任务聊天费用")
    evidence = None
    loop_path = directory / "loop-audit.json"
    loop = json.loads(loop_path.read_text(encoding="utf-8")) if loop_path.exists() else None
    runtime = None
    if runtime_directory:
        runtime = {
            "summary": json.loads((runtime_directory / "summary.json").read_text(encoding="utf-8")),
            "trials": json.loads((runtime_directory / "trials.json").read_text(encoding="utf-8")),
        }
    if evidence_directory:
        evidence = {
            "summary": json.loads((evidence_directory / "summary.json").read_text(encoding="utf-8")),
            "trials": [
                json.loads(line)
                for line in (evidence_directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()
            ],
        }
        html = html.replace(
            "</script>",
            """if(EVIDENCE){const b=EVIDENCE.summary.baseline,r=EVIDENCE.summary.react;
const f=[['首位证据命中率','top1_hit',pct],['前4证据覆盖率','selected_hit',pct],['MRR','mrr',x=>Number(x).toFixed(3)],['NDCG@4','ndcg_at_n',x=>Number(x).toFixed(3)],['来源映射正确率','provenance_correct_rate',pct]];
document.getElementById('evidence').innerHTML='<h2>规则证据专项 · 12题 × 两版 × 2轮</h2><p class="note">10道有答案题（20次/版）统计命中与排序；2道无答案题单列。冻结同一真实候选池，直接比较重排；不经过 Agent 规划、不生成答案。相关性不等于规则权威性。候选来自本轮冻结的真实数据库和本地文档；候选数量及每次选中证据可在逐题记录查看。</p><div class="panel"><table><tr><th>指标</th><th>重排关闭</th><th>重排开启</th></tr>'+f.map(([name,key,fmt])=>`<tr><td>${name}</td><td>${fmt(b[key])}</td><td>${fmt(r[key])}</td></tr>`).join('')+`<tr><td>重排P50 / P95</td><td>关闭</td><td>${seconds(r.rerank.p50_ms)} / ${seconds(r.rerank.p95_ms)}</td></tr><tr><td>平均重排费用</td><td>¥0</td><td>${money(r.rerank.estimated_avg_cny)}</td></tr></table></div><p class="note">专项成功、回退及无答案题返回片段的次数见 summary.json；返回片段不等于生成模型编造了答案。</p><div class="panel">`+EVIDENCE.trials.map(x=>`<details><summary>${esc(x.case_id)} · ${esc(labels[x.variant])} · 第${x.repetition}轮 · ${esc(x.question)}</summary><pre>${esc(JSON.stringify(x,null,2))}</pre></details>`).join('')+'</div>';}
</script>""",
        )
    for placeholder, value in (
        ("__DATA__", rows),
        ("__META__", metadata),
        ("__STATS__", stats),
        ("__EVIDENCE__", evidence),
        ("__LOOP__", loop),
        ("__RUNTIME__", runtime),
    ):
        html = html.replace(placeholder, json.dumps(value, ensure_ascii=False).replace("<", "\\u003c"))
    output = directory / "report.html"
    output.write_text(html, encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--evidence-directory", type=Path)
    parser.add_argument("--runtime-directory", type=Path)
    options = parser.parse_args()
    print(render(options.directory.resolve(), options.evidence_directory, options.runtime_directory))
