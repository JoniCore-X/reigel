'use strict';

// «Aprendizaje» en /app: cola de huecos con aprobación humana y último resultado del
// banco de preguntas. Usa las utilidades de app.js (api, post, esc, heading, ...).
// Los botones de administrador solo se muestran a administradores; el servidor
// vuelve a comprobar el permiso en cada acción.

const learningLabels = {
  status: {open:'Abierto',proposed:'Con propuesta',approved:'Aprobado',rejected:'Descartado',resolved:'Resuelto'},
  reason: {blocked:'Respuesta retirada',fallback:'Respuesta de respaldo',no_knowledge:'Sin fuente verificada',model_error:'Fallo del modelo',staff_flag:'Señalado por el equipo'},
  route: {ia:'/ia',chat:'/chat'},
  proposal: {pending:'Pendiente',approved:'Aprobada',rejected:'Rechazada',superseded:'Sustituida'},
};
const learningState = {status:'',route:''};

function learningCanReview() {return state.user?.role==='admin';}

function learningGapRow(gap) {
  const admin=learningCanReview();
  const open=gap.status==='open'||gap.status==='proposed';
  const buttons=[
    actionButton('learning-proposals','Ver propuestas',`data-id="${esc(gap.id)}"`,'small'),
    open?actionButton('learning-propose','Proponer respuesta',`data-id="${esc(gap.id)}"`,'small'):'',
    admin&&open?actionButton('learning-dismiss','Descartar hueco',`data-id="${esc(gap.id)}"`,'small'):'',
    admin&&gap.status==='approved'?actionButton('learning-resolve','Marcar resuelto',`data-id="${esc(gap.id)}"`,'small'):'',
  ].join('');
  return `<li class="learning-gap"><div class="learning-gap-main"><p class="learning-question">${esc(gap.question)}</p><p class="field-help">${esc(learningLabels.route[gap.route]||gap.route)} · ${esc(learningLabels.reason[gap.reason]||gap.reason)} · tema ${esc(gap.topic)} · ${esc(String(gap.occurrences))} ${gap.occurrences===1?'vez':'veces'} · última ${esc(gap.last_seen_local||'—')}</p></div><div class="learning-gap-side"><span class="badge" title="Prioridad heurística de 0 a 100">P ${esc(String(gap.priority))}</span>${badge(gap.status,learningLabels.status[gap.status]||gap.status)}${gap.pending_proposals?`<span class="badge">${esc(String(gap.pending_proposals))} por revisar</span>`:''}<div class="actions">${buttons}</div></div></li>`;
}

function learningEvalPanel(data) {
  const latest=data.latest;
  const run=data.can_run?actionButton('learning-run-eval',data.running?'Evaluación en curso…':'Ejecutar banco de preguntas',data.running?'disabled aria-disabled="true"':'','small'):'';
  const status=data.running?'<p class="field-help" role="status">El banco se está ejecutando contra el modelo local; puede tardar unos minutos.</p>':data.error?`<p class="form-error" role="alert">${esc(data.error)}</p>`:'';
  if(!latest)return `<section class="panel"><header class="panel-head"><h2>Banco de preguntas</h2>${run}</header><div class="panel-body">${status}${empty('Todavía no hay corridas.','Un administrador puede ejecutar el banco contra el modelo local configurado.','','?')}</div></section>`;
  const rows=(latest.results||[]).map(item=>`<li><strong>${item.ok?'Pasa':'Falla'}${item.replaced?' · sustituida':''}</strong> <span>${esc(item.case_id)}</span>${item.ok?'':`<p class="field-help">${esc((item.failed||[]).map(f=>f.description).join(' '))}</p><blockquote>${esc(item.published||'Sin respuesta')}</blockquote>`}</li>`).join('');
  return `<section class="panel"><header class="panel-head"><div><p class="section-kicker">ÚLTIMA CORRIDA · ${esc(latest.model)} · ${esc(latest.finished_local||'')}</p><h2>${esc(latest.summary)}</h2></div>${run}</header><div class="panel-body">${status}<ul class="learning-eval-list">${rows}</ul><p class="field-help">Las expectativas son patrones: detectan lo que describen, no sustituyen la revisión de una persona.</p></div></section>`;
}

async function renderLearning(requestId) {
  const query=new URLSearchParams({limit:'200'});
  if(learningState.status)query.set('status',learningState.status);
  if(learningState.route)query.set('route',learningState.route);
  const [data,evaluation]=await Promise.all([api(`/api/learning/gaps?${query}`),api('/api/learning/eval')]);
  if(!current(requestId))return;
  const gaps=data.gaps||[];
  const filters=`<form id="learning-filters" class="learning-filters"><label>Estado<select name="status">${options(learningLabels.status,learningState.status,'Todos')}</select></label><label>Ruta<select name="route">${options(learningLabels.route,learningState.route,'Todas')}</select></label><button class="button small" type="submit">Filtrar</button></form>`;
  content.innerHTML=heading('R.E.I.G.E.L. APRENDE CON TU REVISIÓN','Aprendizaje','Lo que R.E.I.G.E.L. no supo responder bien. El equipo propone y solo un administrador aprueba; nada llega a un cliente sin esa aprobación.',actionButton('learning-flag','Señalar una respuesta','','')+actionButton('refresh','Actualizar','',''))+
    learningEvalPanel(evaluation)+
    `<section class="panel"><header class="panel-head"><h2>${esc(String(data.total??gaps.length))} huecos</h2><span class="badge" title="${esc(data.priority_formula||'')}">Orden por prioridad heurística</span></header><div class="panel-body">${filters}${gaps.length?`<ul class="learning-gap-list">${gaps.map(learningGapRow).join('')}</ul>`:empty('Sin huecos en esta vista.','Cuando una respuesta se retire, use el respaldo o el equipo la señale, aparecerá aquí, sin datos de la persona.','','✓')}<p class="field-help">Las preguntas se guardan sin correos, teléfonos, direcciones, números largos ni nombres presentados. Los huecos no aprobados se borran a los 90 días; eso no sustituye las solicitudes de privacidad.</p></div></section>`;
  $('#learning-filters').addEventListener('submit',event=>{event.preventDefault();const fields=new FormData(event.currentTarget);learningState.status=fields.get('status')||'';learningState.route=fields.get('route')||'';navigate('learning',false);});
  if(evaluation.running)setTimeout(()=>{if(state.view==='learning'&&current(requestId))navigate('learning',false);},8000);
}

async function learningProposals(id) {
  openDialog('Propuestas para este hueco',loading());
  try {
    const data=await api(`/api/learning/gaps/${encodeURIComponent(id)}/proposals`);if(!dialog.open)return;
    const admin=learningCanReview();
    const items=data.proposals||[];
    $('#dialog-content').innerHTML=items.length?`<ol class="audit-list">${items.map(item=>`<li><strong>${esc(learningLabels.proposal[item.status]||item.status)}</strong><p>${esc(item.proposed_answer)}</p><small>Fuente o criterio: ${esc(item.source_note)} · ${esc(item.created_local||'')}</small>${item.review_note?`<p class="review-note">${esc(item.review_note)}</p>`:''}${admin&&item.status==='pending'?`<div class="actions">${actionButton('learning-approve','Aprobar',`data-id="${esc(item.id)}"`,'small')}${actionButton('learning-reject','Rechazar',`data-id="${esc(item.id)}"`,'small')}</div>`:''}</li>`).join('')}</ol>${admin?'<p class="field-help">Al aprobar, la respuesta pasa por los validadores públicos: sin cifras, precios, promesas, garantías, financiación ni contactos.</p>':'<p class="field-help">Solo un administrador puede aprobar o rechazar.</p>'}`:empty('Sin propuestas.','Propón una respuesta con su fuente o el criterio del equipo.','','?');
  } catch(error) {if(dialog.open)$('#dialog-content').innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p>`;}
}

function learningPropose(id) {
  openDialog('Proponer una respuesta',`<form id="learning-propose-form"><p class="field-help">Escribe la respuesta que R.E.I.G.E.L. debería dar, en tercera persona sobre el equipo y sin cifras, precios ni promesas. Un administrador la revisa antes de usarla.</p><label>Respuesta propuesta<textarea name="proposed_answer" required maxlength="900" rows="5"></textarea></label><label>Fuente oficial o criterio del equipo<input name="source_note" required maxlength="500"></label><p class="form-error" role="alert"></p><button class="button primary" type="submit">Enviar propuesta</button></form>`);
  $('#learning-propose-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post(`/api/learning/gaps/${encodeURIComponent(id)}/proposals`,{proposed_answer:fields.get('proposed_answer'),source_note:fields.get('source_note')});closeDialog();toast('Propuesta enviada para revisión.');await navigate('learning',false);}));
}

function learningDecision(id,kind) {
  const titles={approve:'Aprobar propuesta',reject:'Rechazar propuesta',dismiss:'Descartar hueco'};
  openDialog(titles[kind],`<form id="learning-decision-form"><label>Nota de revisión (opcional)<textarea name="note" maxlength="500" rows="3"></textarea></label><p class="form-error" role="alert"></p><button class="button primary" type="submit">${esc(titles[kind])}</button></form>`);
  $('#learning-decision-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{
    const path=kind==='dismiss'?`/api/learning/gaps/${encodeURIComponent(id)}/reject`:`/api/learning/proposals/${encodeURIComponent(id)}/${kind}`;
    await post(path,{note:fields.get('note')||''});closeDialog();toast(kind==='approve'?'Propuesta aprobada.':kind==='reject'?'Propuesta rechazada.':'Hueco descartado.');await navigate('learning',false);
  }));
}

function learningFlag() {
  openDialog('Señalar una respuesta',`<form id="learning-flag-form"><p class="field-help">Copia la pregunta de la persona, sin su nombre ni datos de contacto. Se oculta lo que parezca un dato personal antes de guardarla.</p><label>Dónde ocurrió<select name="route">${options(learningLabels.route,'ia')}</select></label><label>Pregunta<textarea name="question" required maxlength="2000" rows="3"></textarea></label><p class="form-error" role="alert"></p><button class="button primary" type="submit">Señalar</button></form>`);
  $('#learning-flag-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post('/api/learning/gaps',{route:fields.get('route'),question:fields.get('question')});closeDialog();toast('Hueco registrado en la cola.');await navigate('learning',false);}));
}

function learningActions(button) {
  const {id}=button.dataset;
  return {
    'learning-proposals':()=>learningProposals(id),
    'learning-propose':()=>learningPropose(id),
    'learning-approve':()=>learningDecision(id,'approve'),
    'learning-reject':()=>learningDecision(id,'reject'),
    'learning-dismiss':()=>learningDecision(id,'dismiss'),
    'learning-resolve':async()=>{await post(`/api/learning/gaps/${encodeURIComponent(id)}/resolve`,{});toast('Hueco marcado como resuelto.');await navigate('learning',false);},
    'learning-flag':learningFlag,
    'learning-run-eval':async()=>{button.disabled=true;await post('/api/learning/eval',{});toast('Banco de preguntas en curso.');await navigate('learning',false);},
  };
}
