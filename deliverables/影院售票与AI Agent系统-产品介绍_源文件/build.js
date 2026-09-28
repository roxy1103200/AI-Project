// 影院售票与 AI Agent 系统｜产品介绍
// 可编辑 PowerPoint：所有版式、文字与图形均由 PptxGenJS 原生对象构成。
const pptxgen = require('pptxgenjs');
const path = require('path');
const {autoFontSize, calcTextBox} = require('./pptxgenjs_helpers/text');
const {warnIfSlideHasOverlaps, warnIfSlideElementsOutOfBounds} = require('./pptxgenjs_helpers/layout');

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'OpenAI Codex';
pptx.subject = '影院售票与 AI Agent 系统产品介绍';
pptx.title = '影院售票与 AI Agent 系统｜产品介绍';
pptx.company = 'AI-Project';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Microsoft YaHei',
  bodyFontFace: 'Microsoft YaHei',
  lang: 'zh-CN',
};

const S = pptx.ShapeType;
const W = 13.333, H = 7.5;
const C = {
  ink:'091822', navy:'0E2430', navy2:'133340', pale:'F7F4ED', paper:'FFFEFA',
  cream:'E8E5DC', muted:'A4B1B4', mutedDark:'697B80', coral:'F47657',
  orange:'E9A45B', teal:'67C5B9', white:'FFFFFF', line:'DDE4E0',
  slate:'29414D', soft:'E9F1EE', softCoral:'FDEAE3', green:'4A9C8E',
};
const FONT = 'Microsoft YaHei';
const AFONT = 'Aptos';

function addShape(sl, type, x,y,w,h, fill, radius=0, lineColor=null, lineW=0) {
  sl.addShape(type, {x,y,w,h,rectRadius:radius,
    fill:{color:fill},
    line:lineColor?{color:lineColor,width:lineW}:{color:fill,transparency:100}});
}
function rect(sl,x,y,w,h,fill, radius=0, lineColor=null, lineW=0){
  addShape(sl,radius?S.roundRect:S.rect,x,y,w,h,fill,radius,lineColor,lineW);
}
function circ(sl,x,y,d,fill,lineColor=null,lineW=0){ addShape(sl,S.ellipse,x,y,d,d,fill,0,lineColor,lineW); }
function line(sl,x1,y1,x2,y2,color,width=1,dash){
  sl.addShape(S.line,{x:x1,y:y1,w:x2-x1,h:y2-y1,line:{color,width,dashType:dash}});
}
function text(sl,t,x,y,w,h,size,color=C.ink,bold=false,opts={}) {
  // calcTextBox provides a measured fallback height for labels that omit h.
  const boxH = h ?? calcTextBox(size,{text:t,w,fontFace:opts.fontFace||FONT,margin:0}).h;
  const fit = autoFontSize(t,opts.fontFace||FONT,{x,y,w,h:boxH,fontSize:size,
    minFontSize:Math.max(8,size-2),maxFontSize:size,mode:'auto'});
  sl.addText(t,{x,y,w,h:boxH,fontFace:opts.fontFace||FONT,fontSize:fit.fontSize,
    color,bold,margin:0,breakLine:false,align:opts.align||'left',
    valign:opts.valign||'mid',charSpacing:opts.charSpacing||0,
    lineSpacingMultiple:1.04,transparency:opts.transparency||0,
    rotate:opts.rotate||0});
}
function kicker(sl,label,dark=false,x=0.7,y=0.62){
  const color=dark?C.teal:C.green;
  rect(sl,x,y,0.10,0.11,color);
  text(sl,label.toUpperCase(),x+0.21,y-0.045,4.7,0.22,10,dark?C.teal:C.green,true,{fontFace:AFONT,charSpacing:1.7});
}
function title(sl,t,sub,dark=false){
  kicker(sl,sub,dark);
  text(sl,t,0.7,0.94,11.8,0.66,28,dark?C.white:C.ink,true);
}
function footer(sl,n,dark=false){
  const col=dark?'789098':'8B999B';
  line(sl,0.7,7.10,12.62,7.10,dark?'27434B':'DDE4E0',0.55);
  text(sl,'CINEMA  /  PRODUCT INTRODUCTION',0.7,7.14,5.5,0.16,8.3,col,false,{fontFace:AFONT,charSpacing:1});
  text(sl,String(n).padStart(2,'0'),12.18,7.12,0.43,0.2,8.5,col,true,{fontFace:AFONT,align:'right'});
}
function base(dark=false){
  const sl=pptx.addSlide(); sl.background={color:dark?C.ink:C.pale}; return sl;
}
function pill(sl,t,x,y,w,fill,color,size=10){
  rect(sl,x,y,w,0.34,fill,0.16);
  text(sl,t,x+0.08,y+0.035,w-0.16,0.26,size,color,true,{align:'center'});
}
function bullet(sl,t,x,y,w,size=13,color=C.ink,dot=C.coral){
  circ(sl,x,y+0.155,0.075,dot);
  text(sl,t,x+0.20,y,w-0.20,0.44,size,color,false);
}
function num(sl,n,x,y,d=0.43,fill=C.coral,color=C.white){
  circ(sl,x,y,d,fill);
  text(sl,String(n).padStart(2,'0'),x,y+0.03,d,d-0.06,10,color,true,{fontFace:AFONT,align:'center'});
}
function bracket(sl,x,y,w,h,color=C.teal){
  line(sl,x,y,x+0.23,y,color,2); line(sl,x,y,x,y+0.23,color,2);
  line(sl,x+w-0.23,y+h,x+w,y+h,color,2); line(sl,x+w,y+h-0.23,x+w,y+h,color,2);
}

// 01 封面。票券、座位和放映光束是有意叠放的编辑图形。
{
  const sl=base(true);
  rect(sl,8.23,0,5.10,H,C.navy);
  line(sl,8.23,0,8.23,H,'214653',1);
  for(let i=0;i<8;i++) circ(sl,8.50+i*0.52,0.30,0.17,'1C3946');
  for(let i=0;i<8;i++) circ(sl,8.50+i*0.52,6.77,0.17,'1C3946');
  rect(sl,0.70,0.63,0.10,0.13,C.coral);
  text(sl,'C I N E M A   /   智 能 影 院',0.91,0.56,5.4,0.33,11,C.teal,true,{fontFace:AFONT,charSpacing:1.2});
  text(sl,'从选片到入场，\n让每一步都恰到好处。',0.70,1.58,7.0,1.60,31,C.white,true,{valign:'top'});
  text(sl,'影院售票与 AI Agent 系统',0.72,3.58,6.62,0.50,20,C.cream,true);
  line(sl,0.72,4.40,6.77,4.40,C.coral,2.3);
  text(sl,'观众购票  ·  影院运营  ·  智能服务',0.72,4.70,6.85,0.39,14,C.muted,false);
  text(sl,'当前代码实现版  /  2026.09',0.72,6.75,5.4,0.28,10,C.muted,false,{fontFace:AFONT});
  // Ticket panel and seat-map motif.
  rect(sl,9.02,1.62,3.56,4.33,C.paper,0.18);
  rect(sl,9.02,1.62,3.56,0.74,C.coral,0.18);
  text(sl,'ADMIT ONE',9.28,1.83,2.56,0.22,13,C.white,true,{fontFace:AFONT,charSpacing:1.5});
  text(sl,'今夜好戏 · 从这里开始',9.28,2.60,2.87,0.40,15,C.ink,true);
  text(sl,'SCREEN 01',9.29,3.16,1.61,0.23,10,C.mutedDark,true,{fontFace:AFONT,charSpacing:1});
  rect(sl,9.38,3.58,2.75,0.10,C.slate,0.06);
  for(let r=0;r<3;r++) for(let c=0;c<6;c++) {
    const selected=(r===1&&c>=2&&c<=3);
    rect(sl,9.46+c*0.43,3.92+r*0.38,0.26,0.23,selected?C.coral:C.soft,0.06);
  }
  line(sl,9.02,5.35,12.58,5.35,C.line,1,'dash');
  text(sl,'ROW C   /   SEAT 05 06',9.29,5.53,2.90,0.18,10,C.slate,true,{fontFace:AFONT});
  footer(sl,1,true);
}

// 02 产品定位。
{
  const sl=base(); title(sl,'一个系统，连接一场电影的完整旅程','PRODUCT VISION');
  text(sl,'把分散的选片、购票、运营与咨询，\n收拢成一条清晰的服务链。',0.72,2.02,5.35,1.18,25,C.ink,true,{valign:'top'});
  text(sl,'围绕影院真实业务建立体验闭环：观众看得见排期、买得到座位；管理者排得稳场次、管得住现场；常见问题与实时数据各走适合的服务路径。',0.74,3.55,5.15,1.50,15,C.mutedDark,false,{valign:'top'});
  const cards=[
    ['01','观众','发现电影、选座购票、查看电子票','DCEBE6',C.green],
    ['02','影院','管理场次、影厅座位与入场服务','FDE9DD',C.coral],
    ['03','服务','Dify 常见问答 + 实时 Agent 查询','E5EDEB',C.slate],
  ];
  cards.forEach((a,i)=>{
    const y=1.93+i*1.48;
    rect(sl,6.74,y,5.88,1.20,C.paper,0.12);
    rect(sl,6.74,y,0.11,1.20,a[4]);
    text(sl,a[0],7.10,y+0.22,0.60,0.29,13,a[4],true,{fontFace:AFONT});
    text(sl,a[1],7.88,y+0.15,1.30,0.37,18,C.ink,true);
    text(sl,a[2],7.88,y+0.62,4.15,0.32,12.5,C.mutedDark);
  });
  footer(sl,2);
}

// 03 功能地图。
{
  const sl=base(true); title(sl,'三条链路，构成可运行的产品闭环','WHAT IS BUILT',true);
  const cols=[
    {n:'01',head:'观众端',sub:'从浏览到观影',accent:C.coral,items:['影片、影院与两周排期','选座锁座、订单与出票','退票资格、电子票与验票','购票后影评与互动']},
    {n:'02',head:'管理端',sub:'从排期到现场',accent:C.teal,items:['影片资料与售票周期','影院、影厅及座位管理','退票规则、验票入场','影评审核、举报与 AI 反馈']},
    {n:'03',head:'影院助手',sub:'问答与实时查询',accent:C.orange,items:['Dify 承接常见问题','手动转接内部实时 Agent','查询影片、场次、本人订单','会话恢复与回答反馈']},
  ];
  cols.forEach((c,i)=>{
    const x=0.70+i*4.21;
    rect(sl,x,1.92,3.84,4.62,C.navy,0.13,'2C4E57',0.6);
    rect(sl,x,1.92,3.84,0.10,c.accent);
    text(sl,c.n,x+0.27,2.23,0.64,0.33,15,c.accent,true,{fontFace:AFONT});
    text(sl,c.head,x+0.27,2.66,3.12,0.48,24,C.white,true);
    text(sl,c.sub,x+0.27,3.22,3.12,0.31,12,C.muted);
    line(sl,x+0.27,3.74,x+3.53,3.74,'35545D',0.65);
    c.items.forEach((it,j)=>bullet(sl,it,x+0.29,4.02+j*0.51,3.15,12,C.cream,c.accent));
  });
  footer(sl,3,true);
}

// 04 购票旅程。
{
  const sl=base(); title(sl,'观众旅程：每一步都有明确状态','CUSTOMER JOURNEY');
  const steps=[
    ['01','发现','影片 / 影院 / 评分'],['02','排期','可售场次 / 两周视图'],
    ['03','选座','座位图 / 短期锁定'],['04','下单','5 分钟待支付'],
    ['05','出票','模拟支付 / 电子票'],['06','观影','验票 / 影评互动']
  ];
  line(sl,1.29,3.15,12.00,3.15,C.line,2);
  steps.forEach((a,i)=>{
    const x=0.70+i*2.10;
    circ(sl,x+0.45,2.82,0.66,i===2?C.coral:C.navy);
    text(sl,a[0],x+0.45,2.98,0.66,0.18,10,C.white,true,{fontFace:AFONT,align:'center'});
    text(sl,a[1],x,3.75,1.57,0.46,19,C.ink,true,{align:'center'});
    text(sl,a[2],x-0.10,4.33,1.80,0.50,11.5,C.mutedDark,false,{align:'center'});
  });
  rect(sl,0.70,5.62,11.93,0.70,C.paper,0.12);
  pill(sl,'最多 6 座 / 单',0.96,5.80,2.02,C.softCoral,C.coral,11);
  pill(sl,'锁座 5 分钟',3.32,5.80,2.02,C.soft,C.green,11);
  pill(sl,'超时自动取消',5.68,5.80,2.08,'E8EFF1',C.slate,11);
  pill(sl,'按规则退票',8.10,5.80,2.02,'F7EDE0','A46C37',11);
  footer(sl,4);
}

// 05 订单可靠性。
{
  const sl=base(true); title(sl,'座位是一份实时承诺','ORDER RELIABILITY',true);
  text(sl,'速度交给 Redis，最终事实交给 MySQL。',0.70,1.77,7.5,0.42,18,C.cream,true);
  const nodes=[
    {x:0.80,w:2.66,lab:'01  原子锁座',body:'Redis Lua 一次检查并锁定所有座位',acc:C.coral},
    {x:4.02,w:2.66,lab:'02  创建订单',body:'requestId 幂等；数据库事务保护状态',acc:C.teal},
    {x:7.24,w:2.66,lab:'03  模拟支付',body:'支付流水号幂等；成功后立即出票',acc:C.orange},
  ];
  nodes.forEach(n=>{
    rect(sl,n.x,2.63,n.w,1.75,C.navy,0.13,'31515B',0.7);
    rect(sl,n.x,2.63,n.w,0.09,n.acc);
    text(sl,n.lab,n.x+0.20,2.92,n.w-0.40,0.38,16,C.white,true);
    text(sl,n.body,n.x+0.20,3.47,n.w-0.40,0.64,12,C.muted,false,{valign:'top'});
  });
  for(const x of [3.53,6.75]){line(sl,x,3.50,x+0.35,3.50,C.teal,2);line(sl,x+0.22,3.40,x+0.35,3.50,C.teal,2);line(sl,x+0.22,3.60,x+0.35,3.50,C.teal,2);}
  rect(sl,10.30,2.63,2.22,1.75,C.coral,0.13);
  text(sl,'04  电子票',10.48,2.92,1.86,0.38,16,C.white,true);
  text(sl,'订单与票项进入已出票状态',10.48,3.48,1.86,0.62,12,C.white,false,{valign:'top'});
  line(sl,0.83,5.06,12.54,5.06,'31515B',0.7);
  rect(sl,0.83,5.40,5.60,0.87,C.navy,0.11);
  text(sl,'未支付超时',1.08,5.57,1.40,0.30,14,C.orange,true);
  text(sl,'RabbitMQ 延迟取消 + 定时对账补偿',2.56,5.56,3.54,0.34,12.5,C.cream);
  rect(sl,6.76,5.40,5.76,0.87,C.navy,0.11);
  text(sl,'退款校验',7.01,5.57,1.30,0.30,14,C.teal,true);
  text(sl,'读取当前规则，验票后整单不可退',8.37,5.56,3.82,0.34,12.5,C.cream);
  footer(sl,5,true);
}

// 06 运营端。
{
  const sl=base(); title(sl,'后台运营：内容、场次、现场协同','OPERATIONS');
  // Conceptual admin dashboard: an editable product illustration, not a screenshot.
  rect(sl,0.71,1.90,6.55,4.75,C.paper,0.16,'DDE4E0',0.6);
  rect(sl,0.71,1.90,1.30,4.75,C.navy,0.16);
  text(sl,'CINEMA',0.86,2.12,1.06,0.25,11,C.teal,true,{fontFace:AFONT,charSpacing:0.9});
  ['概览','影片','排期','影厅','影评','验票'].forEach((t,i)=>{
    if(i===2) rect(sl,0.80,2.70+i*0.48,1.06,0.33,C.coral,0.07);
    text(sl,t,0.91,2.75+i*0.48,0.82,0.22,10.4,i===2?C.white:C.muted,false);
  });
  text(sl,'今日运营概览',2.31,2.17,3.22,0.36,17,C.ink,true);
  text(sl,'影片 · 场次 · 现场服务',2.32,2.59,3.40,0.24,10.5,C.mutedDark);
  const dash=[['影片管理','正在上映'],['场次排期','时段校验'],['影厅座位','可视布局']];
  dash.forEach((a,i)=>{
    const x=2.30+i*1.51;
    rect(sl,x,3.17,1.28,0.95,i===1?C.softCoral:C.soft,0.10);
    text(sl,a[0],x+0.12,3.35,1.04,0.27,11.2,C.ink,true);
    text(sl,a[1],x+0.12,3.71,1.04,0.18,8.5,C.mutedDark);
  });
  text(sl,'场次日历',2.30,4.47,1.70,0.27,12.5,C.ink,true);
  for(let i=0;i<5;i++){
    rect(sl,2.30+i*0.82,4.90,0.65,0.48,i===1||i===3?C.coral:'DDECE7',0.06);
    text(sl,['周一','周二','周三','周四','周五'][i],2.30+i*0.82,5.04,0.65,0.18,8.5,i===1||i===3?C.white:C.mutedDark,true,{align:'center'});
  }
  line(sl,2.30,5.72,6.76,5.72,C.line,0.75);
  text(sl,'排期冲突 / 营业时间 / 片长 + 周转',2.30,5.92,4.46,0.30,10.3,C.mutedDark);
  const items=[
    ['01','影片与排期','售票窗口、影厅时段、20 分钟周转校验'],
    ['02','空间与座位','影厅布局、座位状态及历史订单约束'],
    ['03','票务与现场','退票规则、订单查询、逐票验票入场'],
    ['04','内容与反馈','影评/回复审核、举报、AI 回答评价'],
  ];
  items.forEach((a,i)=>{
    const y=1.92+i*1.13;
    num(sl,a[0],7.75,y+0.06,0.40,i===0?C.coral:C.navy);
    text(sl,a[1],8.37,y,3.40,0.38,16,C.ink,true);
    text(sl,a[2],8.37,y+0.44,3.70,0.42,11.5,C.mutedDark);
    if(i<3) line(sl,8.36,y+0.96,12.40,y+0.96,C.line,0.7);
  });
  footer(sl,6);
}

// 07 影评与验票。
{
  const sl=base(); title(sl,'观影之后，评价才成为可信内容','COMMUNITY & TRUST');
  rect(sl,0.71,1.93,5.49,4.68,C.navy,0.16);
  text(sl,'从有效电影票开始',1.08,2.30,4.55,0.47,21,C.white,true);
  text(sl,'已出票  →  已放映 / 已验票  →  可发表影评',1.10,3.04,4.31,0.80,13,C.cream,false,{valign:'top'});
  rect(sl,1.09,4.20,4.73,1.70,C.paper,0.11);
  text(sl,'「这一场，值得五星。」',1.39,4.52,4.10,0.40,16,C.ink,true);
  text(sl,'★★★★★',1.38,5.07,2.40,0.31,14,C.orange,true);
  pill(sl,'待审核',4.37,5.05,1.05,C.softCoral,C.coral,9.5);
  const details=[
    ['资格','有效已出票票项，放映结束或已验票'],
    ['发布','一人一片一评；1–5 星与文字'],
    ['公开','审核通过且仍具观影资格，才计入评分'],
    ['互动','回复、点赞、举报均有权限与审核规则'],
  ];
  details.forEach((a,i)=>{
    const y=2.03+i*1.06;
    circ(sl,6.75,y+0.10,0.31,i===2?C.coral:C.teal);
    text(sl,a[0],7.23,y,1.12,0.34,15,C.ink,true);
    text(sl,a[1],8.42,y,4.01,0.65,12,C.mutedDark,false,{valign:'top'});
    if(i<3) line(sl,7.23,y+0.87,12.50,y+0.87,C.line,0.7);
  });
  footer(sl,7);
}

// 08 AI 分流。
{
  const sl=base(true); title(sl,'影院助手：先解答，再按需查询实时数据','AI SERVICE',true);
  text(sl,'统一聊天入口，用户主动选择转接实时 Agent。',0.70,1.76,8.04,0.35,16,C.cream);
  const path1={x:0.73,y:2.42,w:5.64,h:3.64};
  const path2={x:6.94,y:2.42,w:5.64,h:3.64};
  rect(sl,path1.x,path1.y,path1.w,path1.h,C.navy,0.16,'36515A',0.7);
  rect(sl,path2.x,path2.y,path2.w,path2.h,C.navy,0.16,'36515A',0.7);
  pill(sl,'默认路径',1.07,2.73,1.31,'244C4D',C.teal,10);
  pill(sl,'用户主动转接',7.28,2.73,2.00,'5E3E3C',C.coral,10);
  text(sl,'常见问题 · Dify',1.07,3.28,4.34,0.49,22,C.white,true);
  text(sl,'前端 → 独立 AI 网关 → Dify',1.07,3.92,4.68,0.32,13,C.teal,true);
  line(sl,1.07,4.54,5.98,4.54,'3A555E',0.75);
  bullet(sl,'通用介绍、营业与规则类问答',1.10,4.79,4.70,12,C.cream,C.teal);
  bullet(sl,'流式回复不占用 Java 长连接',1.10,5.25,4.70,12,C.cream,C.teal);
  text(sl,'实时业务 · 内部 Agent',7.28,3.28,4.75,0.49,22,C.white,true);
  text(sl,'短期凭证 → Agent → Java 固定只读工具',7.28,3.92,4.89,0.32,12.7,C.coral,true);
  line(sl,7.28,4.54,12.19,4.54,'3A555E',0.75);
  bullet(sl,'查询影片、场次、本人订单与退票资格',7.31,4.79,4.89,12,C.cream,C.coral);
  bullet(sl,'身份与数据权限由 Java 校验',7.31,5.25,4.89,12,C.cream,C.coral);
  rect(sl,4.95,6.34,3.37,0.31,'27444E',0.14);
  text(sl,'Agent 不生成 SQL，也不执行交易',5.08,6.38,3.12,0.20,9.9,C.muted,true,{align:'center'});
  footer(sl,8,true);
}

// 09 技术架构。
{
  const sl=base(); title(sl,'架构清晰分层，让票务与 AI 各司其职','SYSTEM ARCHITECTURE');
  // All connectors and nodes are native editable shapes; their intersections are intentional.
  const arch=[
    {x:0.80,y:2.09,w:2.33,h:0.68,head:'浏览器 / React',sub:'观众端 · 管理端 · 聊天',fill:C.navy,fc:C.white},
    {x:3.84,y:2.09,w:2.04,h:0.68,head:'Nginx',sub:'统一入口',fill:C.slate,fc:C.white},
    {x:6.71,y:1.90,w:2.45,h:1.04,head:'Spring Boot',sub:'票务业务与权限',fill:C.coral,fc:C.white},
    {x:6.71,y:3.39,w:2.45,h:1.04,head:'FastAPI 网关',sub:'会话 · SSE · 分流',fill:C.teal,fc:C.ink},
    {x:10.06,y:2.02,w:2.42,h:0.73,head:'MySQL / Redis',sub:'业务事实 · 短期状态',fill:C.navy,fc:C.white},
    {x:10.06,y:2.97,w:2.42,h:0.73,head:'RabbitMQ',sub:'延迟取消与补偿',fill:C.navy,fc:C.white},
    {x:10.06,y:4.01,w:2.42,h:0.73,head:'Dify / Agent',sub:'问答 · 只读查询',fill:C.navy,fc:C.white},
  ];
  arch.forEach(a=>{
    rect(sl,a.x,a.y,a.w,a.h,a.fill,0.10);
    text(sl,a.head,a.x+0.16,a.y+0.11,a.w-0.32,0.28,13,a.fc,true);
    text(sl,a.sub,a.x+0.16,a.y+0.41,a.w-0.32,0.24,9.5,a.fc,false);
  });
  line(sl,3.13,2.43,3.84,2.43,C.green,1.8);
  line(sl,5.88,2.43,6.31,2.43,C.green,1.8);
  line(sl,6.31,2.43,6.31,3.90,C.green,1.8);
  line(sl,6.31,2.43,6.71,2.43,C.green,1.8);
  line(sl,6.31,3.90,6.71,3.90,C.green,1.8);
  line(sl,9.16,2.43,9.64,2.43,C.green,1.8);
  line(sl,9.64,2.43,9.64,3.32,C.green,1.8);
  line(sl,9.64,2.39,10.06,2.39,C.green,1.8);
  line(sl,9.64,3.33,10.06,3.33,C.green,1.8);
  line(sl,9.16,3.91,9.64,3.91,C.green,1.8);
  line(sl,9.64,3.91,9.64,4.38,C.green,1.8);
  line(sl,9.64,4.38,10.06,4.38,C.green,1.8);
  rect(sl,0.80,5.42,11.69,0.81,C.paper,0.11);
  text(sl,'技术栈',1.07,5.66,0.85,0.30,14,C.ink,true);
  text(sl,'React · TypeScript · Java 21 · Spring Boot · MyBatis · MySQL · Redis · RabbitMQ · FastAPI · LangGraph',2.02,5.63,10.06,0.39,11.3,C.mutedDark);
  footer(sl,9);
}

// 10 当前边界与方向。此页严格区分已实现、当前边界与可继续演进。
{
  const sl=base(); title(sl,'真实呈现当前能力，也明确下一步空间','IMPLEMENTATION STATUS');
  const groups=[
    {x:0.71,head:'当前已实现',accent:C.green,fill:C.soft,items:['完整购票、模拟支付与出票流程','影院 / 影厅 / 座位 / 排期管理','验票、影评审核与互动','Dify 问答 + 手动转接实时 Agent']},
    {x:4.91,head:'当前边界',accent:C.coral,fill:C.softCoral,items:['支付与退款未接真实资金渠道','已售场次取消及批量通知未形成闭环','当前 ADMIN 为全局权限','Agent 仅使用固定只读查询工具']},
    {x:9.11,head:'可继续演进',accent:'B27941',fill:'F8EBDC',items:['对接支付渠道与对账','补齐已售场次取消与退款流程','按影院划分运营权限','持续完善 Dify 工作流与知识内容']},
  ];
  groups.forEach(g=>{
    rect(sl,g.x,1.91,3.50,4.66,C.paper,0.14,'E2E4DF',0.6);
    rect(sl,g.x,1.91,3.50,0.13,g.accent);
    circ(sl,g.x+0.28,2.23,0.40,g.fill);
    text(sl,g.head,g.x+0.79,2.18,2.34,0.48,18,C.ink,true);
    line(sl,g.x+0.28,2.91,g.x+3.19,2.91,C.line,0.8);
    g.items.forEach((it,j)=>bullet(sl,it,g.x+0.30,3.18+j*0.72,2.88,11.6,C.mutedDark,g.accent));
  });
  text(sl,'说明：内容以当前仓库代码与业务文档为准；“可继续演进”是方向，不代表已承诺排期。',0.75,6.75,11.95,0.22,9,C.mutedDark);
  footer(sl,10);
}

// 11 结束页。
{
  const sl=base(true);
  for(let i=0;i<9;i++){
    circ(sl,10.00+(i%3)*0.96,0.68+Math.floor(i/3)*1.04,0.64,i%3===0?'183A45':'12313C');
  }
  rect(sl,0.70,0.65,0.10,0.13,C.coral);
  text(sl,'C I N E M A   /   一 场 电 影 的 完 整 旅 程',0.91,0.58,6.92,0.35,11,C.teal,true,{fontFace:AFONT,charSpacing:1.0});
  text(sl,'让购票、运营与服务\n形成一个清晰的闭环。',0.72,1.90,8.90,1.72,32,C.white,true,{valign:'top'});
  line(sl,0.72,4.16,8.44,4.16,C.coral,2.2);
  const words=[['选得轻松','观众体验'],['管得有序','影院运营'],['答得及时','智能服务']];
  words.forEach((a,i)=>{
    const x=0.75+i*2.65;
    text(sl,a[0],x,4.62,2.22,0.42,18,C.white,true);
    text(sl,a[1],x,5.14,2.22,0.25,10.5,C.muted);
  });
  bracket(sl,9.33,4.57,2.56,1.09,C.teal);
  text(sl,'THANK YOU',9.61,4.87,2.04,0.39,19,C.white,true,{fontFace:AFONT,charSpacing:1.0,align:'center'});
  text(sl,'影院售票与 AI Agent 系统',0.73,6.75,6.80,0.25,11,C.muted);
  footer(sl,11,true);
}

// Intentionally layered shapes (backgrounds, cards, connector lines, ticket and dashboard motifs)
// are decorative. Content boxes have been manually reviewed after slide rasterization.
for(const sl of pptx._slides){
  warnIfSlideHasOverlaps(sl,pptx,{muteContainment:true,ignoreLines:true,ignoreDecorativeShapes:true});
  warnIfSlideElementsOutOfBounds(sl,pptx);
}

const out = path.join(__dirname,'影院售票与AI Agent系统-产品介绍.pptx');
pptx.writeFile({fileName:out});
