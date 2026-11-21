"""单页面前端：发起研究 -> 待算/计算中 -> 显示切点次数。"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>茶样含水率换档点分析</title>
<style>
  :root { --ink:#2b2620; --tea:#7a5c3e; --tea2:#a5875a; --bg:#f6f2ea; --card:#fffdf8;
          --line:#e2d9c8; --ok:#2e7d4f; --warn:#b3541e; --bad:#b03030; --mut:#8a8175; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.6 "Noto Serif SC","Songti SC",serif; color:var(--ink);
         background:var(--bg); }
  header { background:linear-gradient(135deg,#6b4f35,#8d6b45); color:#f8f3e8;
           padding:14px 22px; }
  header h1 { margin:0; font-size:19px; letter-spacing:2px; }
  header .sub { font-size:12px; opacity:.85; margin-top:2px; }
  main { display:flex; gap:16px; padding:16px 22px; align-items:flex-start; }
  .col-l { width:300px; flex:none; }
  .col-r { flex:1; min-width:0; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:14px 16px; margin-bottom:16px; box-shadow:0 1px 3px rgba(90,70,40,.06); }
  .card h2 { margin:0 0 10px; font-size:15px; color:var(--tea); border-bottom:1px solid var(--line);
             padding-bottom:6px; }
  label { display:block; font-size:12px; color:var(--mut); margin:8px 0 2px; }
  input[type=text], textarea, select { width:100%; padding:6px 8px; border:1px solid var(--line);
          border-radius:5px; font:13px "IBM Plex Mono",monospace; background:#fff; color:var(--ink); }
  textarea { min-height:90px; resize:vertical; }
  button { cursor:pointer; border:1px solid var(--tea2); background:#f3ead9; color:var(--ink);
           border-radius:5px; padding:5px 12px; font:13px "Noto Serif SC",serif; }
  button:hover { background:#e9dcc3; }
  button.primary { background:var(--tea); border-color:var(--tea); color:#fff; }
  button.primary:hover { background:#63492f; }
  button.small { padding:1px 7px; font-size:12px; }
  .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .study-item { padding:7px 9px; border:1px solid var(--line); border-radius:6px;
                margin-bottom:6px; cursor:pointer; background:#fff; }
  .study-item:hover { border-color:var(--tea2); }
  .study-item.sel { border-color:var(--tea); background:#f7efe0; }
  .study-item .nm { font-weight:600; }
  .study-item .meta { font-size:12px; color:var(--mut); }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th, td { border:1px solid var(--line); padding:4px 7px; text-align:left; }
  th { background:#f1e9d8; font-weight:600; }
  td.num, th.num { text-align:right; font-family:"IBM Plex Mono",monospace; }
  .badge { display:inline-block; padding:1px 9px; border-radius:10px; font-size:12px; }
  .b-queued { background:#eee6d4; color:#7a6535; }
  .b-running { background:#dbe7f5; color:#2c5d8f; }
  .b-completed { background:#d9ecd9; color:var(--ok); }
  .b-failed { background:#f3d9d9; color:var(--bad); }
  .bar-wrap { display:flex; align-items:flex-end; gap:2px; height:120px; padding:6px 4px 0;
              border-bottom:1px solid var(--line); overflow-x:auto; }
  .bar-col { display:flex; flex-direction:column; align-items:center; min-width:26px; }
  .bar { width:18px; background:var(--tea2); border-radius:2px 2px 0 0; }
  .bar.zero { background:#e4dcc9; }
  .bar-lab { font-size:10px; color:var(--mut); font-family:"IBM Plex Mono",monospace; }
  .bar-cnt { font-size:10px; font-family:"IBM Plex Mono",monospace; }
  .mono { font-family:"IBM Plex Mono",monospace; }
  .mut { color:var(--mut); font-size:12px; }
  .err { color:var(--bad); font-size:13px; white-space:pre-wrap; }
  .big { font-size:22px; font-weight:700; color:var(--tea); font-family:"IBM Plex Mono",monospace; }
  .kv { display:grid; grid-template-columns:150px 1fr; row-gap:3px; font-size:13px; }
  .kv b { color:var(--mut); font-weight:500; }
  .pill { background:#efe6d2; border-radius:4px; padding:0 6px; font-size:12px; }
  .ok { color:var(--ok); } .warn { color:var(--warn); }
  #toast { position:fixed; right:18px; bottom:18px; background:#3a3128; color:#f5eedd;
           padding:9px 16px; border-radius:6px; opacity:0; transition:opacity .25s; z-index:9; }
</style>
</head>
<body>
<header>
  <h1>茶样含水率换档点分析</h1>
  <div class="sub">按送检顺序切段 · 每段≥3批 · 经验分位曲线逐点中位数为段代表 · 绝对差面积 + 每刀罚分 · 精确比较 · 并列最优计数不枚举</div>
</header>
<main>
  <div class="col-l">
    <div class="card">
      <h2>新建研究</h2>
      <label>研究名称</label>
      <input type="text" id="new-name" placeholder="如：秋制一号含水率换档">
      <label>每刀罚分（与含水率同单位）</label>
      <input type="text" id="new-penalty" value="0.5">
      <label>批次读数 JSON（按送检顺序，每批一个数组）</label>
      <textarea id="new-batches" placeholder='[[8.01,8.12,8.05],[8.22,8.19],[11.3,11.5,11.4]]'></textarea>
      <div class="row" style="margin-top:8px">
        <button class="primary" onclick="createStudy()">创建研究</button>
        <button class="small" onclick="fillDemo(12,4)">小例12批</button>
        <button class="small" onclick="fillDemo(80,40)">大例80批×40份</button>
      </div>
      <div class="err" id="new-err"></div>
    </div>
    <div class="card">
      <h2>研究列表</h2>
      <div id="study-list" class="mut">加载中…</div>
    </div>
  </div>
  <div class="col-r" id="detail"><div class="card mut">请选择或创建一个研究。</div></div>
</main>
<div id="toast"></div>
<script>
let cur = null;          // 当前研究详情
let pollTimer = null;

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const STATUS = {queued:'待算', running:'计算中', completed:'完成', failed:'失败'};

function toast(msg){ const t=$('toast'); t.textContent=msg; t.style.opacity=1;
  setTimeout(()=>t.style.opacity=0, 2200); }

async function api(path, method, body){
  const opt = {method: method||'GET', headers:{}};
  if (body !== undefined){ opt.headers['Content-Type']='application/json'; opt.body=JSON.stringify(body); }
  const r = await fetch(path, opt);
  const data = await r.json().catch(()=>({}));
  if (!r.ok) throw new Error(data.error || ('HTTP '+r.status));
  return data;
}

// ---------------- 列表与创建 ----------------
async function refreshStudies(){
  try{
    const d = await api('/api/studies');
    const el = $('study-list');
    if (!d.studies.length){ el.innerHTML='<span class="mut">暂无研究</span>'; return; }
    el.innerHTML = d.studies.map(s=>
      `<div class="study-item ${cur&&cur.id===s.id?'sel':''}" onclick="selectStudy(${s.id})">
        <div class="nm">${esc(s.name)}</div>
        <div class="meta">${s.n_batches} 批 · 罚分 ${esc(s.penalty)} · ${s.runs.length} 次运行</div>
      </div>`).join('');
  }catch(e){ $('study-list').innerHTML='<span class="err">'+esc(e.message)+'</span>'; }
}

function demoBatches(n, m){
  // 四个含水率档位，段内平稳、段间跳变
  const levels=[8.0, 11.2, 9.3, 13.1];
  const out=[]; let seed=20261121;
  const rnd=()=>{ seed=(seed*1103515245+12345)%2147483648; return seed/2147483648; };
  for(let i=0;i<n;i++){
    const lv=levels[Math.floor(i/(n/4))%levels.length];
    const b=[];
    for(let j=0;j<m;j++) b.push(+(lv+(rnd()-0.5)*0.6).toFixed(2));
    out.push(b);
  }
  return out;
}
function fillDemo(n,m){ $('new-batches').value=JSON.stringify(demoBatches(n,m));
  $('new-name').value=`示例研究 ${n}批`; toast('已填入示例数据'); }

async function createStudy(){
  $('new-err').textContent='';
  let batches;
  try{ batches=JSON.parse($('new-batches').value); }
  catch(e){ $('new-err').textContent='批次 JSON 无法解析'; return; }
  try{
    const s=await api('/api/studies','POST',
      {name:$('new-name').value, penalty:$('new-penalty').value||'0', batches});
    toast('研究已创建'); await refreshStudies(); selectStudy(s.id);
  }catch(e){ $('new-err').textContent=e.message; }
}

// ---------------- 研究详情 ----------------
async function selectStudy(id){
  cur = await api('/api/studies/'+id);
  renderDetail(); refreshStudies();
  schedulePoll();
}

function renderDetail(){
  const s=cur;
  const runs=[...s.runs].reverse();
  const lastDone=runs.find(r=>r.status==='completed');
  $('detail').innerHTML=`
  <div class="card">
    <h2>${esc(s.name)} <span class="mut">#${s.id}</span></h2>
    <div class="row">
      <span>每刀罚分 <input type="text" id="pen" value="${esc(s.penalty)}" style="width:90px;display:inline-block"></span>
      <button class="small" onclick="savePenalty()">保存罚分</button>
      <span class="pill">${s.n_batches} 批（送检顺序）</span>
      <button class="primary" onclick="startRun()">发起计算（冻结当前输入）</button>
    </div>
  </div>
  <div class="card">
    <h2>批次读数（可编辑 / 调序）</h2>
    <table><thead><tr><th class="num">序</th><th class="num">份数</th><th>含水率读数（逗号分隔）</th><th>操作</th></tr></thead>
    <tbody>${s.batches.map(b=>`
      <tr><td class="num">${b.index+1}</td><td class="num">${b.size}</td>
        <td><input type="text" id="rd-${b.index}" value="${b.readings.map(esc).join(', ')}"></td>
        <td style="white-space:nowrap">
          <button class="small" onclick="saveBatch(${b.index})">存</button>
          <button class="small" onclick="moveBatch(${b.index},${b.index-1})" ${b.index===0?'disabled':''}>↑</button>
          <button class="small" onclick="moveBatch(${b.index},${b.index+1})" ${b.index===s.batches.length-1?'disabled':''}>↓</button>
          <button class="small" onclick="delBatch(${b.index})">删</button></td></tr>`).join('')}
    </tbody></table>
    <div class="row" style="margin-top:8px">
      <input type="text" id="add-rd" placeholder="新批次读数，如 8.1, 8.2, 8.0" style="flex:1">
      <button class="small" onclick="addBatch()">添加批次</button>
    </div>
  </div>
  <div class="card">
    <h2>运行记录</h2>
    ${runs.length? `<table><thead><tr><th class="num">#</th><th>状态</th><th class="num">并列最优切法</th>
      <th class="num">总代价</th><th class="num">耗时(s)</th><th>输入SHA256</th><th>操作</th></tr></thead>
    <tbody>${runs.map(r=>`
      <tr><td class="num">${r.id}</td>
        <td><span class="badge b-${r.status}">${STATUS[r.status]||r.status}</span>
            ${r.rerun_of?`<span class="pill">重跑#${r.rerun_of}</span>`:''}
            ${r.consistent===true?'<span class="ok">✓切点计数一致</span>':''}
            ${r.consistent===false?'<span class="warn">✗不一致!</span>':''}</td>
        <td class="num">${r.result_summary?esc(r.result_summary.num_optimal):'—'}</td>
        <td class="num">${r.result_summary?esc(r.result_summary.total_cost):'—'}</td>
        <td class="num">${r.result_summary?r.result_summary.duration_sec:'—'}</td>
        <td class="mono" title="${r.input_sha256}">${r.input_sha256.slice(0,12)}</td>
        <td>${r.status==='completed'
              ?`<button class="small" onclick="showResult(${r.id})">结果</button>
                 <button class="small" onclick="rerun(${r.id})">冻结重跑</button>`
              :(r.error?`<span class="err">${esc(r.error)}</span>`:'')}</td></tr>`).join('')}
    </tbody></table>`:'<span class="mut">尚未运行。点击“发起计算”冻结当前输入并排队。</span>'}
  </div>
  <div class="card" id="result-card" style="display:${lastDone?'block':'none'}">
    <h2>切点次数</h2>
    <div id="result-body"></div>
  </div>`;
  if (lastDone) showResult(lastDone.id);
}

function parseReadings(text){
  const arr=text.split(/[,\s]+/).filter(x=>x.length).map(Number);
  if(!arr.length||arr.some(x=>!isFinite(x))) throw new Error('读数须为有限数值，逗号或空格分隔');
  return arr;
}
async function guard(fn){ try{ await fn(); cur=await api('/api/studies/'+cur.id);
  renderDetail(); refreshStudies(); }catch(e){ toast(e.message); } }

function savePenalty(){ guard(()=>api('/api/studies/'+cur.id,'PUT',{penalty:$('pen').value})); }
function saveBatch(i){ guard(()=>api(`/api/studies/${cur.id}/batches/${i}`,'PUT',
  {readings:parseReadings($('rd-'+i).value)})); }
function delBatch(i){ guard(()=>api(`/api/studies/${cur.id}/batches/${i}`,'DELETE')); }
function moveBatch(i,j){ guard(()=>api('/api/studies/'+cur.id+'/move',{from:i,to:j})); }
function addBatch(){ guard(()=>api('/api/studies/'+cur.id+'/batches','POST',
  {readings:parseReadings($('add-rd').value)})); }
function startRun(){ guard(async()=>{ await api('/api/studies/'+cur.id+'/runs','POST',{});
  toast('已冻结输入并排队'); }); }
function rerun(rid){ guard(async()=>{ await api(`/api/studies/${cur.id}/runs/${rid}/rerun`,'POST',{});
  toast('已用冻结输入重跑'); }); }

async function showResult(rid){
  const r=await api(`/api/studies/${cur.id}/runs/${rid}`);
  if(!r.result) return;
  const res=r.result;
  const counts=res.cut_counts.map(c=>({pos:c.position, cnt:Number(c.count)}));
  const max=Math.max(1,...counts.map(c=>c.cnt));
  $('result-card').style.display='block';
  $('result-body').innerHTML=`
    <div class="kv">
      <b>并列最优切法总数</b><span class="big">${esc(res.num_optimal)}</span>
      <b>最小总代价</b><span class="mono">${esc(res.total_cost)}</span>
      <b>精确分数</b><span class="mono mut">${esc(res.total_cost_fraction)}</span>
      <b>每刀罚分 / 每段至少</b><span>${esc(res.penalty)} / ${res.min_segment} 批</span>
      <b>引擎 / 耗时</b><span>${esc(res.engine)} · ${res.duration_sec}s · SHA256 ${r.input_sha256.slice(0,16)}…</span>
    </div>
    <div class="bar-wrap">${counts.map(c=>`
      <div class="bar-col" title="第 ${c.pos} 批后下刀：${c.cnt} 次">
        <span class="bar-cnt">${c.cnt||''}</span>
        <div class="bar ${c.cnt?'':'zero'}" style="height:${Math.round(c.cnt/max*88)}px"></div>
        <span class="bar-lab">${c.pos}</span></div>`).join('')}</div>
    <table style="margin-top:10px"><thead><tr><th class="num">切点（第几批后）</th>
      <th class="num">出现次数</th><th class="num">占全部最优切法</th></tr></thead>
    <tbody>${counts.filter(c=>c.cnt>0).map(c=>`
      <tr><td class="num">${c.pos}</td><td class="num">${c.cnt}</td>
      <td class="num">${(c.cnt/Number(res.num_optimal)*100).toFixed(1)}%</td></tr>`).join('')||'<tr><td colspan=3>无切点（整段为唯一最优）</td></tr>'}
    </tbody></table>`;
}

// ---------------- 轮询：待算 -> 计算中 -> 完成 ----------------
function schedulePoll(){
  if (pollTimer) clearInterval(pollTimer);
  pollTimer=setInterval(async()=>{
    if(!cur) return;
    const active=cur.runs.some(r=>r.status==='queued'||r.status==='running');
    if(!active) return;
    cur=await api('/api/studies/'+cur.id);
    renderDetail();
  }, 800);
}

refreshStudies();
</script>
</body>
</html>
"""
