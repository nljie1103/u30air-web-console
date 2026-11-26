const byId=id=>document.getElementById(id);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(path,method='GET',data=null){
 const opt={method,credentials:'same-origin',cache:'no-store'};
 if(method==='POST'){opt.headers={'Content-Type':'application/json','X-Desktop-Action':'1'};opt.body=JSON.stringify(data||{});}
 const response=await fetch(path,opt);
 let result;
 try{result=await response.json();}catch{result={error:'服务返回异常'};}
 if(response.status===401){if(!byId('loginForm'))location.reload();throw Error('登录已过期');}
 if(!response.ok)throw Error(result.error||'请求失败');
 return result;
}
const login=byId('loginForm');
if(login){
 login.addEventListener('submit',async event=>{
  event.preventDefault();
  byId('loginError').textContent='';
  const submit=login.querySelector('button[type=submit]');
  submit.disabled=true;
  try{
   await api('/api/login','POST',{password:byId('password').value});
   location.replace('/');
  }catch(err){byId('loginError').textContent=err.message;submit.disabled=false;}
 });
}else{
 const toast=message=>{
  const el=byId('toast');el.textContent=message;el.classList.add('show');
  clearTimeout(window._toastTimeout);window._toastTimeout=setTimeout(()=>el.classList.remove('show'),4500);
 };
 const screen=byId('screen'),empty=byId('emptyState');
 let refreshing=false,frameUrl='',startPoint=null,apps=[],availableVersion='';
 const say=(msg)=>{byId('frameStatus').textContent=msg};
 async function status(){
  try{
   const s=await api('/api/status');
   byId('deviceName').textContent=[s.manufacturer,s.model].filter(Boolean).join(' ')||'Android 设备';
   byId('deviceInfo').textContent='已连接 · Android '+(s.android||'—');
   byId('androidVersion').textContent=s.android||'—';
   byId('architecture').textContent=s.abi||'—';
   byId('hostName').textContent=location.host;
   byId('version').textContent='v'+s.version;
   byId('online').textContent='设备在线';
   byId('liveDot').classList.add('ok');
  }catch(err){
   byId('online').textContent='连接中断';
   byId('liveDot').classList.remove('ok');
  }
 }
 async function capture(){
  if(refreshing||document.hidden)return;
  refreshing=true;
  try{
   const r=await fetch('/api/screen?at='+Date.now(),{cache:'no-store'});
   if(!r.ok)throw Error('当前无法获取屏幕，请确认设备支持截图');
   const blob=await r.blob();
   const u=URL.createObjectURL(blob);
   screen.onload=()=>{
    const prev=frameUrl;frameUrl=u;screen.style.display='block';empty.style.display='none';
    if(prev)URL.revokeObjectURL(prev);
   };
   screen.onerror=()=>{URL.revokeObjectURL(u);};
   screen.src=u;
   say('自动刷新 · 1.5 秒');
  }catch(err){say('画面不可用');empty.style.display='flex';empty.querySelector('strong').textContent=err.message;empty.querySelector('span:last-child').textContent='可尝试唤醒设备或检查系统显示权限';screen.style.display='none';}
  finally{refreshing=false;}
 }
 async function control(action,extra={}){
  try{await api('/api/control','POST',{action,...extra});setTimeout(capture,350);return true;}
  catch(err){toast(err.message);return false;}
 }
 document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>control(b.dataset.action)));
 byId('refresh').addEventListener('click',capture);
 byId('logout').addEventListener('click',async()=>{try{await api('/api/logout','POST');location.replace('/');}catch(err){toast(err.message)}});
 function coordinates(event){
  const rect=screen.getBoundingClientRect();
  return {x:Math.max(0,Math.min(screen.naturalWidth-1,Math.round((event.clientX-rect.left)*screen.naturalWidth/rect.width))),
          y:Math.max(0,Math.min(screen.naturalHeight-1,Math.round((event.clientY-rect.top)*screen.naturalHeight/rect.height)))};
 }
 screen.addEventListener('pointerdown',event=>{
  if(!event.isPrimary)return;
  startPoint=coordinates(event);
  screen.setPointerCapture(event.pointerId);
 });
 screen.addEventListener('pointerup',event=>{
  if(!startPoint)return;
  const end=coordinates(event),start=startPoint;startPoint=null;
  if(Math.hypot(end.x-start.x,end.y-start.y)<20)control('tap',start);
  else control('swipe',{...start,x2:end.x,y2:end.y});
 });
 screen.addEventListener('pointercancel',()=>{startPoint=null;});
 function renderApps(){
  const container=byId('appList');container.replaceChildren();
  const match=byId('searchApps').value.trim().toLowerCase();
  const visible=apps.filter(v=>v.toLowerCase().includes(match));
  byId('appCount').textContent=apps.length+' 个';
  if(!visible.length){const el=document.createElement('div');el.className='muted';el.textContent=apps.length?'没有匹配的应用':'未检测到用户安装的应用';container.append(el);return;}
  for(const pkg of visible){
   const b=document.createElement('button');b.className='app-item';
   const icon=document.createElement('span');icon.className='app-avatar';icon.textContent=pkg.replace(/^com\./,'').slice(0,1).toUpperCase();
   const title=document.createElement('span');title.textContent=pkg;
   b.append(icon,title);
   b.addEventListener('click',async()=>{if(await control('launch',{package:pkg}))toast('已发送启动命令：'+pkg);});
   container.append(b);
  }
 }
 async function loadApps(){
  try{const r=await api('/api/apps');apps=r.packages||[];renderApps();}
  catch(err){byId('appList').textContent='应用列表不可用';}
 }
 byId('searchApps').addEventListener('input',renderApps);
 byId('vncLink').href='http://'+location.hostname+':5800/vnc.html';
 byId('checkUpdate').addEventListener('click',async()=>{
  const button=byId('checkUpdate');button.disabled=true;byId('updatePill').textContent='查询中';
  try{
   const r=await api('/api/update/check');
   byId('updatePill').textContent=r.available?'发现 v'+r.latest:'当前已最新';
   availableVersion=r.available?r.latest:'';
   byId('applyUpdate').disabled=!r.available;
   byId('releaseNote').hidden=false;
   byId('releaseNote').textContent=r.notes||'此版本没有更新说明';
  }catch(err){byId('updatePill').textContent='检查失败';toast(err.message)}
  finally{button.disabled=false;}
 });
 byId('applyUpdate').addEventListener('click',async()=>{
  if(!availableVersion||!confirm('确认安装 v'+availableVersion+'？设备服务将短暂重启。'))return;
  const button=byId('applyUpdate');button.disabled=true;
  toast('正在下载并校验更新包');
  try{await api('/api/update/apply','POST');toast('更新已准备就绪，服务即将重启');setTimeout(()=>location.reload(),14000);}
  catch(err){toast(err.message);button.disabled=false;}
 });
 status();loadApps();capture();
 setInterval(capture,1500);setInterval(status,12000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)capture()});
}
