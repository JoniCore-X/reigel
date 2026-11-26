'use strict';

// Team workspace extensions. All records and actions come from authenticated APIs.
const taskTypes = {call:'Llamar',send_info:'Enviar información',confirm_appointment:'Confirmar cita',prepare_orientation:'Preparar orientación',follow_up:'Dar seguimiento',review_proposal:'Revisar propuesta',referral:'Contactar recomendación',documents:'Gestionar documentación'};
const taskStatuses = {pending:'Pendiente',completed:'Realizada',cancelled:'Cancelada'};
const priorities = {low:'Baja',normal:'Normal',high:'Alta'};
const interactionTypes = {call:'Llamada registrada',message:'Mensaje registrado',meeting:'Reunión registrada',note:'Nota interna'};
let leadSearchTimer;
let leadSearchSequence = 0;

function options(map,selected='',includeAll='') {
  return `${includeAll?`<option value="">${esc(includeAll)}</option>`:''}${Object.entries(map).map(([value,label])=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(label)}</option>`).join('')}`;
}
function personOptions(selected='',all='Sin asignar') {
  return `<option value="">${esc(all)}</option>${state.users.filter(user=>user.active!==false).map(user=>`<option value="${esc(user.id)}" ${user.id===selected?'selected':''}>${esc(user.name)}</option>`).join('')}`;
}
function currency(value) {return value==null?'Sin importe registrado':new Intl.NumberFormat('es-PR',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(value);}
function amount(value,decimals=1) {return value==null?'—':new Intl.NumberFormat('es-PR',{maximumFractionDigits:decimals}).format(value);}
function localDatetime(value) {
  if(!value)return '';
  const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:timezone(),year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(new Date(value));
  const part=type=>parts.find(item=>item.type===type)?.value;
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
}
function zonedTimestamp(value) {
  if(!value)return null;
  // The workspace uses Puerto Rico's fixed UTC-04:00, independent of the PC zone.
  if(timezone()==='America/Puerto_Rico')return `${value}:00-04:00`;
  const target=Date.parse(`${value}:00Z`);
  if(!Number.isFinite(target))throw new Error('Introduce una fecha y hora válidas.');
  let guess=target;
  for(let i=0;i<3;i++) {
    const represented=Date.parse(localDatetime(new Date(guess).toISOString())+':00Z');
    guess+=target-represented;
  }
  if(localDatetime(new Date(guess).toISOString())!==value)throw new Error('Ese horario no existe en la zona configurada.');
  return new Date(guess).toISOString();
}
function metricCard(label,value,note,tone='') {
  return `<article class="metric ${tone}"><div class="metric-label">${esc(label)}</div><strong>${esc(value)}</strong><small>${esc(note)}</small></article>`;
}
function pageControls(action,offset,total,limit) {
  return `<nav class="pagination" aria-label="Paginación"><button class="button small" type="button" data-action="${esc(action)}" data-offset="${Math.max(0,offset-limit)}" ${offset===0?'disabled':''}>← Anteriores</button><span>${total?`${offset+1}–${Math.min(total,offset+limit)} de ${total}`:'Sin registros'}</span><button class="button small" type="button" data-action="${esc(action)}" data-offset="${offset+limit}" ${offset+limit>=total?'disabled':''}>Siguientes →</button></nav>`;
}
function bindLeadSearch(input,select,status,emptyLabel,onChange=()=>{}) {
  let timer,sequence=0;
  input.addEventListener('input',()=>{
    clearTimeout(timer);const currentSequence=++sequence;
    timer=setTimeout(async()=>{
      if(!select.isConnected)return;
      status.textContent='Buscando prospectos…';
      try {
        const data=await api(`/api/leads?q=${encodeURIComponent(input.value.trim())}&limit=50`);
        if(currentSequence!==sequence||!select.isConnected)return;
        const selected=select.value,selectedLead=state.leads.find(item=>item.id===selected);
        const results=data.leads||[];
        const keepSelected=selectedLead&&!results.some(item=>item.id===selected);
        state.leads=keepSelected?[selectedLead,...results]:results;
        select.innerHTML=`<option value="">${esc(emptyLabel)}</option>${state.leads.map(item=>`<option value="${esc(item.id)}" ${item.id===selected?'selected':''}>${esc(item.name)}</option>`).join('')}`;
        status.textContent=`${data.total??results.length} coincidencias${(data.total??0)>50?'; se muestran las primeras 50. Refina la búsqueda.':'.'}${keepSelected?' Se conserva el prospecto seleccionado hasta que elijas otro.':''}`;
        if(select.value!==selected)onChange();
      }catch(error){if(currentSequence===sequence&&select.isConnected)status.textContent=error.message;}
    },250);
  });
}

async function renderOperationsDashboard(requestId) {
  const query=new URLSearchParams({period:state.dashboardPeriod});
  if(state.dashboardStart)query.set('start',state.dashboardStart);
  if(state.dashboardEnd)query.set('end',state.dashboardEnd);
  const data=await api(`/api/dashboard?${query}`);if(!current(requestId))return;
  const metrics=data.metrics||{},recent=data.recent_leads||[],upcoming=data.upcoming_appointments||[],items=data.priorities||[];
  const period=data.period||{};
  content.innerHTML=heading('R.E.I.G.E.L. / TEAM CAGUAS',`Hola, ${state.user.name.split(' ')[0]}.`,'Tu cartera, las citas y el próximo paso de cada relación.',actionButton('new-lead','+ Nuevo prospecto'))+
    `<form id="dashboard-period" class="period-toolbar"><label>Periodo<select name="period" id="dashboard-period-select">${options({today:'Hoy',week:'Esta semana',month:'Este mes',all:'Todo el historial',custom:'Personalizado'},state.dashboardStart?'custom':state.dashboardPeriod)}</select></label><label class="custom-period" ${state.dashboardStart?'':'hidden'}>Desde<input type="date" name="start" value="${esc(state.dashboardStart)}"></label><label class="custom-period" ${state.dashboardStart?'':'hidden'}>Hasta<input type="date" name="end" value="${esc(state.dashboardEnd)}"></label><button class="button small" type="submit">Aplicar periodo</button><p class="period-note">${period.start?`${esc(period.start)} — ${period.end?esc(period.end):'hoy'}`:'Historial disponible'} · ${esc(period.timezone||timezone())}</p><p class="form-error" role="alert"></p></form>`+
    `<div class="metric-grid operations-metrics">${metricCard('PROSPECTOS',metrics.leads??0,'Registros del periodo')}${metricCard('CITAS PRÓXIMAS',metrics.appointments??0,'Confirmadas desde ahora')}${metricCard('VENTAS REGISTRADAS',metrics.won??metrics.won_leads??metrics.sales??0,'Etapa ganado, sin validar cobro')}${metricCard('SEGUIMIENTOS VENCIDOS',metrics.overdue_tasks??0,'Pendientes a esta hora','attention')}</div>`+
    `<div class="operations-grid"><section class="panel priorities-panel"><header class="panel-head"><div><p class="section-kicker">HOY, LO QUE MUEVE TU TRABAJO</p><h2>¿Qué debo hacer hoy?</h2></div><button class="text-link" type="button" data-view="tasks">Ver tareas ↗</button></header>${items.length?`<ol class="priority-list">${items.slice(0,8).map((item,index)=>`<li><span class="priority-index">${index+1}</span><div><strong>${esc(item.title)}</strong><p>${esc(({overdue_task:'Tarea vencida',task:'Tarea pendiente',followup:'Seguimiento pendiente',new_lead:'Prospecto pendiente',contact:'Contacto pendiente',appointment:'Cita próxima',conversation:'Atención humana'})[item.type]||'Prioridad calculada con tus registros')}</p></div>${item.task_id?actionButton('edit-task','Abrir tarea',`data-id="${esc(item.task_id)}"`,'small'):item.lead_id?actionButton('lead-detail','Abrir ficha',`data-id="${esc(item.lead_id)}"`,'small'):`<button class="button small" type="button" data-view="${item.appointment_id?'appointments':'conversations'}">Revisar</button>`}</li>`).join('')}</ol>`:empty('Tu siguiente paso está al día.','No hay prioridades pendientes en tus registros. Puedes revisar la cartera o planificar una nueva actividad.',`<button class="button small" type="button" data-view="leads">Revisar prospectos</button>`,'✓')}<p class="panel-footnote">Las prioridades reflejan el estado actual. El filtro de periodo se aplica a los indicadores comerciales.</p></section>`+
    `<section class="panel"><header class="panel-head"><div><p class="section-kicker">PRÓXIMOS ENCUENTROS</p><h2>Tu agenda</h2></div><button class="text-link" data-view="appointments" type="button">Ver agenda ↗</button></header>${upcoming.length?`<ul class="row-list">${upcoming.slice(0,5).map(item=>`<li>${dateTile(item.start_at)}<div class="list-content"><strong>${esc(item.lead_name||'Orientación')}</strong><p>${esc(time(item.start_at))} · ${esc(item.advisor_name||'')}</p></div>${item.lead_id?actionButton('lead-detail','Ficha',`data-id="${esc(item.lead_id)}"`,'small'):''}</li>`).join('')}</ul>`:empty('Sin citas próximas.','Consulta horarios reales para coordinar una orientación.',actionButton('new-appointment','Agendar cita','','small'),'▦')}</section></div>`+
    `<section class="panel pipeline-panel"><header class="panel-head"><div><p class="section-kicker">SITUACIÓN DE TU CARTERA</p><h2>Recorrido comercial</h2></div><span class="badge">${amount(metrics.conversion_rate??0)}% ganado / prospectos</span></header><div class="operations-pipeline">${(data.stages||[]).map(item=>`<button type="button" class="stage-tile" data-action="stage-leads" data-stage="${esc(item.stage)}"><strong>${esc(item.count)}</strong><span>${esc(stages[item.stage]||item.stage)}</span></button>`).join('')}</div><p class="panel-footnote">Las etapas describen el estado actual de los registros; no representan una conversión histórica entre cada paso.</p></section>`+
    `<div class="two-columns"><section class="panel"><header class="panel-head"><h2>Contactos recientes</h2><button class="text-link" data-view="leads" type="button">Ver cartera ↗</button></header>${recent.length?`<ul class="row-list">${recent.slice(0,5).map(lead=>`<li><span class="avatar">${esc(initials(lead.name))}</span><div class="list-content"><button type="button" class="table-button" data-action="lead-detail" data-id="${esc(lead.id)}">${esc(lead.name)}</button><p>${esc(lead.municipality||'Municipio pendiente')} · ${esc(lead.advisor_name||'Sin asignar')}</p></div>${badge(lead.stage)}</li>`).join('')}</ul>`:empty('Todavía no hay prospectos en este periodo.','Puedes cambiar el periodo o registrar una nueva oportunidad.','','◎')}</section><section class="panel"><header class="panel-head"><h2>Datos para decidir</h2></header><div class="panel-body data-summary"><div><span>Oportunidades abiertas</span><strong>${esc(metrics.open_opportunities??0)}</strong></div><div><span>Valor declarado de oportunidades</span><strong>${currency(metrics.opportunity_value??null)}</strong></div><div><span>Citas realizadas</span><strong>${esc(metrics.appointments_completed??0)}</strong></div><p class="field-help">Los importes solo proceden de registros del equipo. Ganado no demuestra facturación ni cobro.</p></div></section></div>`;
  $('#dashboard-period-select').addEventListener('change',event=>$$('.custom-period').forEach(label=>label.hidden=event.target.value!=='custom'));
  $('#dashboard-period').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{
    const selected=fields.get('period');
    if(selected==='custom') {
      if(!fields.get('start')||!fields.get('end'))throw new Error('Selecciona las dos fechas del periodo.');
      if(fields.get('end')<fields.get('start'))throw new Error('La fecha final debe ser igual o posterior a la inicial.');
      state.dashboardPeriod='all';state.dashboardStart=fields.get('start');state.dashboardEnd=fields.get('end');
    } else {state.dashboardPeriod=selected;state.dashboardStart='';state.dashboardEnd='';}
    await navigate('dashboard',false);
  }));
}

async function renderOperationsLeads(requestId) {
  await loadUsers();if(!current(requestId))return;
  const q=state.leadQuery;
  content.innerHTML=heading('RELACIONES CON FUTURO','Prospectos','Una ficha completa, un responsable y un próximo paso para cada persona.',actionButton('new-lead','+ Nuevo prospecto'))+
    `<div class="toolbar crm-toolbar"><label class="search-field"><span class="sr-only">Buscar prospectos</span><input type="search" id="lead-search" value="${esc(q.q)}" placeholder="Nombre, teléfono, correo o municipio…"></label><label><span class="sr-only">Filtrar por etapa</span><select id="stage-filter">${options(stages,q.stage,'Todas las etapas')}</select></label>${state.user.role==='admin'?`<label><span class="sr-only">Filtrar por asesor</span><select id="lead-advisor">${personOptions(q.advisor_id,'Todos los asesores')}</select></label>`:''}<label><span class="sr-only">Ordenar prospectos</span><select id="lead-sort">${options({recent:'Más recientes',oldest:'Más antiguos',name:'Nombre A–Z',followup:'Próximo seguimiento'},q.sort==='name'?'name':q.sort==='next_followup_at'?'followup':q.order==='asc'?'oldest':'recent')}</select></label></div><div class="crm-viewbar"><p class="result-count" id="lead-count" role="status"></p><div class="crm-view-switch" role="group" aria-label="Vista de prospectos"><button type="button" data-action="lead-view" data-mode="table" aria-pressed="${state.leadView==='board'?'false':'true'}">Tabla</button><button type="button" data-action="lead-view" data-mode="board" aria-pressed="${state.leadView==='board'?'true':'false'}">Pipeline</button></div></div><section class="panel" id="leads-result">${loading()}</section><nav id="lead-pagination" class="pagination" aria-label="Páginas de prospectos"></nav>`;
  $('#lead-search').addEventListener('input',()=>{clearTimeout(leadSearchTimer);leadSearchTimer=setTimeout(()=>{q.q=$('#lead-search')?.value.trim()||'';q.offset=0;filterOperationsLeads();},250);});
  ['#stage-filter','#lead-advisor','#lead-sort'].forEach(selector=>$(selector)?.addEventListener('change',()=>{q.stage=$('#stage-filter').value;q.advisor_id=$('#lead-advisor')?.value||'';const sort=$('#lead-sort').value;q.sort=sort==='name'?'name':sort==='followup'?'next_followup_at':'created_at';q.order=sort==='recent'?'desc':'asc';q.offset=0;filterOperationsLeads();}));
  await filterOperationsLeads();
}
const pipelineStages = ['nuevo','contacto_pendiente','contactado','calificado','cita','cita_realizada','propuesta_preparacion','propuesta_presentada','negociacion','ganado','perdido'];

function pipelineGroups(leads, stageFilter = '') {
  const order = stageFilter ? [stageFilter] : pipelineStages;
  return order.map(stage => ({stage, leads: leads.filter(lead => lead.stage === stage)}));
}
function pipelineCard(lead) {
  const overdue = lead.next_followup_at && new Date(lead.next_followup_at) < new Date();
  return `<article class="pipeline-card"><button type="button" class="pipeline-card-title table-button" data-action="lead-detail" data-id="${esc(lead.id)}">${esc(lead.name)}</button><p class="pipeline-card-meta">${esc(lead.municipality||'Municipio por confirmar')} · ${esc(lead.advisor_name||'Sin asignar')}</p><div class="pipeline-card-tags">${lead.consent?badge('green','Autorizado'):badge('orange','Sin autorización')}${lead.opportunity_value!=null?`<span class="pipeline-value">Valor declarado: ${esc(currency(lead.opportunity_value))}</span>`:''}</div><p class="pipeline-card-next ${overdue?'overdue-text':''}">${lead.next_followup_at?`Seguimiento: ${esc(dateTime(lead.next_followup_at))}`:'Seguimiento sin fecha'}</p><label class="pipeline-card-move">Mover a<select data-move-id="${esc(lead.id)}" aria-label="Cambiar etapa de ${esc(lead.name)}">${pipelineStages.map(stage=>`<option value="${esc(stage)}" ${stage===lead.stage?'selected':''}>${esc(stages[stage]||stage)}</option>`).join('')}</select></label></article>`;
}
function pipelineBoardMarkup() {
  const groups = pipelineGroups(state.leads, state.leadQuery.stage);
  return `<div class="pipeline-board" role="region" aria-label="Pipeline comercial por etapa">${groups.map(group=>`<section class="pipeline-column" aria-labelledby="pipeline-stage-${esc(group.stage)}"><header class="pipeline-column-head"><h2 id="pipeline-stage-${esc(group.stage)}">${esc(stages[group.stage]||group.stage)}</h2><span class="badge">${group.leads.length}</span></header><div class="pipeline-column-body">${group.leads.length?group.leads.map(pipelineCard).join(''):'<p class="pipeline-empty">Sin registros</p>'}</div></section>`).join('')}</div>${state.leadQuery.stage?'<p class="pipeline-note">Hay un filtro de etapa activo. Quítalo para recorrer el tablero completo.</p>':''}<p class="pipeline-note">Mover una tarjeta registra la etapa con tu usuario en el historial. La etapa es un estado comercial: no confirma cobro, firma ni venta.</p>`;
}
function bindPipelineMoves() {
  $$('.pipeline-card-move select').forEach(select=>select.addEventListener('change',()=>moveLeadStage(select)));
}
async function moveLeadStage(select) {
  const id = select.dataset.moveId;
  const stage = select.value;
  const lead = state.leads.find(item=>item.id===id);
  if(!lead||lead.stage===stage)return;
  const previous = lead.stage;
  select.disabled = true;
  try {
    await post(`/api/leads/${encodeURIComponent(id)}`, {stage}, 'PATCH');
    toast(`Etapa actualizada: ${stages[stage]||stage}.`);
    await filterOperationsLeads();
    const target = $$('.pipeline-card-move select').find(item=>item.dataset.moveId===id);
    if(target)target.focus();
  } catch(error) {
    select.value = previous;
    select.disabled = false;
    toast(error.message);
  }
}
function setLeadView(mode) {
  state.leadView = mode === 'board' ? 'board' : 'table';
  state.leadQuery.offset = 0;
  $$('.crm-view-switch button').forEach(item=>item.setAttribute('aria-pressed', String(item.dataset.mode === state.leadView)));
  return filterOperationsLeads();
}
async function filterOperationsLeads() {
  const sequence=++leadSearchSequence;
  const board=state.leadView==='board';
  const limit=board?500:50;
  const query=new URLSearchParams({...state.leadQuery,limit:String(limit)});
  const target=$('#leads-result');if(!target)return;
  target.classList.toggle('board-mode',board);
  try {
    const data=await api(`/api/leads?${query}`);if(sequence!==leadSearchSequence||!target.isConnected)return;
    state.leads=data.leads||[];const total=data.total??state.leads.length;
    $('#lead-count').textContent=board
      ? `${total} ${total===1?'prospecto':'prospectos'} · tablero por etapa${total>limit?` · se muestran los primeros ${limit}; acota con los filtros`:''}`
      : `${total} ${total===1?'prospecto':'prospectos'} · ${total?`${state.leadQuery.offset+1}–${Math.min(total,state.leadQuery.offset+50)}`:'sin resultados'}`;
    if(board) {
      target.innerHTML=pipelineBoardMarkup();
      $('#lead-pagination').innerHTML='';
      bindPipelineMoves();
      return;
    }
    target.innerHTML=state.leads.length?`<div class="table-wrap"><table class="crm-table"><thead><tr><th>PROSPECTO</th><th>ETAPA / PRÓXIMO PASO</th><th>RESPONSABLE</th><th>ORIGEN Y PERMISO</th></tr></thead><tbody>${state.leads.map(lead=>`<tr><td data-label="Prospecto"><button type="button" class="table-button" data-action="lead-detail" data-id="${esc(lead.id)}">${esc(lead.name)}</button><small>${esc(lead.email||lead.phone||'Sin contacto')}</small><small>${esc(lead.municipality||'Municipio por confirmar')}</small></td><td data-label="Etapa y seguimiento">${badge(lead.stage)}<small class="${lead.next_followup_at&&new Date(lead.next_followup_at)<new Date()?'overdue-text':''}">${lead.next_followup_at?esc(dateTime(lead.next_followup_at)):'Seguimiento sin fecha'}</small></td><td data-label="Responsable">${esc(lead.advisor_name||'Sin asignar')}<small>${esc(lead.interest||'Interés por conocer')}</small></td><td data-label="Origen y permiso"><span>${esc(lead.source||'manual')}</span><small>${lead.consent?badge('green','Autorizado'):badge('orange','Sin autorización')}</small></td></tr>`).join('')}</tbody></table></div>`:empty('No hay prospectos con estos filtros.','Prueba otro periodo, asesor o búsqueda. También puedes registrar una nueva oportunidad.',actionButton('new-lead','Registrar prospecto','','small'),'◎');
    $('#lead-pagination').innerHTML=`<button type="button" class="button small" data-action="lead-page" data-offset="${Math.max(0,state.leadQuery.offset-50)}" ${state.leadQuery.offset===0?'disabled':''}>← Anteriores</button><span>Página ${Math.floor(state.leadQuery.offset/50)+1}</span><button type="button" class="button small" data-action="lead-page" data-offset="${state.leadQuery.offset+50}" ${state.leadQuery.offset+50>=total?'disabled':''}>Siguientes →</button>`;
  } catch(error) {if(target.isConnected)target.innerHTML=`<div class="error-state" role="alert"><p>${esc(error.message)}</p>${actionButton('retry-leads','Volver a intentar','','small')}</div>`;}
}

function operationsLeadFields(lead={}) {
  return `<div class="form-grid"><label class="span-2">Nombre completo<input name="name" required maxlength="100" autocomplete="name" value="${esc(lead.name||'')}"></label><label>Correo electrónico<input name="email" type="email" maxlength="254" autocomplete="email" value="${esc(lead.email||'')}"></label><label>Teléfono<input name="phone" type="tel" maxlength="40" autocomplete="tel" value="${esc(lead.phone||'')}" placeholder="+1 787…"></label><label>Municipio<input name="municipality" maxlength="100" autocomplete="address-level2" value="${esc(lead.municipality||'')}"></label><label>Fuente de captación<select name="source">${options({manual:'Registro manual',web:'Web',referido:'Referido',whatsapp:'WhatsApp',telegram:'Telegram',instagram:'Instagram',messenger:'Messenger',facebook:'Facebook',google:'Google',organic:'Orgánico'},lead.source||'manual')}</select></label><label>Factura mensual declarada (USD)<input name="monthly_bill" type="number" min="0" max="100000" step="0.01" value="${esc(lead.monthly_bill??'')}"></label><label>Consumo mensual declarado (kWh)<input name="monthly_kwh" type="number" min="0" step="0.01" value="${esc(lead.monthly_kwh??'')}"></label><label class="span-2">Interés principal<input name="interest" maxlength="300" value="${esc(lead.interest||'')}" placeholder="Respaldo, entender el consumo, comparar opciones…"></label><label class="span-2 checkbox"><input name="consent" type="checkbox" ${lead.consent?'checked':''}><span>La persona autorizó ser contactada. Registra únicamente un permiso real.</span></label></div><p class="field-help">Incluye correo o teléfono. Un registro sin permiso no autoriza comunicaciones comerciales. El consumo y la factura son datos declarados.</p>`;
}
function leadPayload(fields) {
  const result={};
  ['name','email','phone','municipality','source','interest'].forEach(name=>result[name]=fields.get(name)||'');
  ['monthly_bill','monthly_kwh'].forEach(name=>result[name]=fields.get(name)===''?null:Number(fields.get(name)));
  result.consent=fields.has('consent');
  return result;
}
async function newOperationsLead() {
  await loadUsers();
  openDialog('Registrar prospecto',`<form id="lead-form">${operationsLeadFields()}${state.user.role==='admin'?`<label class="form-section-label">Asesor responsable<select name="advisor_id">${personOptions('','Asignación automática disponible')}</select></label>`:''}<p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Cancelar</button><button class="button primary" type="submit">Guardar prospecto</button></div></form>`);
  $('#lead-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{
    const payload=leadPayload(fields);if(!payload.email&&!payload.phone)throw new Error('Incluye un correo electrónico o un teléfono.');
    if(state.user.role==='admin'&&fields.get('advisor_id'))payload.advisor_id=fields.get('advisor_id');
    const data=await post('/api/leads',payload);toast('Prospecto guardado.');await leadDetail(data.lead.id);
  }));
}
async function operationsLeadDetail(id) {
  openDialog('Ficha del prospecto',loading());dialog.classList.add('wide-dialog');
  try {
    const [data]=await Promise.all([api(`/api/leads/${encodeURIComponent(id)}`),loadUsers()]);
    if(!dialog.open)return;
    const lead=data.lead;state.activeLead=lead;
    $('#dialog-title').textContent=lead.name;
    $('#dialog-content').innerHTML=`<div class="lead-profile-header"><div>${badge(lead.stage)}<p>${esc(lead.advisor_name||'Sin asesor asignado')} · Desde ${esc(dateTime(lead.created_at,{hour:undefined,minute:undefined}))}</p></div><div class="actions">${actionButton('lead-brief','Preparar orientación',`data-id="${esc(id)}"`,'small')}${actionButton('schedule-lead','Agendar cita',`data-id="${esc(id)}"`,'small')}</div></div><div class="profile-grid"><div><form id="lead-update"><h3 class="form-section-title">Información del prospecto</h3>${operationsLeadFields(lead)}<div class="form-grid profile-commercial"><label>Etapa comercial<select name="stage">${options(stages,lead.stage)}</select></label>${state.user.role==='admin'?`<label>Asesor responsable<select name="advisor_id">${personOptions(lead.advisor_id)}</select></label>`:''}<label>Último contacto registrado<input type="datetime-local" name="last_contact_at" value="${esc(localDatetime(lead.last_contact_at))}"></label><label>Próximo seguimiento<input type="datetime-local" name="next_followup_at" value="${esc(localDatetime(lead.next_followup_at))}"></label><label class="span-2">Valor declarado de oportunidad (USD)<input type="number" name="opportunity_value" min="0" step="0.01" value="${esc(lead.opportunity_value??'')}" placeholder="Opcional, según propuesta autorizada"></label><label class="span-2">Notas internas<textarea name="notes" maxlength="5000">${esc(lead.notes||'')}</textarea></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary" type="submit">Guardar ficha</button></div></form><section class="profile-section"><div class="view-heading-inline"><h3>Registrar una interacción</h3></div><form id="activity-form"><div class="form-grid"><label>Tipo<select name="type">${options(interactionTypes,'call')}</select></label><label>Fecha y hora<input type="datetime-local" name="occurred_at" value="${esc(localDatetime(new Date().toISOString()))}" required></label><label class="span-2">Qué ocurrió<textarea name="description" required maxlength="2000" placeholder="Resume la interacción realizada por una persona."></textarea></label><label class="span-2">Resultado<input name="outcome" maxlength="1000" placeholder="Interés, dudas o siguiente paso acordado"></label></div><p class="field-help">Este registro documenta tu actividad; la aplicación no realiza llamadas ni envía mensajes.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button small" type="submit">Guardar interacción</button></div></form></section></div><div class="profile-side"><section class="profile-section"><div class="view-heading-inline"><h3>Próximas tareas</h3>${actionButton('new-task','+ Tarea',`data-lead="${esc(id)}"`,'small')}</div>${taskList(data.tasks||[],true)}</section><section class="profile-section"><h3>Citas</h3>${(data.appointments||[]).length?(data.appointments||[]).map(item=>`<div class="compact-record"><strong>${esc(dateTime(item.start_at))}</strong><small>${esc(item.advisor_name||'')} · ${esc(statuses[item.status]||item.status)}</small></div>`).join(''):'<p class="field-help">Sin citas registradas.</p>'}</section><section class="profile-section"><h3>Historial de actividad</h3>${activityTimeline(data.activities||[])}</section><details class="audit-details"><summary>Trazabilidad de cambios</summary>${(data.history||[]).length?`<ol class="audit-list">${data.history.slice(0,30).map(item=>`<li><strong>${esc(item.action||item.type||'Cambio registrado')}</strong><small>${esc(dateTime(item.created_at))}${item.actor_name?` · ${esc(item.actor_name)}`:''}</small></li>`).join('')}</ol>`:'<p class="field-help">Sin cambios adicionales.</p>'}</details><div id="lead-duplicates"></div></div></div>`;
    $('#lead-update').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{
      const payload={...leadPayload(fields),stage:fields.get('stage'),notes:fields.get('notes'),last_contact_at:zonedTimestamp(fields.get('last_contact_at')),next_followup_at:zonedTimestamp(fields.get('next_followup_at')),opportunity_value:fields.get('opportunity_value')===''?null:Number(fields.get('opportunity_value'))};
      if(state.user.role==='admin')payload.advisor_id=fields.get('advisor_id')||null;
      await post(`/api/leads/${encodeURIComponent(id)}`,payload,'PATCH');toast('Ficha actualizada.');await leadDetail(id);
    }));
    $('#activity-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post(`/api/leads/${encodeURIComponent(id)}/activities`,{type:fields.get('type'),description:fields.get('description'),outcome:fields.get('outcome'),occurred_at:zonedTimestamp(fields.get('occurred_at'))});toast('Interacción registrada.');await leadDetail(id);}));
    findLeadDuplicates(lead);
    appendLeadMemory(id);
  }catch(error){if(dialog.open)$('#dialog-content').innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p>`;}
}
function activityTimeline(items) {
  return items.length?`<ol class="activity-timeline">${items.map(item=>`<li><span class="timeline-dot" aria-hidden="true"></span><div><strong>${esc(interactionTypes[item.type]||item.type)}</strong><p>${esc(item.description)}</p>${item.outcome?`<p class="activity-outcome">${esc(item.outcome)}</p>`:''}<small>${esc(dateTime(item.occurred_at||item.created_at))}${item.actor_name?` · ${esc(item.actor_name)}`:''}</small></div></li>`).join('')}</ol>`:'<p class="field-help">Las interacciones registradas aparecerán aquí.</p>';
}
async function findLeadDuplicates(lead) {
  // Search is server-scoped: no records from another advisor can be discovered.
  const term=lead.email||lead.phone;if(!term)return;
  try {const data=await api(`/api/leads?q=${encodeURIComponent(term)}&limit=20`);const duplicates=(data.leads||[]).filter(item=>item.id!==lead.id&&(lead.email&&item.email===lead.email||lead.phone&&item.phone===lead.phone));const target=$('#lead-duplicates');if(!target||state.activeLead?.id!==lead.id)return;if(duplicates.length)target.innerHTML=`<aside class="duplicate-notice"><strong>Posible contacto duplicado</strong><p>Coincide un correo o teléfono. Revisa antes de crear otro registro.</p>${duplicates.map(item=>actionButton('lead-detail',item.name,`data-id="${esc(item.id)}"`,'small')).join('')}</aside>`;}catch{/* A duplicate hint must never block the profile. */}
}

function taskList(items,compact=false) {
  if(!items.length)return `<p class="field-help ${compact?'':'panel-body'}">No hay tareas con este filtro. Registra un próximo paso con fecha.</p>`;
  return `<div class="task-list ${compact?'compact-tasks':''}">${items.map(item=>`<article class="task-row ${item.overdue?'overdue':''}"><div class="task-status-mark ${esc(item.status)}" aria-hidden="true">${item.status==='completed'?'✓':item.status==='cancelled'?'×':'○'}</div><div class="task-main"><button type="button" class="table-button" data-action="edit-task" data-id="${esc(item.id)}">${esc(taskTypes[item.type]||item.type)}</button>${item.lead_name?`<button class="task-lead" type="button" data-action="lead-detail" data-id="${esc(item.lead_id)}">${esc(item.lead_name)}</button>`:''}<p>${esc(item.description||'Sin descripción adicional')}</p><small class="${item.overdue?'overdue-text':''}">${esc(dateTime(item.due_at))}${item.owner_name?` · ${esc(item.owner_name)}`:''}</small>${item.outcome?`<p class="activity-outcome">${esc(item.outcome)}</p>`:''}</div><div class="task-tags">${badge(item.overdue?'red':item.status==='completed'?'green':'blue',item.overdue?'Vencida':taskStatuses[item.status]||item.status)}${item.priority==='high'?badge('orange','Alta prioridad'):''}</div></article>`).join('')}</div>`;
}
async function renderTasks(requestId) {
  await loadUsers();if(!current(requestId))return;
  const query=new URLSearchParams({status:state.taskQuery.status,limit:'100',offset:String(state.taskOffset||0)});if(state.taskQuery.owner_id)query.set('owner_id',state.taskQuery.owner_id);
  const data=await api(`/api/tasks?${query}`);if(!current(requestId))return;state.tasks=data.tasks||[];
  const overdue=state.tasks.filter(item=>item.overdue).length;
  content.innerHTML=heading('CADA COMPROMISO, VISIBLE','Tareas y seguimiento','Registra el trabajo del equipo y conserva el resultado de cada actividad.',actionButton('new-task','+ Nueva tarea'))+
    `<div class="toolbar"><label>Estado<select id="task-status-filter">${options({pending:'Pendientes',completed:'Realizadas',cancelled:'Canceladas'},state.taskQuery.status,'Todos los estados')}</select></label>${state.user.role==='admin'?`<label>Responsable<select id="task-owner-filter">${personOptions(state.taskQuery.owner_id,'Todo el equipo')}</select></label>`:''}<span class="count">${data.total??state.tasks.length} tareas${overdue?` · ${overdue} vencidas en esta página`:''}</span></div><section class="panel"><header class="panel-head"><h2>${state.taskQuery.status==='pending'?'Tu próximo paso':state.taskQuery.status==='completed'?'Trabajo registrado':'Actividades comerciales'}</h2><span class="badge">Hasta 100 por consulta</span></header>${taskList(state.tasks)}</section><p class="field-help">Cada tarea es un registro interno. Enviar información o confirmar una cita requiere que una persona realice la comunicación. Los recordatorios aparecen dentro de la aplicación.</p>`;
  content.insertAdjacentHTML('beforeend',pageControls('task-page',state.taskOffset||0,data.total??state.tasks.length,100));
  $('#task-status-filter').addEventListener('change',()=>{state.taskQuery.status=$('#task-status-filter').value;state.taskOffset=0;navigate('tasks',false);});
  $('#task-owner-filter')?.addEventListener('change',()=>{state.taskQuery.owner_id=$('#task-owner-filter').value;state.taskOffset=0;navigate('tasks',false);});
}
async function taskForm(id='',leadId='') {
  openDialog(id?'Actualizar tarea':'Nueva tarea',loading());
  try {
    await Promise.all([loadUsers(),loadLeads()]);
    let task=state.tasks.find(item=>item.id===id);
    if(id&&!task){const response=await api(`/api/tasks/${encodeURIComponent(id)}`);task=response.task;if(!task)throw new Error('No se encontró la tarea. Actualiza la lista e inténtalo de nuevo.');}
    task=task||{lead_id:leadId,owner_id:state.leads.find(lead=>lead.id===leadId)?.advisor_id||state.user.id,type:'follow_up',priority:'normal',status:'pending',due_at:new Date(Date.now()+86400000).toISOString(),reminder_hours:1};
    if(task.lead_id&&!state.leads.some(lead=>lead.id===task.lead_id)){const selected=await api(`/api/leads/${encodeURIComponent(task.lead_id)}`);state.leads.unshift(selected.lead);}
    const leadOptions=state.leads.map(item=>`<option value="${esc(item.id)}" ${item.id===task.lead_id?'selected':''}>${esc(item.name)}</option>`).join('');
    $('#dialog-content').innerHTML=`<form id="task-form"><div class="form-grid"><label class="span-2">Buscar prospecto<input type="search" id="task-lead-search" placeholder="Filtra por nombre, correo o teléfono"></label><label class="span-2">Prospecto relacionado<select name="lead_id" id="task-lead-select"><option value="">Sin prospecto (tarea interna)</option>${leadOptions}</select></label><label>Tipo de tarea<select name="type">${options(taskTypes,task.type)}</select></label><label>Prioridad<select name="priority">${options(priorities,task.priority)}</select></label>${state.user.role==='admin'?`<label class="span-2">Responsable<select name="owner_id" id="task-owner" required>${personOptions(task.owner_id,'Selecciona responsable')}</select></label>`:''}<label>Fecha y hora · ${esc(timezone())}<input type="datetime-local" name="due_at" required value="${esc(localDatetime(task.due_at))}"></label><label>Recordatorio previo (horas)<input type="number" name="reminder_hours" min="0" max="720" step="1" value="${esc(task.reminder_hours??1)}"></label><label class="span-2">Descripción<textarea name="description" required maxlength="2000" placeholder="Qué debe hacerse y para qué">${esc(task.description||'')}</textarea></label>${id?`<label>Estado<select name="status">${options(taskStatuses,task.status)}</select></label><label class="span-2">Resultado<textarea name="outcome" maxlength="1500" placeholder="Registra el resultado real de la actividad.">${esc(task.outcome||'')}</textarea></label>`:''}</div><p id="task-lead-search-status" class="field-help" role="status"></p><p class="hint">El recordatorio persiste y se consulta desde Notificaciones. No envía correos, SMS ni WhatsApp.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Cancelar</button><button class="button primary" type="submit">${id?'Guardar tarea':'Crear tarea'}</button></div></form>`;
    const taskOwner=()=>{const lead=state.leads.find(item=>item.id===$('#task-lead-select')?.value);if(lead?.advisor_id&&$('#task-owner'))$('#task-owner').value=lead.advisor_id;};
    $('#task-lead-select').addEventListener('change',taskOwner);if(!id)taskOwner();
    bindLeadSearch($('#task-lead-search'),$('#task-lead-select'),$('#task-lead-search-status'),'Sin prospecto (tarea interna)',taskOwner);
    $('#task-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{
      const payload={lead_id:fields.get('lead_id')||null,type:fields.get('type'),priority:fields.get('priority'),due_at:zonedTimestamp(fields.get('due_at')),description:fields.get('description'),reminder_hours:Number(fields.get('reminder_hours'))};
      if(state.user.role==='admin')payload.owner_id=fields.get('owner_id');
      if(id){payload.status=fields.get('status');payload.outcome=fields.get('outcome');}
      await post(id?`/api/tasks/${encodeURIComponent(id)}`:'/api/tasks',payload,id?'PATCH':'POST');
      closeDialog();toast(id?'Tarea actualizada.':'Tarea creada.');await navigate('tasks',false);
    }));
  }catch(error){if(dialog.open)$('#dialog-content').innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p>`;}
}

async function renderNotifications(requestId) {
  const data=await api(`/api/notifications?limit=100&offset=${state.notificationOffset||0}`);if(!current(requestId))return;
  const items=data.notifications||[];
  content.innerHTML=heading('LO IMPORTANTE, A TIEMPO','Notificaciones','Avisos internos derivados de tareas, citas y actividad persistida.',actionButton('refresh','Actualizar avisos','',''))+
    `<section class="panel"><header class="panel-head"><h2>${data.unread??items.filter(item=>!item.read).length} sin leer</h2><span class="badge">Solo dentro de R.E.I.G.E.L.</span></header>${items.length?`<ul class="notification-list">${items.map(item=>`<li class="${item.read?'is-read':'is-unread'}"><span class="notification-dot" aria-hidden="true"></span><div class="notification-main"><strong>${esc(item.title)}</strong><p>${esc(dateTime(item.created_at))} · ${esc(({task_overdue:'Tarea vencida',task_reminder:'Recordatorio de tarea',appointment_reminder:'Cita próxima',lead_assigned:'Asignación',human_request:'Atención humana'})[item.type]||'Aviso interno')}</p></div><div class="actions">${item.lead_id?actionButton('lead-detail','Abrir ficha',`data-id="${esc(item.lead_id)}"`,'small'):''}${item.read?badge('green','Leída'):actionButton('read-notification','Marcar leída',`data-id="${esc(item.id)}"`,'small')}</div></li>`).join('')}</ul>`:empty('Sin avisos pendientes.','Las tareas y citas generan recordatorios internos al consultar esta vista. Configura la antelación en cada registro.','','✓')}</section>${pageControls('notification-page',state.notificationOffset||0,data.total??items.length,100)}<p class="field-help">Las notificaciones persisten entre reinicios. Un aviso leído no demuestra que el cliente haya recibido una comunicación.</p>`;
}

async function renderOperationsAppointments(requestId) {
  const [data]=await Promise.all([api('/api/appointments'),loadUsers()]);if(!current(requestId))return;state.appointments=data.appointments||[];
  content.innerHTML=heading('CADA ENCUENTRO, EN SU LUGAR','Agenda',`Horarios reales en ${timezone()}, con confirmación al guardar.`,actionButton('new-appointment','+ Agendar cita'))+
    `<div class="toolbar agenda-toolbar"><label>Vista<select id="agenda-view">${options({upcoming:'Próximas',day:'Día',week:'Semana',all:'Todo el historial'},'upcoming')}</select></label><label>Fecha<input type="date" id="agenda-date" value="${dateInput()}"></label><label>Estado<select id="appointment-filter">${options({confirmed:'Confirmadas',completed:'Realizadas',no_show:'No asistió',cancelled:'Canceladas'},'','Todos los estados')}</select></label>${state.user.role==='admin'?`<label>Asesor<select id="agenda-advisor">${personOptions('','Todo el equipo')}</select></label>`:''}<span class="count" id="appointment-count"></span></div><div id="appointments-result"></div><p class="field-help">Una cita se puede marcar realizada o no asistió después de su hora de finalización. Cancelar libera el horario. El archivo de calendario no sincroniza calendarios externos.</p>`;
  ['#agenda-view','#agenda-date','#appointment-filter','#agenda-advisor'].forEach(selector=>$(selector)?.addEventListener('change',filterOperationsAppointments));filterOperationsAppointments();
}
function filterOperationsAppointments() {
  const view=$('#agenda-view').value,day=$('#agenda-date').value,status=$('#appointment-filter').value,advisor=$('#agenda-advisor')?.value;
  let first=day,last=day;
  if(view==='week'){const selected=new Date(day+'T12:00:00Z');const offset=(selected.getUTCDay()+6)%7;selected.setUTCDate(selected.getUTCDate()-offset);first=selected.toISOString().slice(0,10);selected.setUTCDate(selected.getUTCDate()+6);last=selected.toISOString().slice(0,10);}
  const items=state.appointments.filter(item=>{
    const local=localDatetime(item.start_at).slice(0,10);
    return (!status||item.status===status)&&(!advisor||item.advisor_id===advisor)&&(view==='all'||view==='upcoming'&&item.status==='confirmed'&&new Date(item.end_at)>new Date()||(view==='day'||view==='week')&&local>=first&&local<=last);
  }).sort((a,b)=>new Date(a.start_at)-new Date(b.start_at));
  $('#appointment-count').textContent=`${items.length} ${items.length===1?'cita':'citas'}${view==='week'?` · ${first} — ${last}`:''}`;
  $('#appointments-result').innerHTML=items.length?`<div class="agenda-list">${items.map(item=>`<article class="appointment-card">${dateTile(item.start_at)}<div class="appointment-main"><button type="button" class="table-button appointment-title" data-action="lead-detail" data-id="${esc(item.lead_id)}">${esc(item.lead_name||'Orientación')}</button><p>${esc(dateTime(item.start_at))} – ${esc(time(item.end_at))}</p><small>${esc(item.advisor_name||'Asesor')} · ${esc(item.source||'Agenda')}</small>${item.reference?`<span class="appointment-code" title="Código que recibe la persona">Código ${esc(item.reference.slice(0,3))}-${esc(item.reference.slice(3))}</span>`:''}</div><div class="appointment-actions">${badge(item.status)}${item.status==='confirmed'&&new Date(item.end_at)<=new Date()?`${actionButton('appointment-status','Realizada',`data-id="${esc(item.id)}" data-status="completed"`,'small')}${actionButton('appointment-status','No asistió',`data-id="${esc(item.id)}" data-status="no_show"`,'small')}`:''}${item.status==='confirmed'?`${actionButton('appointment-reminder','Recordatorio',`data-id="${esc(item.id)}"`,'small')}${actionButton('cancel-appointment','Cancelar',`data-id="${esc(item.id)}"`,'small danger')}`:''}<a class="button small" href="/api/appointments/${encodeURIComponent(item.id)}/ics" download>Calendario ↓</a></div></article>`).join('')}</div>`:`<section class="panel">${empty('Sin citas para esta vista.','Cambia la fecha o los filtros, o reserva un horario disponible.',actionButton('new-appointment','Agendar cita','','small'),'▦')}</section>`;
}
function appointmentStatusForm(id,status) {
  openDialog('Registrar resultado de la cita',`<form id="appointment-status-form"><p>Registrar esta cita como <strong>${esc(statuses[status])}</strong>. Esta acción documenta el resultado informado por el equipo.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Volver</button><button class="button primary" type="submit">Guardar resultado</button></div></form>`);
  $('#appointment-status-form').addEventListener('submit',event=>submitForm(event,async()=>{await post(`/api/appointments/${encodeURIComponent(id)}`,{status},'PATCH');closeDialog();toast('Resultado de la cita registrado.');await navigate('appointments',false);}));
}
function appointmentReminderForm(id) {
  const item=state.appointments.find(appointment=>appointment.id===id);
  openDialog('Recordatorio interno de cita',`<form id="appointment-reminder-form"><label>Antelación del aviso (horas)<input type="number" name="reminder_hours" min="0" max="720" step="1" required value="${esc(item?.reminder_hours??24)}"></label><p class="field-help">Se guarda con la cita y aparece en Notificaciones. No envía mensajes al cliente.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Cancelar</button><button class="button primary" type="submit">Guardar recordatorio</button></div></form>`);
  $('#appointment-reminder-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post(`/api/appointments/${encodeURIComponent(id)}`,{reminder_hours:Number(fields.get('reminder_hours'))},'PATCH');closeDialog();toast('Recordatorio guardado.');await navigate('appointments',false);}));
}

function renderEnergy(requestId) {
  if(!current(requestId))return;
  content.innerHTML=heading('ENTENDER ANTES DE DIMENSIONAR','Orientación energética','Cálculos preliminares con parámetros explícitos, sin tarifas ni promesas de ahorro.')+
    `<div class="energy-layout"><section class="panel"><header class="panel-head"><div><p class="section-kicker">DATOS E HIPÓTESIS</p><h2>Calculadora preliminar</h2></div></header><div class="panel-body"><form id="energy-form"><div class="form-grid"><label>Consumo mensual medio (kWh)<input name="monthly_kwh" type="number" min="0" step="any" placeholder="Si se conoce"></label><label>Consumo anual (kWh)<input name="annual_kwh" type="number" min="0" step="any" placeholder="Si se conoce"></label><label class="span-2">Factura mensual declarada (USD)<input name="monthly_bill" type="number" min="0" step="0.01" placeholder="Opcional, no se usa como tarifa"></label><label>Potencia nominal de cada panel (W)<input name="panel_watts" type="number" min="0" step="any" placeholder="Según ficha documentada"></label><label>Cantidad de paneles<input name="panel_count" type="number" min="0" step="1" placeholder="Cantidad entera"></label><label class="span-2">Capacidad nominal del sistema (kW)<input name="system_kw" type="number" min="0" step="any" placeholder="Si se conoce"></label><label class="span-2">Rendimiento anual supuesto (kWh por kW por año)<input name="specific_yield_kwh_per_kw_year" type="number" min="0" step="any" placeholder="Parámetro a justificar para el sitio"><span class="field-help">Debe proporcionarlo una fuente o evaluación apropiada. La herramienta no asigna una producción garantizada.</span></label><label class="span-2">Cobertura objetivo (%)<input name="coverage_target_percent" type="number" min="0" step="any" placeholder="Objetivo opcional"></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary" type="submit">Calcular orientación</button></div></form></div></section><section class="panel energy-results" id="energy-results" aria-live="polite"><header class="panel-head"><h2>Una estimación con contexto</h2></header>${empty('Empieza por los datos que conoces.','El resultado separa la matemática de las hipótesis y señala los datos pendientes. No genera una cotización ni reemplaza una evaluación profesional.','','ϟ')}</section></div>`;
  $('#energy-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{
    const payload=Object.fromEntries([...fields].map(([key,value])=>[key,value===''?null:Number(value)]));
    const data=await post('/api/energy/calculate',payload);const results=data.results||{};
    const labels={monthly_kwh:['Consumo mensual','kWh'],annual_kwh:['Consumo anual','kWh'],system_kw:['Potencia nominal del sistema','kW'],system_watts:['Potencia nominal del sistema','W'],annual_production_kwh:['Producción anual estimada','kWh/año'],coverage_percent:['Cobertura preliminar','%'],required_system_kw:['Potencia para cobertura objetivo','kW'],required_panel_count:['Paneles para cobertura objetivo','paneles']};
    $('#energy-results').innerHTML=`<header class="panel-head"><div><p class="section-kicker">RESULTADO MATEMÁTICO</p><h2>Tu orientación preliminar</h2></div></header><div class="panel-body"><dl class="energy-result-list">${Object.entries(labels).filter(([key])=>results[key]!=null).map(([key,[label,unit]])=>`<div><dt>${esc(label)}</dt><dd>${amount(results[key],2)} <span>${esc(unit)}</span></dd></div>`).join('')||'<p class="field-help">Aún no hay datos suficientes para calcular.</p>'}</dl>${informationList('Hipótesis utilizadas',data.assumptions)}${informationList('Datos que faltan',data.missing)}${informationList('Limitaciones y revisión profesional',data.limitations)}<p class="hint orange">Requiere revisión humana. La producción, cobertura y cantidad de paneles son estimaciones bajo los parámetros ingresados; no son garantía de rendimiento o ahorro.</p></div>`;
  }));
}
function informationList(title,items) {return Array.isArray(items)&&items.length?`<section class="result-section"><h3>${esc(title)}</h3><ul>${items.map(item=>`<li>${esc(typeof item==='string'?item:JSON.stringify(item))}</li>`).join('')}</ul></section>`:'';}

async function renderPrivacy(requestId) {
  const data=await api('/api/privacy/requests');if(!current(requestId))return;
  state.privacyRequests=data.requests||[];state.canReviewPrivacy=!!data.can_review;
  const kinds={access:'Acceso a información',correction:'Corrección de datos',deletion:'Eliminación de datos'};
  const labels={pending:'Pendiente de revisión',reviewing:'En revisión',closed:'Cerrada'};
  content.innerHTML=heading('CONTROL Y TRAZABILIDAD','Solicitudes de privacidad','La baja de comunicaciones y las solicitudes sobre datos tienen procesos distintos.',actionButton('refresh','Actualizar solicitudes','',''))+
    `<aside class="privacy-policy-note"><strong>Una solicitud de eliminación no confirma un borrado.</strong><p>El equipo debe verificar identidad, revisar el alcance y documentar la decisión. Esta vista no borra datos automáticamente. La política de retención y las obligaciones aplicables requieren una decisión administrativa.</p></aside><section class="panel"><header class="panel-head"><h2>${state.canReviewPrivacy?'Bandeja de revisión administrativa':'Solicitudes de tus conversaciones'}</h2><span class="badge">${state.privacyRequests.length} solicitudes</span></header>${state.privacyRequests.length?`<div class="privacy-request-list">${state.privacyRequests.map(item=>`<article><div><p class="section-kicker">${esc(dateTime(item.created_at))}</p><h3>${esc(kinds[item.kind]||item.kind)}</h3><p>${esc(item.details||'Solicitud registrada desde el chat.')}</p><small>${item.identity_verified?'Identidad verificada por administración':'Identidad pendiente de verificación'}</small>${item.review_note?`<p class="review-note">${esc(item.review_note)}</p>`:''}</div><div class="actions">${badge(item.status==='closed'?'green':'orange',labels[item.status]||item.status)}${state.canReviewPrivacy?actionButton('review-privacy',item.status==='closed'?'Ver revisión':'Revisar solicitud',`data-id="${esc(item.id)}"`,'small'):''}</div></article>`).join('')}</div>`:empty('Sin solicitudes registradas.','El visitante puede solicitar acceso, corrección o eliminación desde su conversación. Las solicitudes quedan sujetas a revisión humana.','','◇')}</section>`;
}
async function privacyReview(id) {
  if(!state.canReviewPrivacy)return;
  const data=await api(`/api/privacy/requests/${encodeURIComponent(id)}`);const request=data.request;
  if(!request)return;
  const history=(request.history||[]).length?`<section class="result-section"><h3>Historial de revisiones</h3><ol class="audit-list">${request.history.map(item=>`<li><strong>${esc(item.status)}</strong><p>${esc(item.review_note||'Solicitud registrada')}</p><small>${esc(dateTime(item.created_at))} · ${item.identity_verified?'Identidad verificada':'Identidad sin verificar'}</small></li>`).join('')}</ol></section>`:'';
  if(request.status==='closed'){openDialog('Revisión cerrada',`<p class="hint">El cierre está registrado y no admite cambios. No implica borrado automático.</p><p class="review-note">${esc(request.review_note)}</p>${history}`);return;}
  openDialog('Revisar solicitud de privacidad',`<form id="privacy-review-form"><p class="field-help">Verifica la identidad y documenta el tratamiento. Cerrar registra una decisión administrativa; no ejecuta un borrado ni envía datos al solicitante.</p><div class="form-grid"><label class="span-2">Estado<select name="status">${options({pending:'Pendiente',reviewing:'En revisión',closed:'Cerrada'},request.status)}</select></label><label class="span-2 checkbox"><input type="checkbox" name="identity_verified" ${request.identity_verified?'checked':''}><span>He verificado la identidad mediante el procedimiento autorizado del equipo.</span></label><label class="span-2">Nota de revisión<textarea name="review_note" maxlength="3000" required>${esc(request.review_note||'')}</textarea></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Volver</button><button class="button primary" type="submit">Guardar revisión</button></div></form>${history}`);
  $('#privacy-review-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post(`/api/privacy/requests/${encodeURIComponent(id)}`,{status:fields.get('status'),review_note:fields.get('review_note'),identity_verified:fields.has('identity_verified')},'PATCH');closeDialog();toast('Revisión guardada. No se ejecutó un borrado.');await navigate('privacy',false);}));
}

async function leadBrief(id) {
  openDialog('Preparar orientación',loading());
  try {
    const data=await api(`/api/leads/${encodeURIComponent(id)}/brief`);if(!dialog.open)return;
    $('#dialog-content').innerHTML=`<p class="hint orange">Preparación interna basada en registros autorizados. Requiere revisión humana; no es una evaluación técnica certificada.</p><section class="result-section"><h3>Datos conocidos</h3><dl class="brief-known">${(data.known||[]).map(item=>`<div><dt>${esc(item.label)}</dt><dd>${esc(item.value)}</dd></div>`).join('')}</dl></section>${informationList('Información sin verificar',data.unverified)}${informationList('Preguntas pendientes',data.questions)}${informationList('Temas para explicar',data.topics)}${informationList('Próximas acciones sugeridas',data.next_actions)}<div class="form-actions">${actionButton('lead-detail','Volver a la ficha',`data-id="${esc(id)}"`,'small')}</div>`;
  } catch(error) {if(dialog.open)$('#dialog-content').innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p>`;}
}
const needUrgency={high:['red','Urgente'],normal:['orange','Pendiente'],low:['blue','Cuando se pueda']};
function needReportRow(report,reload) {
  const actions=node('div',{class:'actions'});
  const facts=node('div',{class:'need-facts'},(report.known||[]).map(
    item=>node('span',{class:'need-fact',text:`${item.label}: ${item.value}`})));
  const row=node('li',{class:`need-report urgency-${report.urgency}`},[
    node('div',{},[
      node('strong',{text:report.need}),
      node('blockquote',{text:report.question}),
      node('p',{text:`${report.reason_label}${report.repeats>1?` · lo preguntó ${report.repeats} veces`:''}${report.lead_name?` · ${report.lead_name}`:''}`}),
      (report.known||[]).length?facts:null,
      (report.missing||[]).length?node('small',{text:`Falta por preguntar: ${report.missing.join(', ')}`}):null,
    ]),
    node('div',{class:'need-tags'},[
      node('span',{class:`badge ${needUrgency[report.urgency][0]}`,text:needUrgency[report.urgency][1]}),
      report.status==='claimed'?node('span',{class:'badge',text:'En curso'}):null,
      actions,
    ]),
  ]);
  if(report.status!=='claimed') {
    const claim=node('button',{class:'button small',attrs:{type:'button'},text:'Atender'});
    claim.addEventListener('click',async()=>{
      claim.disabled=true;
      try {await post(`/api/needs/${encodeURIComponent(report.id)}/claim`,{});await reload();}
      catch(problem) {claim.disabled=false;toast(problem.message);}});
    actions.append(claim);
  }
  const close=node('button',{class:'button small primary',attrs:{type:'button'},text:'Cerrar'});
  close.addEventListener('click',()=>{
    const outcome=node('input',{attrs:{type:'text',maxlength:'400','aria-label':'Qué se hizo'}});
    const confirm=node('button',{class:'button small primary',attrs:{type:'submit'},text:'Guardar'});
    const form=node('form',{class:'need-close'},[node('label',{text:'Qué se hizo'},[outcome]),confirm]);
    form.addEventListener('submit',async event=>{
      event.preventDefault();confirm.disabled=true;
      try {await post(`/api/needs/${encodeURIComponent(report.id)}/resolve`,{resolution:outcome.value});await reload();}
      catch(problem) {confirm.disabled=false;toast(problem.message);}});
    actions.replaceChildren(form);outcome.focus();
  });
  actions.append(close);
  return row;
}
async function appendNeedQueue() {
  const parent=$('#view-content');
  const reload=async()=>{const old=$('#need-queue');if(old)old.remove();await appendNeedQueue();};
  try {
    const data=await api('/api/needs');
    if(state.view!=='conversations'||!state.user)return;
    const reports=data.reports||[];
    const section=node('section',{class:'panel need-panel'},[
      node('header',{class:'panel-head'},[
        node('div',{},[node('p',{class:'section-kicker',text:'MOTOR AUTÓNOMO / COLA HUMANA'}),
                       node('h2',{text:'Lo que están esperando'})]),
        node('span',{class:`badge ${reports.length?'orange':'green'}`,
          text:reports.length?`${reports.length} sin cerrar`:'Nadie esperando'}),
      ]),
      node('div',{class:'panel-body'},[
        reports.length
          ? node('ul',{class:'need-list'},reports.map(report=>needReportRow(report,reload)))
          : node('p',{class:'field-help',
              text:'Cuando el chat no pueda responder, aquí aparecerá qué necesita esa persona.'}),
        node('p',{class:'hint',text:data.notice||''}),
      ]),
    ]);
    section.id='need-queue';
    parent.insertBefore(section,parent.children[1]||null);
  } catch(problem) {
    if(state.view==='conversations')parent.append(node('p',{class:'field-help',
      text:`Cola de atención no disponible: ${problem.message}`}));
  }
}
const memoryStates={active:['green','Vigente'],superseded:['orange','Sustituida'],
  expired:['orange','Vencida'],retracted:['red','Retirada']};
function memoryOption(value,label,selected) {
  const option=node('option',{text:label});option.value=value;option.selected=!!selected;return option;
}
function memoryBeliefRow(belief,reload) {
  const actions=node('div',{class:'actions'});
  const row=node('li',{class:belief.usable?'is-usable':''},[
    node('div',{},[
      node('strong',{text:belief.claim}),
      node('p',{text:`${belief.subject_label} · ${belief.source_label} · confianza ${Math.round(Number(belief.confidence)*100)}%`}),
      node('small',{text:belief.retracted_reason
        ? `Retirada: ${belief.retracted_reason}`
        : `Observada ${dateTime(belief.observed_at)}${belief.expires_at?` · vence ${dateTime(belief.expires_at)}`:''}`}),
    ]),
    node('div',{class:'belief-tags'},[
      node('span',{class:`badge ${memoryStates[belief.state][0]}`,text:memoryStates[belief.state][1]}),
      belief.usable?null:node('span',{class:'badge',text:'No se usa al hablar'}),
      actions,
    ]),
  ]);
  if(belief.state!=='active')return row;
  if(!belief.usable) {
    const approve=node('button',{class:'button small',attrs:{type:'button'},text:'Aprobar su uso'});
    approve.addEventListener('click',async()=>{
      approve.disabled=true;
      try {await post(`/api/memory/${encodeURIComponent(belief.id)}/approve`,{});await reload();}
      catch(problem) {approve.disabled=false;toast(problem.message);}});
    actions.append(approve);
  }
  const retract=node('button',{class:'button small danger',attrs:{type:'button'},text:'Retirar'});
  retract.addEventListener('click',()=>{
    const reason=node('input',{attrs:{type:'text',maxlength:'200','aria-label':'Motivo para retirar'}});
    const confirm=node('button',{class:'button small danger',attrs:{type:'submit'},text:'Confirmar'});
    const form=node('form',{class:'belief-retract'},[
      node('label',{text:'Motivo'},[reason]),confirm]);
    form.addEventListener('submit',async event=>{
      event.preventDefault();confirm.disabled=true;
      try {await post(`/api/memory/${encodeURIComponent(belief.id)}/retract`,{reason:reason.value});await reload();}
      catch(problem) {confirm.disabled=false;toast(problem.message);}});
    actions.replaceChildren(form);reason.focus();
  });
  actions.append(retract);
  return row;
}
async function appendLeadMemory(leadId) {
  const parent=$('#dialog-content');
  if(!parent||!dialog.open)return;
  const reload=async()=>{const old=$('#lead-memory');if(old)old.remove();await appendLeadMemory(leadId);};
  try {
    const data=await api(`/api/leads/${encodeURIComponent(leadId)}/memory`);
    if(!dialog.open||state.activeLead?.id!==leadId)return;
    const beliefs=data.beliefs||[];
    const claim=node('textarea',{attrs:{name:'claim',required:'',maxlength:'400',
      placeholder:'Lo que sabemos, dicho con sus palabras.'}});
    const subject=node('select',{attrs:{name:'subject','aria-label':'Asunto'}},
      Object.entries(data.subjects||{}).map(([value,label])=>memoryOption(value,label,value==='motivo')));
    const source=node('select',{attrs:{name:'source_kind','aria-label':'De dónde viene'}},
      Object.entries(data.sources||{}).map(([value,label])=>memoryOption(value,label,value==='team_entered')));
    // La confianza se declara: una deducción guardada como certeza es justo la
    // clase de dato que después se repite como si fuera un hecho.
    const confidence=node('select',{attrs:{name:'confidence','aria-label':'Qué tan seguro'}},[
      memoryOption('1','Seguro',true),memoryOption('0.6','Probable'),memoryOption('0.3','Por confirmar')]);
    const error=node('p',{class:'form-error',attrs:{role:'alert'}});
    const save=node('button',{class:'button small',attrs:{type:'submit'},text:'Recordar'});
    const form=node('form',{class:'belief-form'},[
      node('label',{text:'Qué recordar'},[claim]),
      node('div',{class:'belief-form-row'},[
        node('label',{text:'Asunto'},[subject]),
        node('label',{text:'De dónde viene'},[source]),
        node('label',{text:'Qué tan seguro'},[confidence]),
        save,
      ]),
      error,
    ]);
    form.addEventListener('submit',async event=>{
      event.preventDefault();save.disabled=true;error.textContent='';
      try {
        await post(`/api/leads/${encodeURIComponent(leadId)}/memory`,
          {subject:subject.value,claim:claim.value,source_kind:source.value,
           confidence:Number(confidence.value)});
        await reload();
      } catch(problem) {error.textContent=problem.message;save.disabled=false;}
    });
    const section=node('section',{class:'panel lead-memory'},[]);
    section.id='lead-memory';
    section.append(
      node('header',{class:'panel-head'},[
        node('div',{},[node('p',{class:'section-kicker',text:'MEMORIA DEL AGENTE'}),
                       node('h3',{text:'Lo que R.E.I.G.E.L. recuerda'})]),
        node('span',{class:'badge',text:`${(data.usable||[]).length} en uso de ${beliefs.length}`}),
      ]),
      node('div',{class:'panel-body'},[
        form,
        beliefs.length
          ? node('ul',{class:'belief-list'},beliefs.map(belief=>memoryBeliefRow(belief,reload)))
          : node('p',{class:'field-help',text:'Todavía no hay nada recordado sobre esta persona.'}),
        node('p',{class:'hint',text:data.notice||''}),
      ]),
    );
    parent.append(section);
  } catch(problem) {
    if(dialog.open)parent.append(node('p',{class:'field-help',
      text:`Memoria del agente no disponible: ${problem.message}`}));
  }
}
const agentModes={auto:'Automático',approval:'Requiere aprobación',draft:'Borrador'};
const agentStatus={executed:'Hecho',planned:'En espera de una persona'};
// Este panel se construye con nodos y textContent, no con plantillas de HTML:
// muestra nombres escritos por un visitante y así no depende del escapado.
function node(tag,options={},children=[]) {
  const element=document.createElement(tag);
  if(options.class)element.className=options.class;
  if(options.text!==undefined)element.textContent=options.text;
  for(const [name,value] of Object.entries(options.attrs || {}))element.setAttribute(name,value);
  for(const child of children)if(child)element.append(child);
  return element;
}
function agentBadge(tone,label) {return node('span',{class:`badge ${tone}`,text:label});}
function agentCount(value,singular,plural) {const total=Number(value);return `${total} ${total===1?singular:plural}`;}
function agentCycleLine(cycle) {
  if(!cycle)return 'El motor todavía no ha completado una vuelta.';
  return `Última vuelta ${dateTime(cycle.started_at)}: ${agentCount(cycle.leads_seen,'registro revisado','registros revisados')}`
    +`, ${agentCount(cycle.decided,'decisión','decisiones')} (${Number(cycle.executed)} aplicadas, ${Number(cycle.held)} en espera).`;
}
function agentTitle(actions,name) {return (actions[name] && actions[name].title) || name;}
function agentDecisionList(decisions,actions) {
  if(!decisions.length)return node('p',{class:'field-help',text:'Ninguna decisión registrada todavía.'});
  return node('ul',{class:'agent-decisions'},decisions.slice(0,12).map(item=>node('li',{},[
    node('div',{},[node('strong',{text:agentTitle(actions,item.action)}),
                   node('p',{text:`${item.lead_name} · ${item.reason}`})]),
    agentBadge(item.status==='executed'?'green':'orange',agentStatus[item.status] || item.status),
  ])));
}
function agentPolicyRow(name,spec,mode,admin) {
  const effect=spec.effect==='task'?'Crea una tarea para el asesor':'Avisa a quien corresponde';
  let control;
  if(admin) {
    control=node('select',{attrs:{'data-agent-action':name,'aria-label':`Autorización de ${spec.title}`}},
      Object.entries(agentModes).map(([value,label])=>{
        const option=node('option',{text:label});option.value=value;option.selected=mode===value;return option;}));
  } else {
    control=node('span',{text:agentModes[mode] || mode});
  }
  return node('tr',{},[node('th',{attrs:{scope:'row'},text:spec.title}),node('td',{text:effect}),node('td',{},[control])]);
}
function agentPolicyTable(actions,modes,admin) {
  return node('table',{class:'agent-policy'},[
    node('caption',{text:'Qué puede hacer cada decisión y quién la autoriza'}),
    node('thead',{},[node('tr',{},['Decisión','Efecto','Autorización'].map(
      label=>node('th',{attrs:{scope:'col'},text:label})))]),
    node('tbody',{},Object.entries(actions).map(([name,spec])=>agentPolicyRow(name,spec,modes[name],admin))),
  ]);
}
function agentPlanView(plan,actions) {
  const rows=plan.decisions || [];
  return node('section',{class:'result-section'},[
    node('h3',{text:`Plan para ${agentCount(plan.leads_seen,'registro abierto','registros abiertos')}`}),
    node('p',{class:'field-help',text:'Esta vista no escribe nada: es lo que el motor decidiría ahora.'}),
    rows.length?node('ol',{class:'agent-plan'},rows.map(row=>node('li',{},[
      node('strong',{text:agentTitle(actions,row.action)}),
      node('span',{text:` · ${row.lead_name}`}),
      node('small',{text:`${row.reason} · ${agentModes[row.mode] || row.mode}`}),
    ]))):node('p',{class:'field-help',text:'No hay nada pendiente en la cartera.'}),
  ]);
}
async function appendAgentPanel() {
  const parent=$('#view-content');
  try {
    const [engine,registered]=await Promise.all([api('/api/agent'),api('/api/agent/decisions')]);
    if(state.view!=='automation'||!state.user)return;
    const admin=state.user.role==='admin',actions=engine.actions || {},modes=engine.modes || {};
    const cycleLine=node('p',{class:'status-inline',text:agentCycleLine((engine.cycles || [])[0])});
    const error=node('p',{class:'form-error',attrs:{role:'alert'}});
    const planResult=node('div',{attrs:{'aria-live':'polite'}});
    const switchButton=node('button',{class:`button ${engine.enabled?'':'primary'} small`,
      attrs:{type:'button'},text:engine.enabled?'Apagar el motor':'Encender el motor'});
    const planButton=node('button',{class:'button small',attrs:{type:'button'},text:'Ver el plan sin aplicarlo'});
    const runButton=node('button',{class:'button small',attrs:{type:'button'},text:'Ejecutar una vuelta ahora'});
    runButton.disabled=!engine.enabled;
    const section=node('section',{class:'panel agent-panel'},[
      node('header',{class:'panel-head'},[
        node('div',{},[node('p',{class:'section-kicker',text:'MOTOR AUTÓNOMO / CARTERA'}),
                       node('h2',{text:'Trabajo que abre por su cuenta'})]),
        agentBadge(engine.enabled?'green':'orange',engine.enabled?'Encendido':'Apagado'),
      ]),
      node('div',{class:'panel-body'},[
        cycleLine,
        admin?node('div',{class:'form-actions agent-controls'},[switchButton,planButton,runButton]):null,
        error,
        agentPolicyTable(actions,modes,admin),
        planResult,
        node('h3',{class:'agent-subhead',text:'Últimas decisiones'}),
        agentDecisionList(registered.decisions || [],actions),
        node('p',{class:'hint',text:`${engine.notice || ''} Cada decisión queda registrada con su motivo y no se repite el mismo día.`}),
      ]),
    ]);
    parent.append(section);
    if(!admin)return;
    const fail=problem=>{error.textContent=problem.message;};
    const reload=async()=>{if(state.view==='automation'&&section.parentNode){section.remove();await appendAgentPanel();}};
    switchButton.addEventListener('click',async()=>{
      try {await post('/api/agent/state',{enabled:!engine.enabled});await reload();} catch(problem) {fail(problem);}});
    runButton.addEventListener('click',async()=>{
      runButton.disabled=true;
      try {
        const result=await post('/api/agent/tick',{});error.textContent='';
        if(result.status==='disabled')cycleLine.textContent='El motor está apagado: la vuelta no hizo nada.';
        else await reload();
      } catch(problem) {fail(problem);runButton.disabled=false;}});
    planButton.addEventListener('click',async()=>{
      try {
        const plan=await api('/api/agent/preview');
        if(state.view!=='automation')return;
        planResult.replaceChildren(agentPlanView(plan,actions));
      } catch(problem) {fail(problem);}});
    for(const select of section.querySelectorAll('[data-agent-action]')) {
      select.addEventListener('change',async()=>{
        try {await post('/api/agent/policy',{action:select.dataset.agentAction,mode:select.value});error.textContent='';}
        catch(problem) {fail(problem);await reload();}});
    }
  } catch(problem) {
    if(state.view==='automation')parent.append(node('p',{class:'field-help',
      text:`Motor autónomo no disponible: ${problem.message}`}));
  }
}
async function appendTrainer() {
  const parent=$('#view-content');
  try {
    const data=await api('/api/assistant/scenarios');if(state.view!=='automation'||!state.user)return;
    const section=document.createElement('section');section.className='panel trainer-panel';
    section.innerHTML=`<header class="panel-head"><div><p class="section-kicker">SIMULACIÓN / FORMACIÓN</p><h2>Practica una conversación</h2></div>${badge('blue','Escenario ficticio')}</header><div class="panel-body"><form id="trainer-form"><label>Escenario<select name="scenario_id" id="trainer-scenario">${(data.scenarios||[]).map(item=>`<option value="${esc(item.id)}">${esc(item.title)}</option>`).join('')}</select></label><blockquote id="trainer-customer"></blockquote><label>Tu respuesta como asesor<textarea name="response" required maxlength="4000" placeholder="Escribe una respuesta clara y respetuosa para este caso simulado."></textarea></label><details class="trainer-rubric"><summary>Rúbrica utilizada</summary><ul>${(data.rubric||[]).map(item=>`<li><strong>${esc(item.label)}:</strong> ${esc(item.criterion)}</li>`).join('')}</ul></details><p class="form-error" role="alert"></p><div class="form-actions"><button class="button small" type="submit">Revisar mi respuesta</button></div></form><div id="trainer-results" aria-live="polite"></div></div>`;
    parent.append(section);
    const showScenario=()=>{const item=data.scenarios.find(scenario=>scenario.id===$('#trainer-scenario').value);$('#trainer-customer').textContent=item?.customer_message||'';};showScenario();$('#trainer-scenario').addEventListener('change',showScenario);
    $('#trainer-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{const result=await post('/api/assistant/train',{scenario_id:fields.get('scenario_id'),response:fields.get('response')});$('#trainer-results').innerHTML=`<section class="result-section"><h3>Revisión por reglas explícitas: ${esc(result.score)} / ${esc(result.max_score)}</h3><p class="field-help">Evaluación orientativa por heurísticas, sujeta a revisión humana. No mide el desempeño en una conversación real.</p><ul class="rubric-results">${(result.rubric||[]).map(item=>`<li><div><strong>${esc(item.label)}</strong><p>${esc(item.evidence)}</p></div><span>${esc(item.score)} / ${esc(item.max_score)}</span></li>`).join('')}</ul>${informationList('Sugerencias',result.feedback)}</section>`;}));
  }catch(error){if(state.view==='automation'){const message=document.createElement('p');message.className='field-help';message.textContent=`Entrenador no disponible: ${error.message}`;parent.append(message);}}
}

function operationActions(button) {
  const {id}=button.dataset;
  return {
    'retry-leads':filterOperationsLeads,
    'lead-view':()=>setLeadView(button.dataset.mode),
    'lead-page':()=>{state.leadQuery.offset=Number(button.dataset.offset)||0;return filterOperationsLeads();},
    'stage-leads':()=>{state.leadQuery.stage=button.dataset.stage;state.leadQuery.offset=0;return navigate('leads');},
    'task-page':()=>{state.taskOffset=Number(button.dataset.offset)||0;return navigate('tasks',false);},
    'notification-page':()=>{state.notificationOffset=Number(button.dataset.offset)||0;return navigate('notifications',false);},
    'new-task':()=>taskForm('',button.dataset.lead||''),
    'edit-task':()=>taskForm(id),
    'read-notification':async()=>{await post(`/api/notifications/${encodeURIComponent(id)}`,{read:true},'PATCH');await navigate('notifications',false);},
    'appointment-status':()=>appointmentStatusForm(id,button.dataset.status),
    'appointment-reminder':()=>appointmentReminderForm(id),
    'review-privacy':()=>privacyReview(id),
    'lead-brief':()=>leadBrief(id)
  };
}
