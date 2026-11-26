const byId=id=>document.getElementById(id);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(path,method='GET',data=null){
 const opt={method,credentials:'same-origin',cache:'no-store'};
 if(method==='POST'){opt.headers={'Content-Type':'application/json','X-Desktop-Action':'1'};opt.body=JSON.stringify(data||{});}
 const response=await fetch(path,opt);
 let result;
 try{result=await response.json();}catch{result={error:'服务返回异常'};}
 if(response.status===401&&!byId('loginForm')){location.reload();throw Error('登录已过期');}
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
 const appDetails=new Map();
 let detailsGeneration=0, renderQueued=false;
 function scheduleAppsRender(){
  if(renderQueued)return;
  renderQueued=true;
  setTimeout(()=>{renderQueued=false;renderApps()},180);
 }
 const formatSize=value=>typeof value==='number'&&value>=0
   ?(value/1073741824).toFixed(value>=1073741824?1:2)+' GB':'—';
 function setMeter(id,value){
  const bar=byId(id);
  bar.style.width=Number.isFinite(value)?Math.max(0,Math.min(100,value)).toFixed(1)+'%':'0%';
 }
 async function refreshMetrics(){
  try{
   const r=await api('/api/metrics');
   const cpu=typeof r.cpuPercent==='number'?r.cpuPercent:null;
   byId('cpuText').textContent=cpu===null?'不可用':cpu.toFixed(1)+'% · '+(r.cpuCores||'—')+' 核';
   setMeter('cpuFill',cpu);
   for(const [prefix,totalKey,usedKey,labelId] of [
    ['ram','memoryTotal','memoryUsed','ramText'],
    ['storage','storageTotal','storageUsed','storageText']
   ]){
    const total=r[totalKey],used=r[usedKey];
    const percent=typeof total==='number'&&total>0&&typeof used==='number'?used/total*100:null;
    byId(labelId).textContent=percent===null?'不可用':
      formatSize(used)+' / '+formatSize(total)+' · '+percent.toFixed(1)+'%';
    setMeter(prefix==='ram'?'ramFill':'storageFill',percent);
   }
   const uptime=typeof r.uptimeSeconds==='number'?r.uptimeSeconds:null;
   const hours=uptime===null?0:Math.floor(uptime/3600);
   byId('uptimeText').textContent=uptime===null?'运行时间：不可用':
      '运行时间：'+Math.floor(hours/24)+' 天 '+hours%24+' 小时';
   byId('metricsNote').textContent='实时';
  }catch(err){byId('metricsNote').textContent='读取失败'}
 }
 const apkToggle=byId('apkToggle'),apkFields=byId('apkFields');
 let apkBusy=false;
 function apkMode(enabled){
  apkToggle.checked=enabled;apkFields.hidden=!enabled;
  byId('apkMode').textContent=enabled?'已启用':'已关闭';
 }
 async function loadAPKConfig(){
  try{apkMode((await api('/api/apk/config')).enabled);apkToggle.disabled=false}
  catch{byId('apkMode').textContent='不可用'}
 }
 apkToggle.addEventListener('change',async()=>{
  const enabled=apkToggle.checked;
  if(enabled&&!confirm('仅在可信局域网启用 APK 安装。确认启用？')){apkMode(false);return}
  apkToggle.disabled=true;
  try{apkMode((await api('/api/apk/config','POST',{enabled})).enabled)}
  catch(e){apkMode(!enabled);toast(e.message)}
  finally{apkToggle.disabled=false}
 });
 async function installAPK(source,file=false){
  if(apkBusy||!apkToggle.checked)return;
  if(!confirm('确认安装可信来源的 APK？不会自动卸载旧应用。'))return;
  apkBusy=true;apkToggle.disabled=true;
  const buttons=['apkDownload','apkChoose'].map(byId);
  buttons.forEach(b=>b.disabled=true);
  const progress=byId('apkProgress');
  progress.textContent='正在准备安装…';
  const poll=setInterval(async()=>{
   try{
    const p=await api('/api/apk/progress');
    if(apkBusy&&p.stage)progress.textContent=p.stage+(p.received?' · '+(p.received/1048576).toFixed(1)+' MiB'+(p.total>0?' / '+(p.total/1048576).toFixed(1)+' MiB':''):'');
   }catch{}
  },800);
  try{
   if(file){
    if(!source.name.toLowerCase().endsWith('.apk')||source.size>128*1048576||!source.size)throw Error('请选择 128 MiB 以内的 APK');
    const response=await fetch('/api/apk/install',{method:'POST',headers:{'Content-Type':'application/vnd.android.package-archive','X-Desktop-Action':'1'},body:source});
    const result=await response.json();if(!response.ok)throw Error(result.error||'安装失败');
   }else await api('/api/apk/install','POST',{url:source});
   progress.textContent='安装完成';toast('APK 安装成功');appDetails.clear();await loadApps();
  }catch(e){progress.textContent=e.message;toast(e.message)}
  finally{clearInterval(poll);apkBusy=false;apkToggle.disabled=false;buttons.forEach(b=>b.disabled=false)}
 }
 byId('apkDownload').addEventListener('click',()=>{
  const url=byId('apkURL').value.trim();
  if(!url.startsWith('https://')){toast('请输入 HTTPS APK 下载链接');return}
  void installAPK(url);
 });
 byId('apkChoose').addEventListener('click',()=>byId('apkFile').click());
 byId('apkFile').addEventListener('change',e=>{const file=e.target.files[0];e.target.value='';if(file)void installAPK(file,true)});
 void loadAPKConfig();
 let passwordWasEnabled=false;
 const authToggle=byId('authToggle'),authPassword=byId('authPassword');
 const syncAuthVisibility=()=>{
  byId('authPasswordGroup').hidden=!authToggle.checked;
  byId('authWarning').hidden=authToggle.checked;
  byId('authHint').textContent=passwordWasEnabled
    ?'已有密码时，留空表示保持原密码'
    :'请输入要使用的密码（例如单个数字也可以）';
 };
 async function refreshAuth(){
  try{
   const config=await api('/api/auth/config');
   passwordWasEnabled=Boolean(config.enabled);
   authToggle.checked=passwordWasEnabled;
   byId('authMode').textContent=passwordWasEnabled?'已启用':'无需登录';
   byId('logout').hidden=!passwordWasEnabled;
   syncAuthVisibility();
  }catch(err){byId('authMode').textContent='读取失败'}
 }
 authToggle.addEventListener('change',syncAuthVisibility);
 byId('authSave').addEventListener('click',async()=>{
  const enabled=authToggle.checked,password=authPassword.value;
  if(enabled&&!password&&!passwordWasEnabled){
   toast('开启登录时请填写一个密码，任意长度均可');
   return;
  }
  if(!enabled&&!window.confirm('关闭密码后，同一个局域网的设备都可以访问并控制本设备。确认关闭吗？'))return;
  const button=byId('authSave');button.disabled=true;
  try{
   await api('/api/auth/config','POST',{enabled,password});
   toast('登录设置已保存，正在重新进入控制台…');
   setTimeout(()=>location.replace('/'),600);
  }catch(err){toast(err.message);button.disabled=false}
 });
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
 document.querySelectorAll('[data-swipe]').forEach(button=>button.addEventListener('click',()=>{
  if(!screen.naturalWidth||!screen.naturalHeight){
   toast('屏幕画面尚未加载，请先刷新画面');
   return;
  }
  const w=screen.naturalWidth,h=screen.naturalHeight;
  const pt=(x,y)=>({x:Math.round(w*x),y:Math.round(h*y)});
  const commands={
   up:{...pt(.5,.82),x2:pt(.5,.21).x,y2:pt(.5,.21).y},
   down:{...pt(.5,.20),x2:pt(.5,.82).x,y2:pt(.5,.82).y},
   left:{...pt(.82,.52),x2:pt(.18,.52).x,y2:pt(.18,.52).y},
   right:{...pt(.18,.52),x2:pt(.82,.52).x,y2:pt(.82,.52).y},
  };
  const swipe=commands[button.dataset.swipe];
  if(swipe)void control('swipe',swipe);
 }));
 const expandButton=byId('expandDesktop');
 expandButton.addEventListener('click',async()=>{
  const el=byId('desktopCol');
  try{
   if(document.fullscreenElement)await document.exitFullscreen();
   else if(el.requestFullscreen)await el.requestFullscreen();
   else throw Error('当前浏览器不支持全屏模式');
  }catch(err){toast('无法进入全屏：'+err.message)}
 });
 document.addEventListener('fullscreenchange',()=>{
  expandButton.textContent=document.fullscreenElement?'退出全屏':'全屏控制';
 });
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
  const visible=apps.filter(pkg=>{
   const label=appDetails.get(pkg)?.label||pkg;
   return pkg.toLowerCase().includes(match)||label.toLowerCase().includes(match);
  });
  byId('appCount').textContent=apps.length+' 个';
  if(!visible.length){
   const el=document.createElement('div');el.className='muted';
   el.textContent=apps.length?'没有匹配的应用':'未检测到用户安装的应用';
   container.append(el);return;
  }
  for(const pkg of visible){
   const meta=appDetails.get(pkg);
   const label=meta?.label||pkg;
   const b=document.createElement('button');b.className='app-item';
   b.type='button';b.title='打开 '+label;b.setAttribute('aria-label','打开 '+label);
   const icon=document.createElement('span');icon.className='app-avatar';
   icon.textContent=label.slice(0,1).toUpperCase();
   if(meta?.hasIcon){
    const img=document.createElement('img');
    img.className='app-icon';img.alt='';img.loading='lazy';
    img.src='/api/app-icon?package='+encodeURIComponent(pkg)+'&v='+detailsGeneration;
    img.onerror=()=>{img.remove();icon.textContent=label.slice(0,1).toUpperCase();};
    icon.replaceChildren(img);
   }
   const copy=document.createElement('span');copy.className='app-copy';
   const title=document.createElement('strong');title.className='app-title';title.textContent=label;
   copy.append(title);
   if(label!==pkg){
    const sub=document.createElement('small');sub.className='app-package';sub.textContent=pkg;
    copy.append(sub);
   }
   b.append(icon,copy);
   b.addEventListener('click',async()=>{
    if(await control('launch',{package:pkg}))toast('已发送启动命令：'+label);
   });
   container.append(b);
  }
 }
 async function enrichApps(list){
  const generation=++detailsGeneration;
  let pos=0;
  await Promise.all(Array.from({length:3},async()=>{
   while(generation===detailsGeneration){
    const pkg=list[pos++];
    if(!pkg)return;
    if(appDetails.has(pkg))continue;
    try{
     const meta=await api('/api/app-info?package='+encodeURIComponent(pkg));
     if(generation!==detailsGeneration)return;
     if(meta.package===pkg){
      appDetails.set(pkg,meta);
      scheduleAppsRender();
     }
    }catch{
     // Some APK files or labels may not be accessible as the shell user.
     // Preserve the existing package-name listing as a safe fallback.
    }
   }
  }));
 }
 async function loadApps(){
  try{
   const r=await api('/api/apps');
   apps=(r.packages||[]).filter(pkg=>typeof pkg==='string');
   for(const pkg of appDetails.keys())if(!apps.includes(pkg)||!appDetails.get(pkg)?.hasIcon)appDetails.delete(pkg);
   renderApps();void enrichApps(apps);
  }catch(err){
   byId('appList').textContent='应用列表不可用：'+err.message;
  }
 }
 byId('searchApps').addEventListener('input',renderApps);
 async function probeVnc(){
  const button=byId('probeVnc'),link=byId('vncLink'),status=byId('vncStatus');
  button.disabled=true;
  status.textContent='正在检查独立 noVNC 是否可用…';
  link.hidden=true;link.removeAttribute('href');
  try{
   const result=await api('/api/novnc/status');
   if(result.available && typeof result.url==='string' &&
      result.url === 'http://'+location.hostname+':5800/vnc.html'){
    link.href=result.url;link.hidden=false;
    status.textContent='检测到可访问的 noVNC 页面，可在新标签打开。';
   }else{
    status.textContent=result.reason||'未检测到独立 noVNC 服务；请继续使用上方的内置远程控制。';
   }
  }catch(err){
   status.textContent='noVNC 检测不可用：'+err.message;
  }finally{button.disabled=false}
 }
 byId('probeVnc').addEventListener('click',()=>{void probeVnc()});
 async function powerAction(action,label){
  const answer=window.prompt(
   '危险操作：'+label+'设备会中断当前远程连接。\nAndroid 可能要求 Root 或特殊权限。\n请输入“'+label+'”确认：','');
  if(answer===null)return;
  if(answer!==label){toast('已取消：输入内容与“'+label+'”不一致');return}
  try{
   await api('/api/control','POST',{action,confirm:label});
   toast('已发送'+label+'命令，请观察设备是否响应');
  }catch(err){
   if(err instanceof TypeError){
    toast('与设备连接已断开，无法确认'+label+'是否成功执行');
   }else toast(err.message);
  }
 }
 byId('rebootDevice').addEventListener('click',()=>{void powerAction('reboot','重启')});
 byId('shutdownDevice').addEventListener('click',()=>{void powerAction('shutdown','关机')});
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
 status();loadApps();capture();void probeVnc();void refreshAuth();void refreshMetrics();
 setInterval(capture,1500);setInterval(status,12000);setInterval(refreshMetrics,5000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)capture()});
}
