
const $=id=>document.getElementById(id);
window.onerror=function(m){try{toast("页面错误:"+m);}catch(_){}};
let user=localStorage.getItem("fg_user")||"beifeng";
function paintSeg(){$("u1").classList.toggle("on",user==="beifeng");$("u2").classList.toggle("on",user==="gagayouna");}
$("u1").textContent="🧑 邶风";$("u2").textContent="👩 gagayouna";
$("u1").onclick=()=>{user="beifeng";localStorage.setItem("fg_user",user);paintSeg();clearReply();$("list").removeAttribute("data-ready");monthDays={};monthFetched={};CAL_TARGET=0;refresh();if($("mback").style.display==="flex")loadProfile();};
$("u2").onclick=()=>{user="gagayouna";localStorage.setItem("fg_user",user);paintSeg();clearReply();$("list").removeAttribute("data-ready");monthDays={};monthFetched={};CAL_TARGET=0;refresh();if($("mback").style.display==="flex")loadProfile();};
function clearReply(){const el=$("reply");el.className="";el.textContent="";
 if(timer)clearInterval(timer);timer=null;suppress=true;busy=false;
 $("bPhoto").disabled=false;$("bSend").disabled=false;}
function showBack(id){const el=$(id);el.style.display="flex";el.classList.remove("closing");}
function hideBack(id){const el=$(id);el.classList.add("closing");
 setTimeout(()=>{el.style.display="none";el.classList.remove("closing");},260);}
// iOS手势关闭：dir=1 底部抽屉下拉关闭；dir=-1 顶部sheet上推关闭（对齐iOS下拉面板惯例）。
// 拖拽>90px 松手关闭，否则回弹；dir=-1 时内容滚到顶才响应，避免与内部滚动冲突
function enableDragClose(sheet,back,onClose,dir){
 let sy=0,d=0,drag=false;
 sheet.addEventListener("touchstart",e=>{
  if(back.style.display!=="flex"||back.classList.contains("closing"))return;
  sy=e.touches[0].clientY;d=0;drag=true;sheet.style.transition="none";},{passive:true});
 sheet.addEventListener("touchmove",e=>{
  if(!drag)return;
  if(dir<0&&sheet.scrollTop>2)return; // 内部还在滚动 → 不触发手势
  d=(e.touches[0].clientY-sy)*dir;
  if(d>0)sheet.style.transform="translateY("+(d*dir)+"px)";},{passive:true});
 sheet.addEventListener("touchend",()=>{
  if(!drag)return;drag=false;sheet.style.transition="";
  if(d>90){sheet.style.transform="";onClose();}
  else sheet.style.transform="";},{passive:true});
}
enableDragClose($("editBack").querySelector(".sheet"),$("editBack"),closeEdit,1);
enableDragClose($("calBack").querySelector(".sheet"),$("calBack"),closeCal,-1);
function applyTheme(t){document.querySelectorAll("[data-theme]").forEach(v=>v.setAttribute("data-theme",t));
 $("themeBtn").textContent=t==="meal"?"🌿":"🧊";localStorage.setItem("fg_theme",t);}
$("themeBtn").onclick=()=>applyTheme(localStorage.getItem("fg_theme")==="meal"?"home":"meal");
applyTheme(localStorage.getItem("fg_theme")||"home");
function openSettings(){showBack("mback");loadProfile();
 api("/api/mockcfg").then(j=>{$("mockChk").checked=!!j.mock;}).catch(()=>{});}
$("mockChk").onchange=async e=>{const on=e.target.checked;
 try{const j=await api("/api/mockcfg",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({mock:on})},15000);
  toast(j.mock?"测试模式开：识别返回示例数据":"测试模式关：恢复真实识别");}
 catch(err){toast("切换失败："+err.message);e.target.checked=!on;}};
function closeSettings(){hideBack("mback");}
$("gear").onclick=openSettings;
$("mclose").onclick=closeSettings;
$("mback").onclick=e=>{if(e.target.id==="mback")closeSettings();};
$("tProfile").onclick=()=>{$("tProfile").classList.add("on");$("tGeneral").classList.remove("on");
 $("pProfile").classList.add("on");$("pGeneral").classList.remove("on");};
$("tGeneral").onclick=()=>{$("tGeneral").classList.add("on");$("tProfile").classList.remove("on");
 $("pGeneral").classList.add("on");$("pProfile").classList.remove("on");};
function showPTab(tabId,panelId){["tProfile","tGeneral","tPlan"].forEach(t=>$(t).classList.toggle("on",t===tabId));
 ["pProfile","pGeneral","pPlan"].forEach(p=>$(p).classList.toggle("on",p===panelId));}
$("tPlan").onclick=()=>{showPTab("tPlan","pPlan");loadPlanView();};
let curPlan={days:[]};
async function loadPlanView(){
 try{const p=await api("/api/plan?user="+user);
  curPlan=p&&p.days?p:{days:[]};
  $("pPrev").textContent=curPlan.days.length?
   "当前计划（保存新的会覆盖）：\n"+curPlan.days.map(d=>d.dow+"："+d.parts.map(x=>x.name+(x.sets_reps?" "+x.sets_reps:"")).join("、")).join("\n")
   :"还没有训练计划";
 }catch(e){$("pPrev").textContent="读取失败："+e.message;}
}
$("pParse").onclick=async()=>{
 const t=$("pText").value.trim();if(!t){toast("先粘贴计划文本");return;}
 $("pParse").disabled=true;$("pPrev").textContent="解析中…";
 try{const j=await api("/api/plan/parse",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user,text:t})},120000);
  if(j.days&&j.days.length){$("pPrev").textContent="解析结果预览：\n"+j.days.map(d=>d.dow+"："+d.parts.map(x=>x.name+(x.sets_reps?" "+x.sets_reps:"")).join("、")).join("\n")+"\n\n确认无误后点「保存计划」";}
  else{$("pPrev").textContent="⚠️ 没解析出内容，检查文本格式（每行：星期 动作 组次）";}
 }catch(e){$("pPrev").textContent="解析失败："+e.message;}
 $("pParse").disabled=false;
};
let curParsed=null;
$("pSaveP").onclick=async()=>{
 if(!curParsed){toast("先点「解析预览」生成计划");return;}
 $("pSaveP").disabled=true;
 try{const j=await api("/api/plan",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user,plan:curParsed})},60000);
  curPlan={days:j.days||[]};
  toast("已保存 "+curPlan.days.length+" 天计划");loadPlanView();
 }catch(e){toast("保存失败："+e.message);}
 $("pSaveP").disabled=false;
};
async function loadProfile(){
 try{const p=await api("/api/profile?user="+user);
  $("s_name").value=p.display_name||"";$("s_gender").value=p.gender||"male";
  $("s_age").value=p.age??"";$("s_height").value=p.height_cm??"";
  $("s_weight").value=p.weight_kg??"";$("s_targetw").value=p.target_weight_kg??"";
  $("s_days").value=p.training_days??4;
  $("s_deficit").value=p.deficit??350;
  updateCalc();
  const t=p.targets||{};
  $("s_hint").textContent="当前热量线 "+(t.daily_kcal??"?")+" kcal / 蛋白 "+(t.protein_g??"?")+"g（"+(t.calculated_at||"")+" 算）";
 }catch(e){toast("读取档案失败："+e.message);}
}
$("s_save").onclick=async()=>{
 try{const j=await api("/api/profile",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user,display_name:$("s_name").value,gender:$("s_gender").value,
   age:$("s_age").value,height_cm:$("s_height").value,weight_kg:$("s_weight").value,
   target_weight_kg:$("s_targetw").value,training_days:$("s_days").value,deficit:$("s_deficit").value})});
  const btn=user==="beifeng"?$("u1"):$("u2");
  btn.textContent=(user==="beifeng"?"🧑 ":"👩 ")+($("s_name").value.trim()||user);
  toast("已保存，热量线 "+j.targets.daily_kcal+" kcal / 蛋白 "+j.targets.protein_g+"g");
  $("s_hint").textContent="当前热量线 "+j.targets.daily_kcal+" kcal / 蛋白 "+j.targets.protein_g+"g（刚重算）";
  refresh();
 }catch(e){toast("保存失败："+e.message);}
};
paintSeg();
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
let TOKEN=localStorage.getItem("fg_token")||"";
async function api(path,opts,tmo,retried){const ctl=("AbortController"in window)?new AbortController():null;
 const to=ctl?setTimeout(()=>ctl.abort(),tmo||180000):null;
 if(ctl&&opts&&opts.signal)opts.signal.addEventListener("abort",()=>ctl.abort());
 activeCtl=ctl;
 const h=Object.assign({},(opts&&opts.headers)||{});
 if(TOKEN)h["X-Access-Token"]=TOKEN;
 try{const r=await fetch(path,Object.assign({},opts,{headers:h},ctl?{signal:ctl.signal}:{}));
  let j=null;try{j=await r.json()}catch(_){}
  if(r.status===401&&!retried){const c=prompt("此站受访问码保护，请输入访问码：");
   if(c){TOKEN=c;localStorage.setItem("fg_token",c);return api(path,opts,tmo,true);}}
  if(!r.ok)throw new Error((j&&j.error)||("HTTP "+r.status));return j;}
 finally{if(to)clearTimeout(to);}}
let busy=false,timer=null,suppress=false,activeCtl=null;
let viewDate=null,monthDays={},monthFetched={},CAL_TARGET=0; // monthDays按用户切换时清空（避免串数据）
function invalidateMonthCache(){monthFetched={};} // 记录/删除/清空后调用，否则环的月度聚合是死缓存
function ringSvg(pct){ // 进度环组件：viewBox 44 自适应容器；弧封顶100%，dashoffset 纯CSS过渡
 const R=19,SW=3,C=2*Math.PI*R,off=C*(1-Math.min(100,Math.max(0,pct))/100);
 return "<svg class='cring' viewBox='0 0 44 44' aria-hidden='true'>"+
  "<circle class='ring-track' cx='22' cy='22' r='"+R+"' fill='none' stroke-width='"+SW+"'/>"+
  "<circle class='ring-fill' cx='22' cy='22' r='"+R+"' fill='none' stroke-width='"+SW+"' stroke-linecap='round'"+
  " stroke-dasharray='"+C+"' stroke-dashoffset='"+off+"' transform='rotate(-90 22 22)'/></svg>";
}
function todayStr(){return new Date().toISOString().slice(0,10);}
function labelFor(ds){const t=todayStr();
 if(ds===t)return"今天";
 const y=dstrShift(t,-1);if(ds===y)return"昨天";
 const d=new Date(ds+"T12:00:00");
 return (d.getMonth()+1)+"月"+d.getDate()+"日 "+["周日","周一","周二","周三","周四","周五","周六"][d.getDay()];}
function dstrShift(base,n){const d=new Date((base||todayStr())+"T12:00:00");d.setDate(d.getDate()+n);return d.toISOString().slice(0,10);}
function setViewDate(ds){if(ds>todayStr())ds=todayStr();
 $("list").classList.add("dim"); // 乐观切换：旧明细淡化保持可见，数据到了再替换
 viewDate=(ds===todayStr())?null:ds;renderDateHead();refresh();}
let calY=0,calM=0;
function openCal(){const b=viewDate||todayStr();calY=+b.slice(0,4);calM=+b.slice(5,7);
 showBack("calBack");requestAnimationFrame(()=>$("calBack").classList.add("open"));renderCal();}
function closeCal(){$("calBack").classList.remove("open");hideBack("calBack");}
$("dLabel").onclick=openCal;
$("calClose").onclick=closeCal;
$("calBack").onclick=e=>{if(e.target.id==="calBack")closeCal();};
$("calPrevM").onclick=()=>{calM--;if(calM<1){calM=12;calY--;}
 ensureMonth(calY+"-"+String(calM).padStart(2,"0"));renderCal();};
$("calNextM").onclick=()=>{calM++;if(calM>12){calM=1;calY++;}
 ensureMonth(calY+"-"+String(calM).padStart(2,"0"));renderCal();};
$("calToday").onclick=()=>{const td=todayStr();
 setViewDate(td);calY=+td.slice(0,4);calM=+td.slice(5,7);
 ensureMonth(td.slice(0,7));renderCal();closeCal();};
function renderCal(){
 $("calTitle").textContent=calY+"年"+calM+"月";
 const first=new Date(calY,calM-1,1);
 let lead=first.getDay()-1;if(lead<0)lead=6;
 const dim=new Date(calY,calM,0).getDate();
 const prevDim=new Date(calY,calM-1,0).getDate();
 const t=todayStr();const sel=viewDate||todayStr();
 let h="";
 for(let i=0;i<lead;i++) // 上月溢出日期：浅灰弱化、不可点
  h+="<div class='calcell'><div class='cday out'>"+(prevDim-lead+1+i)+"</div></div>";
 for(let d=1;d<=dim;d++){
  const ds=calY+"-"+String(calM).padStart(2,"0")+"-"+String(d).padStart(2,"0");
  const future=ds>t;
  const md=monthDays[ds]||{},has=md.n>0;
  const pct=has&&CAL_TARGET?md.eaten/CAL_TARGET*100:0;
  const cls="cday"+(has?" has":"")+(future?" dis":"")+(ds===sel?" sel":"")+(ds===t?" today":"");
  h+="<div class='calcell'><div class='"+cls+"' data-d='"+ds+"'>"+(has?ringSvg(pct):"")+d+"</div></div>";
 }
 const trail=(7-(lead+dim)%7)%7;
 for(let i=1;i<=trail;i++) // 下月溢出补满整周
  h+="<div class='calcell'><div class='cday out'>"+i+"</div></div>";
 $("calGrid").innerHTML=h;
 $("calGrid").querySelectorAll(".cday:not(.dis):not(.out)").forEach(c=>c.onclick=()=>{
  setViewDate(c.dataset.d);hideBack("calBack");}); // 选中历史日期→加载当日记录并关闭
}
function renderDateHead(){
 $("dLabel").textContent=labelFor(viewDate||todayStr())+" ▾";
 $("clearBtn").style.display="";} // 清空跟随所选日期（后端已支持 date），历史日期也可清
$("dLabel").onclick=openCal;
const photoUrls={};
function makeThumb(b64,max=240){ // 保存时前端生成240px缩略图（零依赖：浏览器canvas），列表加载~8KB vs 原图100KB+
 return new Promise(ok=>{
  const img=new Image();
  img.onload=()=>{const s=Math.min(1,max/Math.max(img.width,img.height));
   const cv=document.createElement("canvas");
   cv.width=Math.max(1,Math.round(img.width*s));cv.height=Math.max(1,Math.round(img.height*s));
   cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
   ok(cv.toDataURL("image/jpeg",0.7).split(",")[1]);};
  img.onerror=()=>ok(null);
  img.src="data:image/jpeg;base64,"+b64;});
}
async function loadThumb(id,img,uid){
 if(photoUrls[id]){img.src=photoUrls[id];return;} // blob缓存命中直接复用，切日期不重拉
 try{const r=await fetch("/photo/"+id+"?thumb=1"+(uid?"&user="+uid:""),TOKEN?{headers:{"X-Access-Token":TOKEN}}:{});
  if(!r.ok){img.style.display="none";return;}
  const b=await r.blob();
  photoUrls[id]=URL.createObjectURL(b);img.src=photoUrls[id];
  const ks=Object.keys(photoUrls); // 上限50张：LRU淘汰，防翻历史内存无限涨
  if(ks.length>50){URL.revokeObjectURL(photoUrls[ks[0]]);delete photoUrls[ks[0]];}
 }catch(e){img.style.display="none";}
}
function setLoading(msg){busy=true;$("bPhoto").disabled=true;$("bSend").disabled=true;
 suppress=false;
 const el=$("reply"),t0=Date.now();el.className="wait";
 el.innerHTML="<span class='spin'></span>"+msg+" <b id='el'></b>"+
  "<span class='cxlink' onclick='cancelWait()'>取消等待</span>";
 timer=setInterval(()=>{const el=$("el");if(!el){if(timer)clearInterval(timer);return;}
  const s=Math.round((Date.now()-t0)/1000);
  el.textContent=s+"s"+(s>12?" · 大图高峰会慢些":"");},500);}
function done(){busy=false;$("bPhoto").disabled=false;$("bSend").disabled=false;if(timer)clearInterval(timer);}
let sendCtl=null;
function cancelWait(){if(activeCtl)activeCtl.abort();}
function showOk(t){done();if(suppress)return;const el=$("reply");el.className="ok";el.textContent=t;}
function showErr(t){done();if(suppress)return;const el=$("reply");el.className="err";el.textContent="❌ "+t;}
function toast(t){const el=$("toast");el.textContent=t;el.classList.add("show");
 setTimeout(()=>el.classList.remove("show"),2200);}
const MEAL_ORD={"早餐":0,"午餐":1,"晚餐":2,"加餐":3};
function listSkeleton(){ // 明细卡骨架屏：首屏/切用户时替代转圈，数据到后整体覆盖
 const row="<div style='display:flex;align-items:center;gap:10px;padding:8px'>"+
  "<div class='skel' style='width:48px;height:48px;border-radius:12px;flex:none'></div>"+
  "<div style='flex:1'><div class='skel' style='height:14px;width:60%;margin-bottom:8px'></div>"+
  "<div class='skel' style='height:11px;width:35%'></div></div>"+
  "<div class='skel' style='width:44px;height:13px'></div></div>";
 const card="<div class='card gcard'><div class='skel' style='height:16px;width:38%;margin-bottom:10px'></div>"+row+row+"</div>";
 $("list").innerHTML=card+card;
}
let refreshSeq=0;
async function refresh(){
 const seq=++refreshSeq; // 竞态守卫：快速切日期时旧响应后到会被丢弃，防止旧数据覆盖新选择
 if(!$("list").dataset.ready)listSkeleton();
 try{const j=await api("/api/today?user="+user+(viewDate?"&date="+viewDate:""));
  if(seq!==refreshSeq)return;
  renderHero(j);renderDetail(j);$("list").dataset.ready=1;}
 catch(e){if(seq===refreshSeq){$("list").classList.remove("dim");toast("加载失败："+e.message);}}
 renderStrip();renderDateHead(); // 用本地缓存即时渲染周条/日期头，不等网络
 try{const pl=await api("/api/plan?user="+user);
  const w=await api("/api/workouts?user="+user);
  if(seq!==refreshSeq)return;
  renderWK(pl,w.records||[]);
 }catch(e){}
 await Promise.all([ensureMonth(todayStr()),ensureMonth(dstrShift(todayStr(),-7))]); // 补拉上月：周条跨月天有环数据
 renderStrip();
}
function countUp(el,to){ // 剩余热量数字平滑过渡：300ms ease-out（rAF三次缓出），避免数值跳变
 const from=parseInt(el.textContent,10)||0;if(from===to){el.textContent=to;return;}
 const t0=performance.now(),dur=300;
 const step=t=>{const p=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-p,3);
  el.textContent=Math.round(from+(to-from)*e);
  if(p<1)requestAnimationFrame(step);};
 requestAnimationFrame(step);}
function renderHero(j){
 CAL_TARGET=j.target||CAL_TARGET; // 环形比例的分母（当日目标热量）
 countUp($("remain"),j.remaining);
 $("remain").classList.toggle("over",j.remaining<0);
 const pct=Math.max(0,Math.min(100,j.target?j.eaten/j.target*100:0));
 const bar=$("bar");bar.classList.toggle("warn",pct>85);
 bar.firstElementChild.style.width=pct+"%";
 $("sumline").textContent=(j.remaining<0?"⚠️ 已超出 "+(-j.remaining)+" 千卡 ｜ ":"")
  +"已吃 "+j.eaten+" / "+j.target+" kcal ｜ 蛋白 "+j.protein+" / "+j.protein_target+" g";
 const d=$("dinner");d.textContent=j.dinner_tip?("🌙 "+j.dinner_tip):"";d.classList.toggle("show",!!j.dinner_tip);
}
function renderDetail(j){
 _recs={};j.records.forEach(r=>_recs[r.id]=r);
 const RAT={"早餐":0.25,"午餐":0.35,"晚餐":0.30,"加餐":0.10};
 const sug=m=>{const t=(j.target||0)*(RAT[m]||0);
  return (Math.round(t*0.85/5)*5)+" ~ "+(Math.round(t*1.15/5)*5);};
 const recs=[...j.records].sort((a,b)=>(MEAL_ORD[a.meal_type]??9)-(MEAL_ORD[b.meal_type]??9));
 const groups=[];let cur=null;
 for(const r of recs){
  if(!cur||cur.m!==r.meal_type){cur={m:r.meal_type,items:[],tot:0};groups.push(cur);}
  cur.items.push(r);cur.tot+=r.kcal||0;
 }
 const GEMO={"早餐":"☀️","午餐":"🌤️","晚餐":"🌙","加餐":"🍪"};
 let h="";
 for(const g of groups){
  h+="<div class='card gcard'><div class='ghead'>"+
   "<span class='gh-emoji'>"+(GEMO[g.m]||"🍽️")+"</span><span class='gh-name'>"+esc(g.m)+"</span>"+
   "<div class='gh-tot'><small>本餐合计</small><b>"+g.tot+" 千卡</b></div></div>"+
   "<div class='gsug'>热量建议："+sug(g.m)+" kcal</div>";
  for(const r of g.items){
   h+="<div class='mrow' data-id='"+r.id+"'>"+
    "<div class='dz'><button class='delzone2' data-del='"+r.id+"' aria-label='删除"+esc(r.food)+"'>删除</button></div>"+
    "<div class='mmain'>"+
    (r.photo?"<img class='thumb' data-photo='"+r.id+"' alt=''>":"<div class='thumb ph' role='img' aria-label='暂无照片'>" +
    "<svg width='26' height='26' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' aria-hidden='true'><path d='M4 13h16'/><path d='M5 13a7 7 0 0 0 14 0z'/></svg></div>")+
    "<div class='mname'>"+esc(r.food)+"<div class='msub'>"+
    [r.portion,r.note].filter(Boolean).map(esc).join(" · ")+"</div></div>"+
    "<div class='kcell'><b>"+r.kcal+"</b> 千卡<span class='chev'>›</span></div></div></div>";
  }
  h+="</div>";
 }
 $("list").innerHTML=h||"<div class='muted' style='padding:8px 0'>这一天还没有记录</div>";
 document.querySelectorAll("#list img[data-photo]").forEach(im=>loadThumb(im.dataset.photo,im,user));
 bindSwipe($("list"));
 $("list").classList.remove("dim"); // 数据到位，结束乐观淡化
}
let openId=null,suppressClick=false,_recs={};
function closeOpen(exceptId){document.querySelectorAll("#list .mrow").forEach(row=>{
 if(+row.dataset.id!==exceptId){row.querySelector(".mmain").style.transform="";row.classList.remove("open");}});
 if(exceptId==null)openId=null;}
function bindSwipe(list){
 list.querySelectorAll(".mrow").forEach(row=>{
  const rid=+row.dataset.id,main=row.querySelector(".mmain");
  let sx=0,sy=0,drag=false,moved=false,cap=false;
  main.addEventListener("pointerdown",e=>{sx=e.clientX;sy=e.clientY;drag=true;moved=false;cap=false;main.style.transition="none";});
  main.addEventListener("pointermove",e=>{if(!drag)return;
   const dx=e.clientX-sx,dy=e.clientY-sy;
   if(!moved&&Math.abs(dx)>8&&Math.abs(dx)>Math.abs(dy)){
    moved=true;suppressClick=true;setTimeout(()=>suppressClick=false,350);
    try{main.setPointerCapture(e.pointerId);}catch(_){}}
   if(!moved)return;
   const base=openId===rid?-72:0;
   main.style.transform="translateX("+Math.max(-72,Math.min(0,base+dx))+"px)";});
  const end=e=>{if(!drag)return;drag=false;main.style.transition="";
   if(cap){try{main.releasePointerCapture(e.pointerId);}catch(_){}}
   if(!moved){if(openId===rid){main.style.transform="";openId=null;}return;}
   const t=(openId===rid?-72:0)+(e.clientX-sx);
   if(t<-36){closeOpen(rid);main.style.transform="translateX(-72px)";row.classList.add("open");openId=rid;}
   else{main.style.transform="";row.classList.remove("open");if(openId===rid)openId=null;}};
  main.addEventListener("pointerup",end);
  main.addEventListener("pointercancel",()=>{drag=false;main.style.transition="";
   main.style.transform=openId===rid?"translateX(-72px)":"";row.classList.toggle("open",openId===rid);});
  main.addEventListener("click",e=>{if(suppressClick||drag||moved)return;
   if(e.target.closest(".kcell"))openEdit(rid);});
  row.querySelectorAll(".delzone2").forEach(b=>b.addEventListener("click",()=>delId(rid)));
 });
}
async function sendText(){
 if(busy)return;
 const t=$("text").value.trim();if(!t)return;
 setLoading("识别中…");
 try{const j=await api("/api/meal",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,text:t,date:viewDate||todayStr()})},240000);
  if(j.reply&&j.reply.indexOf("没识别出")>=0){showErr(j.reply);}else{showOk(j.reply);bump();invalidateMonthCache();refresh();}
  $("text").value="";
 }catch(e){showErr(friendly(e.message));}
}
function friendly(m){
 if(/abort/i.test(m))return "已取消等待（后台可能已记上，稍后在明细核对）";
 if(/timed out/i.test(m))return "网关高峰无响应（已等待超时）。稍后重试；长语音建议拆成按餐短句，更快更稳";
 if(/api_key/i.test(m))return m;
 return m;
}
$("text").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();sendText();}});
$("bSend").onclick=sendText;
$("bPhoto").onclick=()=>$("photo").click(); // Safari原生三项弹层已够用，不再自绘
// ---- 分析结果页（照片专用：识别→修正→确认保存）----
const MEALS=["早餐","午餐","晚餐","加餐"];
let avItems=[],avB64=null,avMeal="早餐",avBusy=false,avTarget={protein:0,fat:0,carb:0},avDay={protein:0,fat:0,carb:0};
$("avmenu").innerHTML=MEALS.map(m=>"<button data-m='"+m+"'>"+m+"</button>").join("");
function hourMeal(h){return h<10?"早餐":h<14?"午餐":h<17?"加餐":h<21?"晚餐":"加餐";}
function exifHour(buf){
 try{
  const v=new DataView(buf);
  if(v.byteLength<12||v.getUint16(0)!==0xFFD8)return null;
  let off=2;
  while(off+4<v.byteLength){
   if(v.getUint8(off)!==0xFF)break;
   const mk=v.getUint8(off+1),len=v.getUint16(off+2);
   if(mk===0xE1&&off+10<v.byteLength&&v.getUint32(off+4)===0x45786966)return tiffHour(off+10);
   off+=2+len;
  }
 }catch(e){}
 return null;
 function tiffHour(t){
  const le=v.getUint16(t)===0x4949;
  const g16=o=>v.getUint16(t+o,le),g32=o=>v.getUint32(t+o,le);
  let ifd=t+g32(4),ptr=0,hour=null;
  for(let pass=0;pass<2&&ifd;pass++){
   const n=g16(ifd);
   for(let i=0;i<n;i++){
    const en=ifd+2+i*12,tag=g16(en);
    if(pass===0&&tag===0x8769)ptr=g32(en+8);
    if(pass===1&&tag===0x9003){
     const s=t+g32(en+8);let dt="";
     for(let k=0;k<19;k++){const c=v.getUint8(s+k);if(c>=32)dt+=String.fromCharCode(c);}
     const m=dt.match(/\d{4}:\d{2}:\d{2} (\d{2}):(\d{2})/);
     if(m)hour=+m[1];
    }
   }
   ifd=pass===0&&ptr?t+ptr:null;
  }
  return hour;
 }
}
let avInt=null;
function avWait(msg){$("avItems").innerHTML="<div class='avload'><span class='spin'></span> "+msg+" <b id='avel'></b></div>";
 const t0=Date.now();if(avInt)clearInterval(avInt);
 avInt=setInterval(()=>{const el=$("avel");if(!el){if(avInt)clearInterval(avInt);return;}
  const s=Math.round((Date.now()-t0)/1000);
  const ph=s<10?"":s<25?" · 正在分析份量…":s<45?" · 正在计算热量…":" · 网络高峰，马上好…";
  el.textContent=s+"s"+ph;},500);}
function avDone(){if(avInt)clearInterval(avInt);avInt=null;}
function avBusyUI(on){$("avFix").disabled=on;$("avSave").disabled=on;}
function renderAv(){
 avDone();
 $("avMeal").textContent="今天 "+avMeal+" ▼";
 $("avmenu").querySelectorAll("button").forEach(b=>b.classList.toggle("on",b.dataset.m===avMeal));
 const tot=k=>avItems.reduce((s,i)=>s+(i[k]||0),0);
 const has=avItems.length>0;
 $("avKcal").style.display=has?"block":"none";
 $("avM").style.display=has?"flex":"none";
 if(has){
  $("avKcal").innerHTML="<div class='text-heading'>这餐热量</div>"+
   "<div class='text-huge-cal'>"+tot("kcal")+" <span class='text-unit'>千卡</span></div>"+
   "<div style='display:flex;justify-content:flex-end;margin-top:10px'><span class='tag'>今天 "+avMeal+"</span></div>";
  $("avM").innerHTML=mcard("蛋白质",tot("protein_g"),avDay.protein,avTarget.protein)+
   mcard("脂肪",tot("fat_g"),avDay.fat,avTarget.fat)+
   mcard("碳水",tot("carb_g"),avDay.carb,avTarget.carb);
 }
 let h="";
 for(const it of avItems)h+="<div class='avitem'><div class='avname'><b>"+esc(it.food)+"</b> <span class='muted'>"+
  esc(it.portion||"")+"</span> "+esc(it.note||"")+"</div><div class='avk'>"+it.kcal+" 千卡</div></div>";
 $("avItems").innerHTML=h||"<div class='avload'><span class='spin'></span> 识别中…</div>";
}
function mcard(label,mealVal,dayVal,target){
 const pct=target>0?Math.min(100,Math.round(dayVal/target*100)):0;
 const R=26,C=2*Math.PI*R,off=C*(1-pct/100);
 return "<div class='card mcd'><div class='mcrow'>"+
  "<svg width='64' height='64' viewBox='0 0 64 64'>"+
  "<circle class='ring-track' cx='32' cy='32' r='"+R+"' fill='none' stroke-width='7'/>"+
  "<circle class='ring-fill' cx='32' cy='32' r='"+R+"' fill='none' stroke-width='7' stroke-linecap='round' "+
  "stroke-dasharray='"+C+"' stroke-dashoffset='"+off+"' transform='rotate(-90 32 32)'/>"+
  "<text x='32' y='37' text-anchor='middle' font-size='13.5' font-weight='700' style='fill:var(--text-main)'>"+pct+"%</text></svg>"+
  "<div class='mcol'><div class='mc-l'>"+label+"</div><div class='mc-v'>"+mealVal+"g</div></div></div>"+
  "<div class='mc-n'>已吃 <b>"+dayVal+"g</b> / 目标 <b>"+(target||0)+"g</b></div></div>";
}
function closeAv(){$("av").style.display="none";avBusy=false;}
$("avBack").onclick=()=>{
 if(avItems.length&&!avSaved&&!confirm("识别结果未保存，确定放弃吗？"))return;
 closeAv();};
$("avMeal").onclick=e=>{e.stopPropagation();
 const m=$("avmenu");m.style.display=m.style.display==="block"?"none":"block";};
$("avmenu").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
 avMeal=b.dataset.m;renderAv();$("avmenu").style.display="none";});
document.addEventListener("click",e=>{if(!e.target.closest("#avmenu")&&!e.target.closest("#avMeal"))$("avmenu").style.display="none";});
$("avSave").onclick=async()=>{
 if(avBusy||!avItems.length)return;avBusy=true;
 try{
  await api("/api/save",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,meal_type:avMeal,items:avItems,image:avB64,thumb:avB64?await makeThumb(avB64):null,date:viewDate||todayStr()})});
  const kcal=avItems.reduce((s,i)=>s+(i.kcal||0),0);
  closeAv();toast((kcal<0?"已扣回 ":"已记录 ")+kcal+" 千卡");invalidateMonthCache();refresh();
 }catch(e){toast("保存失败："+e.message);}
 avBusy=false;
};
let fixB64=null;
$("avFix").onclick=()=>{if(avBusy||!avB64)return;
 fixB64=null;$("fixText").value="";$("fixCnt").textContent="0/200";
 $("fixThumb").style.display="none";$("fixPhotoHint").textContent="可选：拍剩余的盘子，AI 按图扣减";
 $("fixErr").classList.remove("show");
 showBack("fixBack");$("fixText").focus();};
$("fixClose").onclick=()=>{if(avBusy){toast("AI 正在分析，请稍候…");return;}hideBack("fixBack");};
$("fixBack").onclick=e=>{if(e.target.id!=="fixBack")return;
 if(avBusy){toast("AI 正在分析，请稍候…");return;}hideBack("fixBack");};
$("fixText").addEventListener("input",e=>{$("fixCnt").textContent=e.target.value.length+"/200";});
$("fixPhotoBtn").onclick=()=>$("fixPhoto").click();
$("fixPhoto").addEventListener("change",async e=>{
 const f=e.target.files[0];e.target.value="";
 if(!f)return;
 try{
  const img=new Image();img.src=await new Promise((ok,no)=>{const fr=new FileReader();
   fr.onload=()=>ok(fr.result);fr.onerror=no;fr.readAsDataURL(f);});
  await new Promise(ok=>img.onload=ok);
  const cv=document.createElement("canvas"),s=Math.min(1,1024/Math.max(img.width,img.height));
  cv.width=img.width*s;cv.height=img.height*s;cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
  fixB64=cv.toDataURL("image/jpeg",0.8).split(",")[1];
  const th=$("fixThumb");th.src="data:image/jpeg;base64,"+fixB64;th.style.display="block";
  $("fixPhotoHint").textContent="已附剩余照片 ✓";
 }catch(err){toast("读图失败："+err.message);}
});
$("fixOk").onclick=async()=>{
 const t=$("fixText").value.trim();
 if(!t&&!fixB64){toast("写修正内容或附剩余照片");return;}
 avBusy=true;$("fixOk").disabled=true;
 const t0=Date.now();
 $("fixOk").innerHTML="<span class='spin' style='border-color:rgba(255,255,255,.5);border-top-color:#fff;display:inline-block;vertical-align:-2px;margin-right:6px'></span>分析中… <b id='fs'>0s</b>";
 const fi=setInterval(()=>{const el=$("fs");if(!el){clearInterval(fi);return;}
  el.textContent=Math.round((Date.now()-t0)/1000)+"s";},500);
 const fe=$("fixErr");fe.classList.remove("show");
 try{
  const j=await api("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,image:fixB64||avB64,text:t,prev:avItems})},200000);
  clearInterval(fi);
  avItems=j.items||[];if(j.targets)avTarget=j.targets;if(j.day)avDay=j.day;renderAv();hideBack("fixBack");
 }catch(e){
  clearInterval(fi);
  fe.textContent="修正失败："+e.message+"（已识别结果未丢失，可重试或返回）";
  fe.classList.add("show");
 }
 $("fixOk").disabled=false;$("fixOk").textContent="确定";avBusy=false;
};
async function mealPhotoChange(e){ // 拍照/相册共用入口
 const f=e.target.files[0];e.target.value="";
 if(!f||avBusy)return;
 avBusy=true;
 try{
  const hr=exifHour(await f.arrayBuffer());
  avMeal=hr!=null?hourMeal(hr):hourMeal(new Date().getHours());
  const img=new Image();img.src=await new Promise((ok,no)=>{const fr=new FileReader();
   fr.onload=()=>ok(fr.result);fr.onerror=no;fr.readAsDataURL(f);});
  await new Promise(ok=>img.onload=ok);
  const cv=document.createElement("canvas"),s=Math.min(1,1024/Math.max(img.width,img.height));
  cv.width=img.width*s;cv.height=img.height*s;cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
  avB64=cv.toDataURL("image/jpeg",0.8).split(",")[1];
  $("avImg").src="data:image/jpeg;base64,"+avB64;
  avItems=[];$("av").style.display="block";window.scrollTo(0,0);renderAv();
  avBusyUI(true);
  avWait("识别中");
  const j=await api("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,image:avB64})},200000);
  avItems=j.items||[];if(j.targets)avTarget=j.targets;if(j.day)avDay=j.day;renderAv();
  if(!avItems.length)$("avItems").innerHTML="<div class='avload'>🤔 没识别出食物：点「AI 修正」描述一下，或返回重拍</div>";
 }catch(err){avDone();toast("识别失败："+friendly(err.message));closeAv();}
 avBusyUI(false);avBusy=false;
}
$("photo").addEventListener("change",mealPhotoChange);
// ---- 编辑抽屉 & 删除确认 ----
let editId0=null,editB64=null,editBusy=false,delId0=null;
function openEdit(id){
 const r=_recs[id];if(!r)return;editId0=id;editB64=null;
 if(r.photo){$("eThumb").style.display="block";$("eThumbPh").style.display="none";loadThumb(id,$("eThumb"),user);}
 else{$("eThumb").style.display="none";$("eThumbPh").style.display="flex";}
 $("eFood").value=r.food;$("ePortion").value=r.portion||"";
 $("eKcal").value=r.kcal;$("eProtein").value=(r.protein_g==null?"":r.protein_g);
 editBase={kcal:r.kcal||0,per:pnum(r.portion),prot:(r.protein_g==null?null:r.protein_g)};
 kcalTouched=false;protTouched=false;
 $("ePills").innerHTML=MEALS.map(m=>"<button data-m='"+m+"' class='"+(m===r.meal_type?"on":"")+"'>"+m+"</button>").join("");
 $("ePills").querySelectorAll("button").forEach(b=>b.onclick=()=>{
  $("ePills").querySelectorAll("button").forEach(x=>x.classList.remove("on"));b.classList.add("on");});
 showBack("editBack");requestAnimationFrame(()=>$("editBack").classList.add("open"));
}
function pnum(s){const m=String(s||"").match(/(\d+(?:\.\d+)?)/);return m?parseFloat(m[1]):null;}
let editBase={kcal:0,per:null,prot:null},kcalTouched=false,protTouched=false;
$("ePortion").addEventListener("input",()=>{
 if(kcalTouched&&protTouched)return;
 const nNew=pnum($("ePortion").value),nOld=editBase.per;
 if(!nOld||!nNew||nNew<=0)return;
 if(!kcalTouched&&editBase.kcal>0)$("eKcal").value=Math.round(editBase.kcal*nNew/nOld);
 if(!protTouched&&editBase.prot!=null)$("eProtein").value=Math.round(editBase.prot*nNew/nOld);
});
$("eKcal").addEventListener("input",()=>{kcalTouched=true;});
$("eProtein").addEventListener("input",()=>{protTouched=true;});
function closeEdit(){$("editBack").classList.remove("open");hideBack("editBack");}
$("editBack").onclick=e=>{if(!e.target.closest(".sheet"))closeEdit();};
$("eClose").onclick=closeEdit;$("eCancel").onclick=closeEdit;
$("eThumb").onclick=()=>$("ePhoto").click();$("eThumbPh").onclick=()=>$("ePhoto").click();
$("ePhoto").addEventListener("change",async e=>{
 const f=e.target.files[0];e.target.value="";if(!f)return;
 try{
  const img=new Image();img.src=await new Promise((ok,no)=>{const fr=new FileReader();fr.onload=()=>ok(fr.result);fr.onerror=no;fr.readAsDataURL(f);});
  await new Promise(ok=>img.onload=ok);
  const cv=document.createElement("canvas"),s=Math.min(1,1024/Math.max(img.width,img.height));
  cv.width=img.width*s;cv.height=img.height*s;cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
  editB64=cv.toDataURL("image/jpeg",0.8).split(",")[1];
  $("eThumb").src="data:image/jpeg;base64,"+editB64;$("eThumb").style.display="block";$("eThumbPh").style.display="none";
 }catch(err){toast("读图失败："+err.message);}
});
$("eSave").onclick=async()=>{
 if(editBusy)return;editBusy=true;$("eSave").disabled=true;$("eSave").textContent="保存中…";
 const meal=$("ePills").querySelector("button.on").dataset.m;
 const kcalV=$("eKcal").value;
 try{
  await api("/api/correct",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({id:editId0,action:"edit",
    food:$("eFood").value.trim()||undefined,kcal:kcalV===""?undefined:parseFloat(kcalV),
    portion:$("ePortion").value.trim(),protein_g:$("eProtein").value===""?undefined:parseFloat($("eProtein").value),
    meal_type:meal,image:editB64||undefined,thumb:editB64?await makeThumb(editB64):undefined})},60000);
  closeEdit();bump();invalidateMonthCache();refresh();toast("已保存 ✓");
 }catch(e){toast("保存失败："+e.message);}
 $("eSave").disabled=false;$("eSave").textContent="保存修改";editBusy=false;
};
async function delId(id){try{await api("/api/correct",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({id:id,action:"delete"})});toast("已删除");bump();invalidateMonthCache();refresh();}catch(e){toast("删除失败："+e.message);}}
let clearing=false;
$("clearBtn").onclick=()=>showBack("clearBack");
$("cCancel").onclick=()=>hideBack("clearBack");
$("cOk").onclick=async()=>{
 hideBack("clearBack");if(clearing)return;clearing=true;
 try{const j=await api("/api/clear",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user,date:viewDate||todayStr()})});toast("已清空 "+j.cleared+" 条");bump();invalidateMonthCache();refresh();}
 catch(e){toast("清空失败："+e.message);}
 clearing=false;
};
function bump(){const el=$("remain");el.classList.remove("bump");void el.offsetWidth;el.classList.add("bump");}
// ---- 本周训练卡（计划 vs 实际）----
const WKDAYS=["周一","周二","周三","周四","周五","周六","周日"];
async function ensureMonth(ym){
 ym=ym.slice(0,7); // 兼容误传完整日期（后端校验 YYYY-MM，传整日期会400且被静默吞掉）
 if(monthFetched[ym])return;monthFetched[ym]=true;
 try{const j=await api("/api/month?user="+user+"&ym="+ym);
  j.days.forEach(d=>monthDays[d.date]={eaten:d.eaten,n:d.n});
 }catch(e){delete monthFetched[ym];}
}
function renderStrip(){
 const el=$("strip");let h="";
 const sel=viewDate||todayStr();
 for(let i=6;i>=0;i--){
  const d=new Date();d.setDate(d.getDate()-i);
  const ds=d.toISOString().slice(0,10);
  const wd=["日","一","二","三","四","五","六"][d.getDay()];
  const md=monthDays[ds]||{},n=md.n||0;
  const pct=n&&CAL_TARGET?md.eaten/CAL_TARGET*100:0;
  const selCls=(ds===sel)?" sel":"";
  const todayCls=(ds===todayStr())?" today":"";
  h+="<div class='sday"+(n>0?" has":"")+selCls+todayCls+"' data-d='"+ds+"'>"+
   "<div class='swd'>"+wd+"</div><div class='ring'>"+(n?ringSvg(pct):"")+d.getDate()+"</div></div>";
 }
 el.innerHTML=h;
 el.querySelectorAll(".sday").forEach(sd=>sd.onclick=()=>setViewDate(sd.dataset.d));
}
function renderWK(plan,wk){
 const el=$("wkCard");
 if(!plan.days||!plan.days.length){
  el.innerHTML="<div style='display:flex;align-items:center'><div class='muted' style='flex:1'>🏋️ 还没有训练计划</div>"+
   "<button class='tag' style='cursor:pointer' onclick='showPTab(\"tPlan\",\"pPlan\")'>去设置导入</button></div>";
  return;}
 const doneBy={};wk.forEach(w=>doneBy[w.date]=(doneBy[w.date]||0)+1);
 const monday=new Date();monday.setDate(monday.getDate()-monday.getDay()+1);
 const today=new Date().toISOString().slice(0,10);
 let h="<div style='display:flex;align-items:center;margin-bottom:6px'>"+
  "<div style='font-weight:700;color:var(--text-main)'>🏋️ 本周训练</div>"+
  "<div class='muted' style='margin-left:auto'>计划 "+plan.days.length+" 练 · 已练 "+wk.length+"</div></div>";
 for(const d of plan.days){
  const idx=WKDAYS.indexOf(d.dow);if(idx<0)continue;
  const ds=new Date(monday);ds.setDate(ds.getDate()+idx);
  const dsStr=ds.toISOString().slice(0,10);
  const dn=doneBy[dsStr]||0;
  const mark=dn>0?"<span style='color:var(--color-primary);font-weight:700'>✓</span>":
   (dsStr===today?"<span class='tag'>今天</span>":(dsStr<today?"<span class='muted'>✗</span>":"<span class='muted'>未到</span>"));
  h+="<div class='wkrow'><span class='chip'>"+d.dow+"</span><span style='flex:1;color:var(--text-main)'>"+
   d.parts.map(p=>esc(p.name)+(p.sets_reps?" "+esc(p.sets_reps):"")).join("、")+"</span>"+mark+"</div>";
 }
 el.innerHTML=h;
}
// ---- 减脂缺口滑块：实时计算明细 ----
function updateCalc(){
 const w=parseFloat($("s_weight").value),h=parseFloat($("s_height").value),a=parseFloat($("s_age").value);
 const g=$("s_gender").value,d=parseInt($("s_days").value)||0;
 $("s_defval").textContent=$("s_deficit").value;
 if(!(w>0&&h>0&&a>0)){$("calcBox").innerHTML="<span class='muted'>填完身高/体重/年龄后显示计算明细</span>";return;}
 const bmr=Math.round(10*w+6.25*h-5*a+(g==="male"?5:-161));
 const af={0:1.2,1:1.26,2:1.32,3:1.38,4:1.44,5:1.5,6:1.56,7:1.6}[d]||1.35;
 const tdee=Math.round(bmr*af);
 const deficit=parseInt($("s_deficit").value)||0;
 const target=tdee-deficit;
 const floor=g==="male"?1500:1200;
 $("s_deficit").max=Math.max(0,Math.min(750,tdee-floor));
 const row=(l,v)=>"<div class='crow'><span>"+l+"</span><span>"+v+"</span></div>";
 let t=row("基础代谢",Math.round(bmr)+" 千卡")
       +row("不减肥该吃（×"+af+" 活动系数）",tdee+" 千卡")
       +row("减脂缺口","−"+deficit+" 千卡");
 let tot="目标摄入 <b>"+target+"</b> 千卡";
 if(target<floor){tot+=" <span class='warnred'>⚠️ 低于安全下限 "+floor+"</span>";}
 else if(deficit>0){tot+="<span class='muted'> ｜ 预计每周 −"+(deficit*7/7700).toFixed(2)+" kg</span>";}
 t+="<div class='caltotal'>"+tot+"</div>";
 $("calcBox").innerHTML=t;
}
["s_weight","s_height","s_age","s_days"].forEach(id=>$(id).addEventListener("input",updateCalc));
$("s_gender").addEventListener("change",updateCalc);
$("s_deficit").addEventListener("input",updateCalc);
// 点空白处收起滑开的删除区
document.addEventListener("click",e=>{
 if(openId!==null&&!e.target.closest("#list")&&!e.target.closest(".mback")&&!e.target.closest(".modal")){
  closeOpen(null);}
});
refresh();
