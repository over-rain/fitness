
const $=id=>document.getElementById(id);
window.onerror=function(m){try{toast("页面错误:"+m);}catch(_){}};
let user=localStorage.getItem("fg_user")||"beifeng";
function paintSeg(){$("u1").classList.toggle("on",user==="beifeng");$("u2").classList.toggle("on",user==="gagayouna");}
$("u1").textContent="🧑 邶风";$("u2").textContent="👩 gagayouna";
$("u1").onclick=()=>{user="beifeng";localStorage.setItem("fg_user",user);paintSeg();clearReply();refresh();if($("mback").style.display==="flex")loadProfile();};
$("u2").onclick=()=>{user="gagayouna";localStorage.setItem("fg_user",user);paintSeg();clearReply();refresh();if($("mback").style.display==="flex")loadProfile();};
function clearReply(){const el=$("reply");el.className="";el.textContent="";}
function showBack(id){const el=$(id);el.style.display="flex";el.classList.remove("closing");}
function hideBack(id){const el=$(id);el.classList.add("closing");
 setTimeout(()=>{el.style.display="none";el.classList.remove("closing");},240);}
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
async function loadProfile(){
 try{const p=await api("/api/profile?user="+user);
  $("s_name").value=p.display_name||"";$("s_gender").value=p.gender||"male";
  $("s_age").value=p.age??"";$("s_height").value=p.height_cm??"";
  $("s_weight").value=p.weight_kg??"";$("s_targetw").value=p.target_weight_kg??"";
  $("s_days").value=p.training_days??4;
  const t=p.targets||{};
  $("s_hint").textContent="当前热量线 "+(t.daily_kcal??"?")+" kcal / 蛋白 "+(t.protein_g??"?")+"g（"+(t.calculated_at||"")+" 算）";
 }catch(e){toast("读取档案失败："+e.message);}
}
$("s_save").onclick=async()=>{
 try{const j=await api("/api/profile",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user,display_name:$("s_name").value,gender:$("s_gender").value,
   age:$("s_age").value,height_cm:$("s_height").value,weight_kg:$("s_weight").value,
   target_weight_kg:$("s_targetw").value,training_days:$("s_days").value})});
  const btn=user==="beifeng"?$("u1"):$("u2");
  btn.textContent=(user==="beifeng"?"🧑 ":"👩 ")+($("s_name").value.trim()||user);
  toast("已保存，热量线 "+j.targets.daily_kcal+" kcal / 蛋白 "+j.targets.protein_g+"g");
  $("s_hint").textContent="当前热量线 "+j.targets.daily_kcal+" kcal / 蛋白 "+j.targets.protein_g+"g（刚重算）";
  refresh();
 }catch(e){toast("保存失败："+e.message);}
};
paintSeg();
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
async function api(path,opts,tmo){const ctl=("AbortController"in window)?new AbortController():null;
 const to=ctl?setTimeout(()=>ctl.abort(),tmo||180000):null;
 try{const r=await fetch(path,Object.assign({},opts,ctl?{signal:ctl.signal}:{}));
  let j=null;try{j=await r.json()}catch(_){}
  if(!r.ok)throw new Error((j&&j.error)||("HTTP "+r.status));return j;}
 finally{if(to)clearTimeout(to);}}
let busy=false,timer=null;
function setLoading(msg){busy=true;$("bPhoto").disabled=true;$("bSend").disabled=true;
 const el=$("reply"),t0=Date.now();el.className="wait";
 el.innerHTML="<span class='spin'></span>"+msg+" <b id='el'></b>";
 timer=setInterval(()=>{const s=Math.round((Date.now()-t0)/1000);
  $("el").textContent=s+"s"+(s>12?" · 大图高峰会慢些":"");},500);}
function done(){busy=false;$("bPhoto").disabled=false;$("bSend").disabled=false;if(timer)clearInterval(timer);}
function showOk(t){done();const el=$("reply");el.className="ok";el.textContent=t;}
function showErr(t){done();const el=$("reply");el.className="err";el.textContent="❌ "+t;}
function toast(t){const el=$("toast");el.textContent=t;el.classList.add("show");
 setTimeout(()=>el.classList.remove("show"),2200);}
const MEAL_ORD={"早餐":0,"午餐":1,"晚餐":2,"加餐":3};
async function refresh(){
 try{const j=await api("/api/today?user="+user);
  $("remain").textContent=j.remaining;
  const pct=Math.min(100,j.target?j.eaten/j.target*100:0);
  const bar=$("bar");bar.classList.toggle("warn",pct>85);
  bar.firstElementChild.style.width=pct+"%";
  $("sumline").textContent="已吃 "+j.eaten+" / "+j.target+" kcal ｜ 蛋白 "+j.protein+" / "+j.protein_target+" g";
  const d=$("dinner");d.textContent=j.dinner_tip?("🌙 "+j.dinner_tip):"";d.classList.toggle("show",!!j.dinner_tip);
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
     (r.photo?"<img class='thumb' src='/photo/"+r.id+"' alt=''>":"<div class='thumb ph' role='img' aria-label='暂无照片'>" +
     "<svg width='26' height='26' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' aria-hidden='true'><path d='M4 13h16'/><path d='M5 13a7 7 0 0 0 14 0z'/></svg></div>")+
     "<div class='mname'>"+esc(r.food)+"<div class='msub'>"+
     [r.portion,r.note].filter(Boolean).map(esc).join(" · ")+"</div></div>"+
     "<div class='kcell'><b>"+r.kcal+"</b> 千卡<span class='chev'>›</span></div></div></div>";
   }
   h+="</div>";
  }
  $("list").innerHTML=h||"<div class='muted' style='padding:8px 0'>还没有记录，开吃吧 🍚</div>";
  bindSwipe($("list"));
 }catch(e){toast("加载失败："+e.message);}
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
   body:JSON.stringify({user:user,text:t})},240000);
  if(j.reply&&j.reply.indexOf("没识别出")>=0){showErr(j.reply);}else{showOk(j.reply);bump();refresh();}
  $("text").value="";
 }catch(e){showErr(friendly(e.message));}
}
function friendly(m){
 if(/timed out|abort/i.test(m))return "网关高峰无响应（已等待超时）。稍后重试；长语音建议拆成按餐短句，更快更稳";
 if(/api_key/i.test(m))return m;
 return m;
}
$("text").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();sendText();}});
$("bSend").onclick=sendText;
$("bPhoto").onclick=()=>$("photo").click();
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
$("avBack").onclick=closeAv;
$("avMeal").onclick=e=>{e.stopPropagation();
 const m=$("avmenu");m.style.display=m.style.display==="block"?"none":"block";};
$("avmenu").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
 avMeal=b.dataset.m;renderAv();$("avmenu").style.display="none";});
document.addEventListener("click",e=>{if(!e.target.closest("#avmenu")&&!e.target.closest("#avMeal"))$("avmenu").style.display="none";});
$("avSave").onclick=async()=>{
 if(avBusy||!avItems.length)return;avBusy=true;
 try{
  await api("/api/save",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,meal_type:avMeal,items:avItems,image:avB64})});
  const kcal=avItems.reduce((s,i)=>s+(i.kcal||0),0);
  closeAv();toast((kcal<0?"已扣回 ":"已记录 ")+kcal+" 千卡");refresh();
 }catch(e){toast("保存失败："+e.message);}
 avBusy=false;
};
let fixB64=null;
$("avFix").onclick=()=>{if(avBusy||!avB64)return;
 fixB64=null;$("fixText").value="";$("fixCnt").textContent="0/200";
 $("fixThumb").style.display="none";$("fixPhotoHint").textContent="可选：拍剩余的盘子，AI 按图扣减";
 $("fixErr").classList.remove("show");
 showBack("fixBack");$("fixText").focus();};
$("fixClose").onclick=()=>hideBack("fixBack");
$("fixBack").onclick=e=>{if(e.target.id==="fixBack")hideBack("fixBack");};
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
$("photo").addEventListener("change",async e=>{
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
 }catch(err){avDone();toast("识别失败："+err.message);closeAv();}
 avBusyUI(false);avBusy=false;
});
// ---- 编辑抽屉 & 删除确认 ----
let editId0=null,editB64=null,editBusy=false,delId0=null;
function openEdit(id){
 const r=_recs[id];if(!r)return;editId0=id;editB64=null;
 if(r.photo){$("eThumb").src="/photo/"+id;$("eThumb").style.display="block";$("eThumbPh").style.display="none";}
 else{$("eThumb").style.display="none";$("eThumbPh").style.display="flex";}
 $("eFood").value=r.food;$("ePortion").value=r.portion||"";
 $("eKcal").value=r.kcal;$("eProtein").value=(r.protein_g==null?"":r.protein_g);
 $("ePills").innerHTML=MEALS.map(m=>"<button data-m='"+m+"' class='"+(m===r.meal_type?"on":"")+"'>"+m+"</button>").join("");
 $("ePills").querySelectorAll("button").forEach(b=>b.onclick=()=>{
  $("ePills").querySelectorAll("button").forEach(x=>x.classList.remove("on"));b.classList.add("on");});
 showBack("editBack");requestAnimationFrame(()=>$("editBack").classList.add("open"));
}
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
    meal_type:meal,image:editB64||undefined})},60000);
  closeEdit();bump();refresh();
 }catch(e){toast("保存失败："+e.message);}
 $("eSave").disabled=false;$("eSave").textContent="保存修改";editBusy=false;
};
async function delId(id){try{await api("/api/correct",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({id:id,action:"delete"})});toast("已删除");bump();refresh();}catch(e){toast("删除失败："+e.message);}}
let clearing=false;
$("clearBtn").onclick=()=>showBack("clearBack");
$("cCancel").onclick=()=>hideBack("clearBack");
$("cOk").onclick=async()=>{
 hideBack("clearBack");if(clearing)return;clearing=true;
 try{const j=await api("/api/clear",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user})});toast("已清空 "+j.cleared+" 条");bump();refresh();}
 catch(e){toast("清空失败："+e.message);}
 clearing=false;
};
function bump(){const el=$("remain");el.classList.remove("bump");void el.offsetWidth;el.classList.add("bump");}
// 点空白处收起滑开的删除区
document.addEventListener("click",e=>{
 if(openId!==null&&!e.target.closest("#list")&&!e.target.closest(".mback")&&!e.target.closest(".modal")){
  closeOpen(null);}
});
refresh();
