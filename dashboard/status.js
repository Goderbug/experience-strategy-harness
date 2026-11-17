(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const txt = value => typeof value === 'string' ? value : '';
  const list = value => Array.isArray(value) ? value : [];
  const el = (tag, className = '', value = '') => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== '') node.textContent = String(value);
    return node;
  };
  const names = {
    stage: {create:'设计创作',artifact_check:'产物检查',user_validation:'用户验证',legacy_review:'策略评审'},
    phase: {candidate_ready:'候选已就绪',waiting_evidence:'等待证据',needs_owner:'等待负责人',active:'处理中',
      verified:'产物已核验',decided:'已记录裁决',superseded:'已由新案接替'},
    role: {critic:'设计质评',execution:'设计执行',measurement:'产物检查',strategist:'策略制定',verifier:'验证',
      user_evidence:'用户证据',judge:'设计裁决',resume:'恢复案件'},
    step: {done:'已交付',current:'当前角色',upcoming:'待进行',skipped:'已跳过'},
    evidence: {disabled:'此阶段关闭',enabled:'已启用',active:'已启用',not_applicable:'不适用',unknown:'未记录'},
    outcome: {unverified:'未验证',unknown:'未记录',not_assessed:'未评估',observed_supports:'本案观察支持该主张',observed_refutes:'本案观察反驳该主张'},
    decision: {ready:'候选就绪',rework:'退回设计执行',keep:'维持方案',revise:'建议修订',withdraw:'撤回方案',defer:'暂缓判断',escalate:'交负责人判断'},
    integrity: {matches:'文件指纹一致',changed:'文件有变化',unreadable:'无法读取',not_submitted:'尚无交付'},
    concern: {open:'开放',resolved:'已解决',deferred:'暂缓',dismissed:'已搁置','in-progress':'处理中','awaiting-validation':'待验证'},
    detail: {change:'设计改动',tradeoff:'取舍',acceptance:'验收条件',review_steps:'检查方法',limitations:'适用边界',checks:'检查项',
      outcome:'结果',next_trigger:'再评条件',critic_response:'回应异议',rationale:'依据',assumption:'假设',intent:'意图',options:'备选方案',
      proposal:'提案',reopen_if:'重开条件',consequence:'影响',objection:'异议',reason:'理由',check:'检查',method:'方法',observation:'观察',
      scope:'范围',provenance:'来源',finding:'发现',task:'任务',participant_scope:'参与者范围'}
  };
  const name = (group, value, fallback = '未记录') => Object.hasOwn(names[group], value) ? names[group][value] : txt(value) || fallback;
  const naturalNumber = value => Number.isInteger(value) && value >= 0;
  const formatTime = value => {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  };
  const formatDate = value => {
    if (!formatTime(value)) return '';
    return new Date(value).toLocaleString('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  };
  const valid = data => data && Array.isArray(data.projects) && data.projects.every(project =>
    project && typeof project.id === 'string' && Array.isArray(project.cases));
  let boot;
  try { boot = JSON.parse($('boot').textContent); }
  catch { $('main').append(el('p','alert','无法读取状态数据。')); return; }
  if (!valid(boot.snapshot)) { $('main').append(el('p','alert','项目状态的格式无法读取。')); return; }
  let snapshot = boot.snapshot;
  const live = boot.mode === 'live';
  const params = new URLSearchParams(location.hash.slice(1));
  let projectId = params.get('project'), caseId = params.get('case');
  let loading = false, disconnected = false, timer;
  const expanded = new Map();
  const lastVerified = new Map();
  const scopedKey = (...ids) => JSON.stringify(ids);
  const savedKey = (project, item) => scopedKey(project.id,item.id,item.revision);
  function rememberVerification(data) {
    for (const project of data.projects) for (const item of list(project.cases)) {
      if (typeof item.stale_snapshot !== 'boolean' && !item.integrity) { lastVerified.delete(savedKey(project,item)); continue; }
      lastVerified.set(savedKey(project,item), {
        at:data.generated_at, integrity:item.integrity, stale_snapshot:item.stale_snapshot, stale_concern:item.stale_concern
      });
    }
  }
  if (!live) rememberVerification(snapshot);
  function selection() {
    const project = snapshot.projects.find(p => p.id === projectId) || snapshot.projects[0];
    const item = project && (project.cases.find(c => c.id === caseId) || project.cases[0]);
    projectId = project?.id || ''; caseId = item?.id || '';
    return {project,item};
  }
  function closeNavigation() {
    document.body.classList.remove('nav-open');
    $('mobile-nav').setAttribute('aria-expanded','false');
  }
  function choose(nextProject,nextCase) {
    projectId = nextProject; caseId = nextCase || '';
    const {item} = selection();
    const hash = new URLSearchParams({project:projectId});
    if (item) hash.set('case',item.id);
    try { history.replaceState(null,'','#' + hash.toString()); } catch { /* Some offline readers disable history. */ }
    closeNavigation(); render();
    $('main').focus({preventScroll:true});
  }
  function projectNavigation(activeProject,activeCase) {
    const nav = $('project-nav');
    nav.replaceChildren();
    $('project-count').textContent = snapshot.projects.length;
    for (const project of snapshot.projects) {
      const selected = project.id === activeProject?.id;
      const group = el('div','nav-project');
      const btn = el('button','project-button' + (selected ? ' selected' : ''));
      btn.type = 'button'; btn.dataset.project = project.id;
      btn.setAttribute('aria-expanded',String(selected));
      const label = el('span','project-label',project.name || project.id);
      let note = project.cases.length + ' 个案件';
      if (!project.cases.length && list(project.concerns).length) note=list(project.concerns).length+' 条项目问题';
      if (project.cases.length === 1) note = name('phase',project.cases[0].phase);
      if (project.status === 'error') note = '状态读取失败';
      if (project.status === 'partial') note = '部分数据可用';
      if (project.status === 'not_initialized') note = '尚未初始化';
      label.append(el('small','',note));
      const glyph = el('span','project-glyph'); glyph.setAttribute('aria-hidden','true');
      btn.append(glyph,label); btn.addEventListener('click',() => choose(project.id, selected ? caseId : ''));
      group.append(btn);
      if (selected && project.cases.length) {
        const cases = el('ul','case-list');
        for (const item of project.cases) {
          const active = item.id === activeCase?.id;
          const row = el('li'), cb = el('button','case-button' + (active ? ' selected' : ''),item.id);
          cb.type = 'button'; cb.dataset.case = item.id;
          cb.title = item.goal || item.claim || item.id;
          if (active) cb.setAttribute('aria-current','true');
          cb.addEventListener('click',() => choose(project.id,item.id));
          row.append(cb); cases.append(row);
        }
        group.append(cases);
      }
      nav.append(group);
    }
  }
  function observeOpen(details,key,defaultOpen) {
    details.open = expanded.has(key) ? expanded.get(key) : defaultOpen;
    details.addEventListener('toggle',() => { if (details.isConnected) expanded.set(key,details.open); });
  }
  function heading(title,note) {
    const head = el('div','card-head');
    head.append(el('h2','',title));
    if (note) head.append(el('span','muted',note));
    return head;
  }
  function fact(label,value,tone) {
    const row = el('div','status-fact'), answer = el('dd','',value);
    if (tone) answer.dataset.tone = tone;
    row.append(el('dt','',label),answer); return row;
  }
  async function copyPath(path,button) {
    let copied = false;
    try {
      if (navigator.clipboard) { await navigator.clipboard.writeText(path); copied = true; }
    } catch { /* Local file pages can lack clipboard access. */ }
    if (!copied) {
      const range = document.createRange();
      range.selectNodeContents(button.previousElementSibling);
      const selected = window.getSelection();
      selected.removeAllRanges(); selected.addRange(range);
      try { copied = document.execCommand('copy'); } catch { /* Selection remains available for manual copy. */ }
    }
    button.textContent = copied ? '已复制' : '已选中';
    $('feedback').textContent = copied ? '已复制项目相对路径。' : '已选中路径，可用系统复制快捷键。';
  }
  function taskHero(project,item) {
    const hero = el('section','hero'), head = el('div','hero-top');
    head.append(el('span','stage-tag' + (item.mode === 'fixture' ? ' fixture' : ''),name('stage',item.stage) + (item.mode === 'fixture' ? ' · 模拟' : '')),
      el('span','case-id',item.id));
    const core = el('div','hero-content'), lead = el('div');
    const title = el('h1','',name('phase',item.phase));
    title.id = 'phase-title';
    lead.append(title,el('p','hero-goal',item.goal || item.claim || project.goal || '没有登记目标。'));
    const next = el('div','hero-next');
    let label = '当前角色', value = name('role',item.next_role,'无待执行角色');
    if (item.phase === 'candidate_ready') {
      label='用户效果'; value=name('outcome',item.user_outcome);
    } else if (item.phase === 'waiting_evidence') {
      label='继续条件'; value=item.next_trigger || '有新证据后可恢复案件';
    } else if (item.phase === 'needs_owner') {
      label='接手方'; value=item.next_trigger || '需要项目负责人判断';
    } else if (item.phase === 'superseded') {
      label='后续案件'; value=item.superseded_by || '已由新案接替';
    } else if (!item.next_role && item.next_trigger) {
      label='再评条件'; value=item.next_trigger;
    }
    next.append(el('small','',label),el('p','',value)); core.append(lead,next);
    const flow = el('div','steps-wrap'), st = el('div','section-line');
    const steps = list(item.steps);
    st.append(el('h2','','角色进度'));
    if (steps.length) st.append(el('span','fraction',steps.filter(node=>node.status==='done').length+' / '+steps.length+' 已交付'));
    flow.append(st);
    const seq = el('ol','steps'); seq.id='role-steps';
    seq.setAttribute('aria-label','案件的角色进度');
    for (const step of steps) {
      const line=el('li'), node=el('span','step-node ' + (['done','current','upcoming'].includes(step.status)?step.status:''),step.status==='done'?'✓':'');
      node.setAttribute('aria-hidden','true');
      if (step.status === 'current') line.setAttribute('aria-current','step');
      const state=item.phase==='superseded' && step.status!=='done' ? '未执行' : name('step',step.status);
      line.append(node,el('span','step-title',name('role',step.role)),el('span','step-state',state)); seq.append(line);
    }
    if (!steps.length) seq.append(el('li','muted','没有可用的角色记录。'));
    flow.append(seq); hero.append(head,core,flow); return hero;
  }
  function deliveries(project,item) {
    const card=el('section','card');const entries=list(item.history);
    card.append(heading('角色交付',entries.length+' 条记录'));
    const logs=el('ol','history'); logs.id='history-list';
    for (const record of entries.slice().reverse()) {
      const row=el('li','history-item'), details=el('details'), sum=el('summary');
      const rev=naturalNumber(record.revision)?'r'+record.revision:'';
      const key=scopedKey(project.id,item.id,'log',record.revision,record.role);
      const title=el('div','log-heading');
      title.append(el('strong','',name('role',record.role)),el('span','rev',[rev,formatDate(record.recorded_at)].filter(Boolean).join(' · ')));
      const text=el('div');text.append(title);
      if (record.summary) {
        const checks=list(record.details).filter(pair=>Array.isArray(pair) && /^pass · /.test(pair[1]));
        const summary=record.role==='measurement' && record.summary==='ready' && checks.length ?
          checks.length+' 项产物检查通过' : name('decision',record.summary);
        text.append(el('p','log-summary',summary));
      }
      const fileCount=list(record.refs).length;
      if (fileCount) title.append(el('small','file-count',fileCount+' 个文件'));
      sum.append(text); sum.dataset.history=key;
      const body=el('div','log-body');
      for (const pair of list(record.details)) {
        if (!Array.isArray(pair) || pair.length < 2 || !pair[1]) continue;
        const dl=el('dl','log-pair');
        const observed=String(pair[1]).replace(/^pass · /,'通过 · ').replace(/^fail · /,'需返工 · ');
        dl.append(el('dt','',name('detail',pair[0])),el('dd','',name('decision',observed))); body.append(dl);
      }
      const refs=list(record.refs);
      if (refs.length) {
        body.append(el('div','sub-label','相关文件 · 项目相对路径'));
        const ul=el('ul','evidence-list');
        for (const ref of refs) {
          if (!ref.path) continue;
          const li=el('li'),path=el('code','ref-path',ref.path),copy=el('button','copy-path','复制');
          copy.type='button';copy.setAttribute('aria-label','复制路径 '+ref.path);
          copy.addEventListener('click',()=>copyPath(ref.path,copy));li.append(path,copy);ul.append(li);
        }
        body.append(ul);
      }
      if (!body.children.length) body.append(el('p','muted','此交付没有额外明细。'));
      details.append(sum,body);observeOpen(details,key,false);row.append(details);logs.append(row);
    }
    if (!entries.length) logs.append(el('li','empty','尚无角色提交。'));
    card.append(logs);return card;
  }
  function projectStatus(project,item) {
    const card=el('section','card');card.append(heading('状态核对'));
    const facts=el('dl'),runtime=project.runtime || {};
    const readable = !['error','partial'].includes(project.status);
    const pending=naturalNumber(runtime.pending_count)?runtime.pending_count+' 项':readable && runtime.enabled===false?'未启用':'未知';
    facts.append(fact('宿主待检',pending,runtime.pending_count>0?'warning':''));
    if (runtime.latest_event) facts.append(fact('宿主最后事件',formatDate(runtime.latest_event)||'时间未知'));
    if (item) {
      facts.append(fact('用户证据',name('evidence',item.user_evidence)),fact('用户效果',name('outcome',item.user_outcome)));
      const saved=lastVerified.get(savedKey(project,item));
      const integrity=item.integrity || saved?.integrity;
      if (item.stage==='create') {
        facts.append(fact('候选文件',name('integrity',integrity?.candidate,'未核对'),integrity?.candidate==='matches'?'positive':''),
          fact('检查记录',name('integrity',integrity?.check_record,'未核对'),integrity?.check_record==='matches'?'positive':''));
      }
      const stale=typeof item.stale_snapshot === 'boolean'?item.stale_snapshot:saved?.stale_snapshot;
      facts.append(fact('产品基线',stale===true?'已变化':stale===false?'与开案时一致':'未核对',stale===true?'warning':''));
      if (item.stale_concern === true) facts.append(fact('关联问题','记录有变化','warning'));
      if (saved?.at) facts.append(fact('最近文件核对',formatDate(saved.at)));
    }
    card.append(facts);return card;
  }
  function caseScope(project,item) {
    const card=el('section','card secondary-card'),details=el('details'),summary=el('summary','','案件依据');
    summary.dataset.fold='scope';const inside=el('div');
    if (item.claim) inside.append(el('p','log-summary',item.claim));
    if (item.updated_at) inside.append(el('p','origin','案件更新于 '+formatDate(item.updated_at)));
    if (naturalNumber(item.revision)) inside.append(el('p','origin','案件版本 r'+item.revision));
    details.append(summary,inside);observeOpen(details,scopedKey(project.id,item.id,'basis'),false);card.append(details);return card;
  }
  function projectScope(project) {
    const card=el('section','card secondary-card'),details=el('details'),concerns=list(project.concerns);
    const incomplete=['error','partial','not_initialized'].includes(project.status);
    const count=incomplete ? (concerns.length?'已读取 '+concerns.length+' 条':'未确认') : concerns.length;
    const title=el('summary','','项目问题 · '+count);title.dataset.fold='concerns';
    const inside=el('div');
    if (concerns.length) {
      const ul=el('ul','concerns');
      for (const problem of concerns) {
        const li=el('li','',problem.title||problem.id||'未命名问题');
        li.append(el('small','',[problem.id,name('concern',problem.status)].filter(Boolean).join(' · ')));ul.append(li);
      }
      inside.append(ul);
    } else inside.append(el('p','muted',project.status==='ready'?'没有登记项目问题。':'没有可显示的问题记录。'));
    if (project.root) inside.append(el('p','origin','项目路径 · '+project.root));
    details.append(title,inside);observeOpen(details,scopedKey(project.id,'project-concerns'),false);card.append(details);return card;
  }
  function render() {
    const active=document.activeElement;
    const focusId=active?.id;
    const focusData=active?.dataset?Object.entries(active.dataset).filter(([k])=>['history','fold','project','case'].includes(k))[0]:null;
    const {project,item}=selection(); projectNavigation(project,item);
    const main=$('main');main.replaceChildren();
    if (!project) { main.append(el('p','empty','尚未传入可显示的项目。'));return; }
    const crumbs=el('div','eyebrow');crumbs.append(el('strong','',project.name||project.id),el('span','slash','/'),el('span','',item?'案件状态':'项目状态'));
    main.append(crumbs);
    if (project.error || ['error','partial'].includes(project.status)) {
      main.append(el('p','alert',project.error || (project.status==='partial'?'部分状态暂时无法读取。':'项目状态读取失败。')));
    }
    const grid=el('div','detail-grid'),left=el('div'),right=el('div');
    if (item) { main.append(taskHero(project,item));left.append(deliveries(project,item));right.append(projectStatus(project,item),caseScope(project,item)); }
    else {
      const card=el('section','card project-empty');
      const label=project.status==='not_initialized'?'项目尚未初始化':project.status==='error'?'案件状态不可用':project.status==='partial'?'部分状态可用':'尚无角色案件';
      const h=el('h1','',label);h.id='phase-title';card.append(h);
      if (project.goal) card.append(el('p','hero-goal',project.goal));
      left.append(card);right.append(projectStatus(project,null));
    }
    right.append(projectScope(project));grid.append(left,right);main.append(grid);
    if (focusData && !active.isConnected) {
      const [key,value]=focusData;
      const match=Array.from(document.querySelectorAll('[data-'+key+']')).find(n=>n.dataset[key]===value);
      if (match) match.focus({preventScroll:true});
    } else if (focusId && !active.isConnected) $(focusId)?.focus({preventScroll:true});
  }
  function syncStatus() {
    const state=$('connection');
    state.textContent=live?(disconnected?'连接中断':loading?'正在刷新':'实时视图'):'导出快照';
    state.dataset.state=disconnected?'error':live?'live':'snapshot';
    const time=$('updated');time.textContent=formatTime(snapshot.generated_at);
    time.title=(live?'最近读取时间 · ':'快照生成时间 · ')+formatDate(snapshot.generated_at);
    if (snapshot.generated_at) time.dateTime=snapshot.generated_at;
    $('refresh').hidden=!live;$('refresh').disabled=loading;
  }
  function planPoll() {
    if (live) timer=setTimeout(()=>refresh(false),Math.max(1000,Number(boot.interval_ms)||5000));
  }
  async function refresh(verify) {
    if (loading||!live) return;
    clearTimeout(timer);loading=true;syncStatus();
    const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),15000);
    try {
      const res=await fetch(verify?'./api/status?verify=1':'./api/status',{cache:'no-store',signal:abort.signal});
      if (!res.ok) throw new Error('status');
      const body=await res.json(),next=body.snapshot||body;
      if (!valid(next)) throw new Error('payload');
      const changed=JSON.stringify(next.projects)!==JSON.stringify(snapshot.projects);
      snapshot=next;disconnected=false;$('notice').textContent='';
      if (verify) {rememberVerification(next);$('feedback').textContent='已刷新案件与文件核对结果。';}
      if (changed||verify) render();
    } catch {
      disconnected=true;$('notice').textContent='无法连接本地状态服务。当前保留上次成功读取的数据，连接恢复后会自动更新。';
    } finally {clearTimeout(timeout);loading=false;syncStatus();planPoll();}
  }
  $('refresh').addEventListener('click',()=>refresh(true));
  $('mobile-nav').addEventListener('click',()=>{
    const open=document.body.classList.toggle('nav-open');$('mobile-nav').setAttribute('aria-expanded',String(open));
    if (open) $('project-nav').querySelector('.project-button.selected,.project-button')?.focus();
  });
  document.addEventListener('keydown',event=>{
    if (event.key==='Escape'&&document.body.classList.contains('nav-open')) {closeNavigation();$('mobile-nav').focus();}
  });
  window.addEventListener('hashchange',()=>{
    const current=new URLSearchParams(location.hash.slice(1));projectId=current.get('project');caseId=current.get('case');render();
  });
  render();syncStatus();planPoll();
})();
