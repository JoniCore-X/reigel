'use strict';

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const state = {user:null,view:'dashboard',leadView:'table',leads:[],users:[],appointments:[],conversations:[],tasks:[],settings:null,conversation:null,requestId:0,leadQuery:{q:'',stage:'',advisor_id:'',sort:'created_at',order:'desc',offset:0},taskQuery:{status:'pending',owner_id:''},dashboardPeriod:'month',dashboardStart:'',dashboardEnd:''};
const stages = {nuevo:'Prospecto nuevo',contacto_pendiente:'Contacto pendiente',contactado:'Contactado',calificado:'Interesado',cita:'Cita programada',cita_realizada:'Cita realizada',propuesta_preparacion:'Propuesta en preparación',propuesta_presentada:'Propuesta presentada',negociacion:'Negociación',ganado:'Ganado',perdido:'Perdido'};
const views = {dashboard:'Operaciones',leads:'Prospectos',tasks:'Tareas y seguimiento',appointments:'Agenda',notifications:'Notificaciones',energy:'Orientación energética',privacy:'Privacidad',conversations:'Conversaciones',automation:'R.E.I.G.E.L.',marketing:'Marketing',settings:'Equipo y ajustes',subscription:'Suscripción'};
const channels = {web:'Chat web propio',whatsapp:'WhatsApp',telegram:'Telegram',instagram:'Instagram',messenger:'Messenger',openai:'Inteligencia artificial',ai:'IA local'};
const statuses = {confirmed:'Confirmada',completed:'Realizada',no_show:'No asistió',cancelled:'Cancelada',sent:'Enviado',failed:'Falló el envío',uncertain:'Entrega sin confirmar',received:'Recibido',pending:'Pendiente'};
const weekdays = ['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];
const content = $('#view-content');
const dialog = $('#form-dialog');
let toastTimer;
let lastDialogTrigger;

function timezone() { return state.settings?.business?.timezone || 'America/Puerto_Rico'; }
function dateTime(value, options = {}) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('es-PR',{timeZone:timezone(),day:'numeric',month:'short',hour:'numeric',minute:'2-digit',...options}).format(date);
}
function time(value, zone = timezone()) { return new Intl.DateTimeFormat('es-PR',{timeZone:zone,hour:'numeric',minute:'2-digit'}).format(new Date(value)); }
function dateInput(offset = 0) {
  const date = new Date(Date.now() + offset * 86400000);
  return new Intl.DateTimeFormat('en-CA',{timeZone:timezone(),year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
}
function initials(name) {return String(name || 'PS').trim().split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();}
function badge(value, label = null) {return `<span class="badge ${esc(value)}">${esc(label || stages[value] || statuses[value] || value)}</span>`;}
function errorMessage(data) {
  if (typeof data?.detail === 'string') return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map(item=>`${item.loc?.at(-1) || 'Campo'}: ${item.msg || 'valor inválido'}`).join('. ');
  return 'No se pudo completar la solicitud. Intenta nuevamente.';
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(),60000);
  try {
    const response = await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...options.headers},signal:controller.signal});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) {
      if(response.status===401 && path!=='/api/auth/login') showLogin();
      const error = new Error(errorMessage(data)); error.status=response.status; throw error;
    }
    return data;
  } catch(error) {
    if (error.name==='AbortError') throw new Error('La solicitud tardó demasiado. Comprueba el estado antes de repetir un envío.');
    if (error instanceof TypeError) throw new Error('No hay conexión con el servidor. Comprueba que la app esté iniciada.');
    throw error;
  } finally { clearTimeout(timeout); }
}
function post(path,data,method='POST') {return api(path,{method,body:JSON.stringify(data)});}
function toast(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
function empty(title, text, action = '', symbol = '↗') {return `<div class="empty-state"><span class="empty-symbol" aria-hidden="true">${symbol}</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;}
function heading(kicker,title,copy,action='') {return `<div class="page-heading"><div><p class="eyebrow">${esc(kicker)}</p><h1>${esc(title)}</h1><p>${esc(copy)}</p></div>${action?`<div class="actions">${action}</div>`:''}</div>`;}
function actionButton(action,label,extra='',kind='primary') {return `<button type="button" class="button ${kind}" data-action="${esc(action)}" ${extra}>${esc(label)}</button>`;}
function loading() {return '<div class="loading" role="status">Cargando tu espacio…</div>';}
function fail(error) {content.innerHTML=`<div class="error-state" role="alert"><h2>No pudimos cargar esta vista.</h2><p>${esc(error.message)}</p>${actionButton('refresh','Volver a intentar')}</div>`;}
function showLogin() {state.user=null;$('#workspace').hidden=true;$('#login-screen').hidden=false;closeMenu();if(dialog.open)dialog.close();}
async function enter(user) {
  state.user=user;
  $('#login-screen').hidden=true;$('#workspace').hidden=false;
  $('#user-name').textContent=user.name;$('#user-role').textContent=roleLabel(user);$('[data-view="subscription"]').hidden=!user.is_owner;if(state.view==='subscription'&&!user.is_owner)state.view='dashboard';$('#user-avatar').textContent=initials(user.name);
  try {state.settings=await api('/api/settings');$('#business-zone').textContent=(state.settings.business?.market || 'Puerto Rico').toUpperCase();}catch {state.settings=null;}
  syncMenu();await navigate(state.view,false);
}
async function navigate(view, focus = true) {
  if (!views[view] || !state.user || (view==='subscription'&&!state.user.is_owner)) return;
  state.view=view;state.conversation=null;const requestId=++state.requestId;
  closeMenu();$('#current-page').textContent=views[view];document.title=`${views[view]} · R.E.I.G.E.L. — Team Caguas`;
  $$('.nav-item').forEach(item=>{item.classList.toggle('active',item.dataset.view===view);if(item.dataset.view===view)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');});
  content.innerHTML=loading();
  if (focus) $('#main').focus();
  try {
    const renderers={dashboard:renderDashboard,leads:renderLeads,tasks:renderTasks,notifications:renderNotifications,energy:renderEnergy,privacy:renderPrivacy,appointments:renderAppointments,conversations:renderConversations,automation:renderAutomation,marketing:renderMarketing,settings:renderSettings,subscription:renderSubscription};
    await renderers[view](requestId);
    if(view==='automation'&&current(requestId))await appendTrainer();
  }catch(error){if(requestId===state.requestId&&state.user)fail(error);}
}
function current(requestId) {return requestId===state.requestId && !!state.user;}
async function loadUsers() {const data=await api('/api/team');state.users=data.users || [];return state.users;}
async function loadLeads() {const data=await api('/api/leads?limit=500');state.leads=data.leads || [];state.leadTotal=data.total??state.leads.length;return state.leads;}

async function renderDashboard(requestId) {return renderOperationsDashboard(requestId);}
function dateTile(value) {const date=new Date(value);return `<div class="date-tile"><strong>${esc(new Intl.DateTimeFormat('es-PR',{timeZone:timezone(),day:'numeric'}).format(date))}</strong><span>${esc(new Intl.DateTimeFormat('es-PR',{timeZone:timezone(),month:'short'}).format(date))}</span></div>`;}

async function renderLeads(requestId) {return renderOperationsLeads(requestId);}
function openDialog(title,html) {if(!dialog.open)lastDialogTrigger=document.activeElement;dialog.classList.remove('wide-dialog');$('#dialog-title').textContent=title;$('#dialog-content').innerHTML=html;if(!dialog.open)dialog.showModal();}
function closeDialog() {dialog.close();if(lastDialogTrigger?.isConnected)lastDialogTrigger.focus();}
function formError(form,error) {const element=$('.form-error',form);if(element)element.textContent=error.message || String(error);}
async function submitForm(event,work) {
  event.preventDefault();const form=event.currentTarget;const button=$('[type=submit]',form);if(button?.disabled)return;
  const error=$('.form-error',form);if(error)error.textContent='';if(button)button.disabled=true;
  try {await work(form,new FormData(form));}catch(error){formError(form,error);}finally{if(button?.isConnected)button.disabled=false;}
}
function leadFields() {return operationsLeadFields();}
async function newLead() {return newOperationsLead();}
async function leadDetail(id) {return operationsLeadDetail(id);}
async function renderAppointments(requestId) {return renderOperationsAppointments(requestId);}
async function newAppointment(leadId='') {
  openDialog('Agendar una evaluación',loading());
  try {
    await Promise.all([loadLeads(),loadUsers()]);if(leadId&&!state.leads.some(lead=>lead.id===leadId)){const selected=await api(`/api/leads/${encodeURIComponent(leadId)}`);state.leads.unshift(selected.lead);}const advisors=state.users.filter(user=>user.active!==false&&user.public_booking&&(state.user.role==='admin'||user.id===state.user.id));
    if(!state.leads.length){$('#dialog-content').innerHTML=empty('Primero, un prospecto.','Registra el contacto antes de reservar una cita.',actionButton('new-lead','Crear prospecto','','small'));return;}
    if(!advisors.length){$('#dialog-content').innerHTML=empty('Define la disponibilidad primero.','Activa las reservas del asesor y su horario en Equipo y ajustes.','<button type="button" class="button small" data-action="availability">Ir a disponibilidad</button>','▦');return;}
    $('#dialog-content').innerHTML=`<form id="appointment-form"><div class="form-grid"><label class="span-2">Buscar prospecto<input type="search" id="appointment-lead-search" placeholder="Filtra por nombre, correo o teléfono"></label><label class="span-2">Prospecto<select name="lead_id" id="appointment-lead-select" required>${state.leads.map(lead=>`<option value="${esc(lead.id)}" ${lead.id===leadId?'selected':''}>${esc(lead.name)}</option>`).join('')}</select></label><label>Asesor<select id="appointment-advisor" name="advisor_id" required><option value="">Selecciona un asesor</option>${advisors.map(user=>`<option value="${esc(user.id)}">${esc(user.name)}</option>`).join('')}</select></label><label>Fecha<input type="date" id="appointment-date" required min="${dateInput()}" max="${dateInput(60)}" value="${dateInput(1)}"></label><p id="appointment-assignment-note" class="field-help span-2" role="status"></p><div class="span-2"><label>Horario disponible<input type="hidden" id="appointment-start" name="start_at"></label><div id="appointment-slots" class="slots" role="group" aria-label="Horarios disponibles"></div><p id="appointment-zone" class="calendar-zone"></p><p id="appointment-lead-search-status" class="field-help" role="status"></p></div></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" data-action="close-dialog" type="button">Cancelar</button><button class="button primary" type="submit">Confirmar cita</button></div></form>`;
    const updateSlots=()=>{
      const lead=state.leads.find(item=>item.id===$('#appointment-lead-select').value);
      const advisor=advisors.find(item=>item.id===$('#appointment-advisor').value);
      $('#appointment-assignment-note').textContent=!advisor?'Selecciona un asesor con disponibilidad.':lead&&lead.advisor_id!==advisor.id?`Al confirmar esta cita, ${advisor.name} será responsable del prospecto y de sus tareas pendientes.`:'';
      return loadSlots($('#appointment-advisor').value,$('#appointment-date').value,$('#appointment-slots'),$('#appointment-start'),$('#appointment-zone'));
    };
    const selectLeadAdvisor=()=>{
      const lead=state.leads.find(item=>item.id===$('#appointment-lead-select').value);
      const assigned=state.user.role==='admin'?lead?.advisor_id:state.user.id;
      $('#appointment-advisor').value=advisors.some(item=>item.id===assigned)?assigned:'';
      return updateSlots();
    };
    bindLeadSearch($('#appointment-lead-search'),$('#appointment-lead-select'),$('#appointment-lead-search-status'),'Selecciona un prospecto',selectLeadAdvisor);
    $('#appointment-lead-select').addEventListener('change',selectLeadAdvisor);
    $('#appointment-advisor').addEventListener('change',updateSlots);$('#appointment-date').addEventListener('change',updateSlots);await selectLeadAdvisor();
    $('#appointment-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{if(!data.get('start_at'))throw new Error('Selecciona un horario disponible.');await post('/api/appointments',{lead_id:data.get('lead_id'),advisor_id:data.get('advisor_id'),start_at:data.get('start_at')});closeDialog();toast('Cita confirmada en la agenda.');await navigate('appointments',false);}));
  }catch(error){$('#dialog-content').innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p>`;}
}
async function loadSlots(advisor,date,container,input,zoneElement) {
  input.value='';container.innerHTML='<p class="status-inline">Consultando horarios…</p>';const requestKey=`${advisor}-${date}`;container.dataset.request=requestKey;
  if(!advisor||!date){container.innerHTML='<p class="slot-empty">Elige un asesor y una fecha.</p>';return;}
  try {const data=await api(`/api/public/slots?advisor_id=${encodeURIComponent(advisor)}&date=${encodeURIComponent(date)}`);if(container.dataset.request!==requestKey)return;
    const zone=data.timezone || timezone();zoneElement.textContent=`Zona horaria: ${zone}`;
    container.innerHTML=(data.slots || []).length?data.slots.map(slot=>`<button type="button" class="slot-button" data-slot="${esc(slot.start_at)}" aria-pressed="false">${esc(time(slot.start_at,zone))}</button>`).join(''):'<p class="slot-empty span-2">No hay horarios disponibles para este día. Prueba otra fecha.</p>';
    $$('[data-slot]',container).forEach(button=>button.addEventListener('click',()=>{input.value=button.dataset.slot;$$('[data-slot]',container).forEach(other=>{other.classList.toggle('selected',other===button);other.setAttribute('aria-pressed',String(other===button));});}));
  }catch(error){if(container.dataset.request===requestKey)container.innerHTML=`<p class="form-error">${esc(error.message)}</p>`;}
}
async function cancelAppointment(id) {
  openDialog('Cancelar esta cita',`<p class="muted">El horario volverá a estar disponible. La cancelación se guarda en la agenda; avisa al prospecto por su canal habitual.</p><form id="cancel-form"><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" data-action="close-dialog" type="button">Conservar cita</button><button class="button danger" type="submit">Confirmar cancelación</button></div></form>`);
  $('#cancel-form').addEventListener('submit',event=>submitForm(event,async()=>{await post(`/api/appointments/${encodeURIComponent(id)}`,{status:'cancelled'},'PATCH');closeDialog();toast('Cita cancelada.');await navigate('appointments',false);}));
}

async function renderConversations(requestId) {
  const [data]=await Promise.all([api('/api/conversations'),loadUsers()]);if(!current(requestId))return;state.conversations=data.conversations || [];
  content.innerHTML=heading('UNA BANDEJA. MÁS CONTEXTO.','Conversaciones','Atiende a cada persona, toma el control humano y activa la IA cuando corresponda.',actionButton('refresh','Actualizar bandeja','',''))+
    `<section class="conversation-layout"><div class="conversation-list"><div class="panel-head"><h2>Mensajes recibidos</h2><span class="badge">${state.conversations.length}</span></div>${state.conversations.length?state.conversations.map(item=>`<button type="button" class="conversation-choice" data-action="open-conversation" data-id="${esc(item.id)}"><strong>${esc(item.contact_name || 'Nuevo contacto')}</strong><small>${esc(channels[item.channel] || item.channel)} · ${item.mode==='ai'?'Atención automática':'Atención humana'}</small><p>${esc(item.last_message || 'Abrir conversación')}</p></button>`).join(''):empty('Aquí empieza la conversación.','Las conversaciones del chat web aparecen aquí. Comparte la página de captación para comenzar.','','☷')}</div><div class="conversation-main" id="conversation-detail">${empty('Personas, no solo mensajes.','Selecciona una conversación para revisar su contexto y responder.','','☷')}</div></section>`;
}
async function openConversation(id) {
  const container=$('#conversation-detail');if(!container)return;state.conversation=id;container.innerHTML=loading();$$('.conversation-choice').forEach(button=>button.classList.toggle('active',button.dataset.id===id));
  try {const data=await api(`/api/conversations/${encodeURIComponent(id)}`);if(state.conversation!==id||!container.isConnected)return;const item=data.conversation;const messages=data.messages || [];
    container.innerHTML=`<header class="conversation-head"><div><h2>${esc(item.contact_name || 'Nuevo contacto')}</h2><p>${esc(channels[item.channel] || item.channel)} · ${item.mode==='ai'?'R.E.I.G.E.L. atiende los próximos mensajes':'Atención humana'}</p></div><button class="button small ${item.mode==='ai'?'':'primary'}" type="button" data-action="conversation-mode" data-id="${esc(id)}" data-mode="${item.mode==='ai'?'human':'ai'}">${item.mode==='ai'?'Tomar control humano':'Activar atención automática'}</button></header>${state.user.role==='admin'?`<form id="conversation-assignment" class="panel-body"><label>Responsable<select name="advisor_id"><option value="">Sin asignar</option>${state.users.filter(user=>user.active!==false).map(user=>`<option value="${esc(user.id)}" ${item.advisor_id===user.id?'selected':''}>${esc(user.name)}</option>`).join('')}</select></label><div class="actions"><button class="button small" type="submit">Guardar responsable</button><p class="form-error" role="alert"></p></div></form>`:''}<div class="message-log" role="log" aria-label="Historial de la conversación">${messages.length?messages.map(message=>`<article class="message ${message.direction==='outbound'?'outbound':'inbound'}"><p class="message-text">${esc(message.text)}</p><small>${esc(dateTime(message.created_at))}${message.direction==='outbound'?` · ${esc(statuses[message.status] || message.status)}`:''}</small></article>`).join(''):empty('Todavía no hay mensajes.','El historial se conserva por conversación.','','☷')}</div><form class="composer" id="message-form"><label>Tu respuesta<textarea name="text" required maxlength="4000" aria-label="Tomar control humano: responder conversación" placeholder="Escribe una respuesta para esta persona…"></textarea></label><p class="form-error" role="alert"></p><div class="composer-footer"><small>Se envía por ${esc(channels[item.channel] || item.channel)}. Comprueba el estado de entrega.</small><button class="button primary small" type="submit">Enviar respuesta ↗</button></div></form>`;
    const log=$('.message-log',container);log.scrollTop=log.scrollHeight;
    $('#conversation-assignment')?.addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post(`/api/conversations/${encodeURIComponent(id)}`,{advisor_id:fields.get('advisor_id')||null},'PATCH');toast('Responsable actualizado.');}));
    $('#message-form').addEventListener('submit',event=>submitForm(event,async(form,fields)=>{await post(`/api/conversations/${encodeURIComponent(id)}/messages`,{text:fields.get('text')});toast(item.channel==='web'?'Respuesta guardada en el chat del cliente.':'Respuesta enviada al proveedor.');await openConversation(id);}));
  }catch(error){if(state.conversation===id&&container.isConnected)container.innerHTML=`<div class="error-state" role="alert"><p>${esc(error.message)}</p>${actionButton('open-conversation','Volver a intentar',`data-id="${esc(id)}"`,'small')}</div>`;}
}
async function conversationMode(id,mode,button) {
  button.disabled=true;try{await post(`/api/conversations/${encodeURIComponent(id)}/mode`,{mode});toast(mode==='human'?'Control humano activado.':'Atención automática activada para los próximos mensajes entrantes.');await openConversation(id);}catch(error){toast(error.message);button.disabled=false;}
}

const campaignTemplates = [
  {tag:'CAPTACIÓN · INSTAGRAM / FACEBOOK',title:'Primero, entiende tus opciones.',text:'Tu factura de luz merece una conversación con números claros. En Power Solar revisamos tu consumo, las características de tu hogar y tus prioridades para explorar si una solución solar tiene sentido para ti.\n\nAgenda una evaluación y toma tu próxima decisión con más información.\n\n[ENLACE DE CAPTACIÓN]'},
  {tag:'CONFIANZA · WHATSAPP / MESSENGER',title:'Seguimiento con permiso.',text:'Hola, [NOMBRE]. Soy [ASESOR] del equipo de Power Solar. Nos autorizaste a contactarte sobre una evaluación solar. ¿Qué te interesa resolver primero: entender tu consumo, explorar respaldo o conocer opciones para tu hogar?\n\nSi prefieres que no te contactemos, indícamelo y respetamos tu decisión.'},
  {tag:'EDUCACIÓN · TELEGRAM / REDES',title:'Tres preguntas antes de decidir.',text:'Antes de elegir un sistema solar, pregunta:\n1. ¿Cómo se calculó la producción estimada para mi hogar?\n2. ¿Qué cubren la propuesta, las garantías y el mantenimiento?\n3. ¿Cómo cambian los costos según mi consumo y las condiciones de financiación?\n\nEn Power Solar empezamos por entender tu situación. Solicita una evaluación: [ENLACE DE CAPTACIÓN]'},
  {tag:'REACTIVACIÓN · CONTACTOS AUTORIZADOS',title:'Una invitación sin presión.',text:'Hola, [NOMBRE]. Retomo nuestra conversación sobre las opciones de energía para tu hogar. Si todavía estás evaluando, podemos revisar tus dudas y coordinar un horario que te funcione.\n\nAquí puedes consultar los espacios disponibles: [ENLACE DE CAPTACIÓN]\n\nSi ya no te interesa, dime y cierro el seguimiento.'}
];
async function renderMarketing(requestId) {
  if(!current(requestId))return;
  content.innerHTML=heading('CLARIDAD QUE CONECTA','Marketing','Mensajes útiles, seguimiento con permiso y un generador de enlaces con parámetros UTM.')+
    `<section class="marketing-feature"><div><p class="eyebrow">DE LA PRIMERA PREGUNTA A LA CITA</p><h2>Persuade con contexto.<br>Construye confianza con claridad.</h2><p>Parte del problema de la persona, explica el siguiente paso y ofrece una evaluación. Personaliza cada mensaje antes de compartirlo.</p></div><div><div class="marketing-label">ESCUCHAR → ORIENTAR<strong>INVITAR A CONVERSAR ↗</strong>EL ENLACE CIERRA EL RECORRIDO</div></div></section>
    <div class="marketing-grid">${campaignTemplates.map((template,index)=>`<article class="copy-card"><span class="tagline">${template.tag}</span><h3>${template.title}</h3><p class="copy-content">${esc(template.text)}</p>${actionButton('copy-template','Copiar mensaje',`data-index="${index}"`,'small')}</article>`).join('')}</div>
    <div class="marketing-tools"><section class="panel"><header class="panel-head"><div><p class="section-kicker">PREPARA TU ENLACE</p><h2>Enlace de campaña con UTM</h2></div></header><div class="panel-body"><form id="utm-form"><div class="form-grid"><label class="span-2">URL de la página de captación<input name="url" type="url" required value="${esc(state.settings?.business?.site_url || location.origin+'/')}" placeholder="https://tudominio.com/"></label><label>Origen<input name="source" required maxlength="80" placeholder="instagram"></label><label>Medio<input name="medium" required maxlength="80" value="organic_social"></label><label class="span-2">Campaña<input name="campaign" required maxlength="100" placeholder="evaluacion_solar_octubre"></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary small" type="submit">Generar enlace</button></div></form><div id="utm-result" hidden><p class="result-box" id="utm-link"></p><button class="text-link" type="button" data-action="copy-utm">Copiar enlace ↗</button></div><p class="field-help">Los parámetros UTM se añaden al enlace. El seguimiento de origen aún no está integrado en el chat ni en el formulario de Google. Los enlaces locales funcionan solo en este equipo; para captar desde redes necesitas publicar la app con un dominio.</p></div></section>
    <section class="panel"><header class="panel-head"><div><p class="section-kicker">UN BORRADOR, CON TU CRITERIO</p><h2>Asistente de contenido</h2></div></header><div class="panel-body"><form id="draft-form"><label>¿Qué necesitas redactar?<textarea name="prompt" required maxlength="3000" placeholder="Un mensaje breve para una persona que pregunta por respaldo durante apagones. Sin prometer autonomía ni ahorros garantizados."></textarea></label><p class="field-help">El modelo local redacta en esta computadora. Revisa sus afirmaciones antes de usar el borrador. Esta acción no publica ni envía mensajes.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary small" type="submit">Crear borrador local</button></div></form><div id="draft-result" hidden><p id="draft-text" class="result-box"></p><button class="text-link" type="button" data-action="copy-draft">Copiar borrador ↗</button></div></div></section></div>
    <section class="panel faq-compact"><header class="panel-head"><h2>Conversaciones que generan confianza</h2></header><div class="panel-body"><details><summary>“¿Cuánto voy a ahorrar?”</summary><p>Depende del consumo, la producción estimada, la tarifa, el sistema y las condiciones de la propuesta. Invita a revisar esos datos; no prometas una cifra antes del análisis.</p></details><details><summary>“¿Funciona si se va la luz?”</summary><p>El respaldo depende del diseño, la batería, las cargas y la instalación. Un sistema conectado a la red no implica respaldo por sí solo. Confirma las especificaciones de la solución propuesta.</p></details><details><summary>“¿Tengo que decidir ahora?”</summary><p>La evaluación es un espacio para comprender opciones. Comparte el alcance y los próximos pasos, y permite que la persona decida con información. Evita urgencias o incentivos que no estén confirmados.</p></details></div></section>`;
  $('#utm-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{const url=new URL(data.get('url'));if(!['https:','http:'].includes(url.protocol))throw new Error('Usa una URL http o https.');url.searchParams.set('utm_source',data.get('source').trim());url.searchParams.set('utm_medium',data.get('medium').trim());url.searchParams.set('utm_campaign',data.get('campaign').trim());$('#utm-link').textContent=url.toString();$('#utm-result').hidden=false;}));
  $('#draft-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{const result=await post('/api/assistant/draft',{prompt:data.get('prompt')});$('#draft-text').textContent=result.text || '';$('#draft-result').hidden=false;}));
}
async function copy(text) {try{await navigator.clipboard.writeText(text);toast('Copiado. Personaliza el mensaje antes de compartirlo.');}catch{openDialog('Copia este contenido',`<label>Contenido<textarea id="copy-fallback" readonly>${esc(text)}</textarea></label><p class="field-help">Selecciona el texto y usa Ctrl+C o la opción Copiar de tu dispositivo.</p>`);$('#copy-fallback').select();}}

function integrationRows(integrations) {
  const list=Array.isArray(integrations)?integrations:Object.entries(integrations || {}).map(([id,item])=>({id,...(typeof item==='object'?item:{configured:!!item})}));
  return list.map(item=>{const name=item.name || item.label || channels[item.id || item.channel] || item.id || item.channel || 'Servicio';const configured=Boolean(item.configured || item.status==='configured');const local=item.status==='local',blocked=item.status==='blocked_cost_policy',model=item.status==='local_check_required';const label=local?'Local · activo':blocked?'Bloqueado por costo':model?'Verificar modelo':configured?'Configurado · sin verificar':'Por conectar';return `<div class="integration-row"><div><strong>${esc(name)}</strong><p>${esc(item.detail || item.description || (configured?'Configuración presente. Falta verificar la conexión real.':'Configura la cuenta y sus credenciales en el servidor.'))}</p></div>${badge(local?'green':blocked?'orange':'blue',label)}</div>`;}).join('') || '<p class="field-help">No se pudo leer el estado de las integraciones.</p>';
}

function freshnessLabel(status) {
  return ({fresh:'Información vigente',cached:'Copia vigente · consulta falló',stale:'Revisión vencida',partial:'Revisión parcial',unavailable:'Sin información verificable',ok:'Revisada',error:'No se pudo revisar',changed:'Cambio detectado',pending:'Pendiente',blocked:'Acceso bloqueado'})[status] || 'Pendiente de revisión';
}
function safeSourceLink(value,label) {
  try { const url=new URL(value);if(url.protocol==='https:')return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(label || url.hostname)} ↗</a>`; } catch {}
  return '<span class="field-help">Fuente sin enlace disponible</span>';
}
function knowledgeContent(knowledge) {
  const sources=Array.isArray(knowledge.sources)?knowledge.sources:[];
  return `<div class="knowledge-summary"><span class="badge ${knowledge.status==='fresh'?'green':'orange'}">${esc(freshnessLabel(knowledge.status))}</span><p class="status-inline">Última revisión válida: ${knowledge.checked_at?esc(dateTime(knowledge.checked_at)):'aún no realizada'}.${knowledge.last_attempt_at?` Último intento: ${esc(dateTime(knowledge.last_attempt_at))}.`:''}${knowledge.valid_until?` Vigencia hasta ${esc(dateTime(knowledge.valid_until))}.`:''}</p><p class="field-help">${esc(knowledge.notice || 'Las fuentes se revisan mientras el servidor tiene conexión. La ausencia de datos nuevos no confirma que una oferta siga vigente.')}</p></div>${sources.length?sources.map(source=>`<article class="knowledge-source"><div><h3>${esc(source.title || source.name || 'Fuente de Power Solar')}</h3>${safeSourceLink(source.url)}<p>${esc(source.last_error || source.notice || (source.available?'Contenido disponible para consulta. Las condiciones comerciales requieren verificación.':'No hay contenido vigente disponible de esta fuente.'))}</p><small>Revisada: ${source.checked_at?esc(dateTime(source.checked_at)):'sin revisar'}${source.changed_at?` · Cambio detectado: ${esc(dateTime(source.changed_at))}`:''}${source.valid_until?` · Vigencia: ${esc(dateTime(source.valid_until))}`:''}${source.verification_method?` · Método: ${esc(({direct_http:'consulta directa al sitio',web_search:'fragmentos de búsqueda',search_excerpt:'fragmentos de búsqueda',web_review:'revisión web con fuentes'})[source.verification_method] || source.verification_method)}`:''}</small></div><span class="badge ${source.available&&source.status==='fresh'?'green':'orange'}">${esc(freshnessLabel(source.status))}</span></article>`).join(''):empty('Todavía no hay fuentes disponibles.','El sistema necesita completar una consulta a las fuentes permitidas antes de usar información comercial actualizada.','','◎')}`;
}
async function renderAutomation(requestId) {
  const data=await api('/api/automation');if(!current(requestId))return;
  const knowledge=data.knowledge || {},model=data.local_model || {},booking=data.booking || {},admin=state.user.role==='admin';
  const modelAvailable=model.status==='available';
  content.innerHTML=heading('TECNOLOGÍA PROPIA, CON CRITERIO','R.E.I.G.E.L.','Tu asistente comercial, su conocimiento y la agenda que convierte interés en citas.',`<a class="button primary" href="/" target="_blank" rel="noopener">Abrir chat de clientes ↗</a>`)+
    `<section class="automation-intro"><div><h2>Escucha. Orienta. Coordina.</h2><p>El chat web responde con un motor comercial propio, maneja dudas y conecta al cliente con horarios reales. El equipo conserva el control de la conversación y de cada propuesta.</p></div><span class="chat-emblem" aria-hidden="true">R.</span></section>
    <div class="automation-facts"><article class="automation-fact"><small>ATENCIÓN WEB</small><strong>${data.chat==='active'?'Motor comercial activo':'Estado por verificar'}</strong><p>Conversaciones guardadas en tu sistema, con atención humana desde la bandeja.</p></article><article class="automation-fact"><small>RESERVAS AUTOMÁTICAS</small><strong>${Number(booking.public_advisors || 0)} ${Number(booking.public_advisors || 0)===1?'asesor con horarios':'asesores con horarios'}</strong><p>${Number(booking.public_advisors || 0)?'El cliente elige y confirma. El servidor valida que no se crucen citas.':'Publica la disponibilidad de un asesor en Equipo y ajustes para recibir citas.'}</p></article><article class="automation-fact"><small>MODELO GENERATIVO LOCAL</small><strong>${modelAvailable?esc(model.model || 'Modelo disponible'):model.status==='model_missing'?'Modelo pendiente':'Modelo sin conexión'}</strong><p>${modelAvailable?'Borradores en esta computadora, sujetos a revisión antes de enviarlos.':'El motor comercial puede seguir atendiendo. Los borradores necesitan un modelo local disponible.'}</p></article></div>
    <section class="panel"><header class="panel-head"><div><p class="section-kicker">POWER SOLAR / INFORMACIÓN Y FUENTES</p><h2>Lo que R.E.I.G.E.L. puede verificar</h2></div>${admin?actionButton('refresh-knowledge','Revisar ahora','','small'):''}</header><div class="panel-body"><div id="knowledge-content">${knowledgeContent(knowledge)}</div><p class="automation-error" id="knowledge-error" role="alert"></p><p class="hint">Revisión automática cada ${Math.round(Number(knowledge.refresh_interval_seconds || 21600)/3600)} horas con el servidor encendido y conexión a Internet. El contenido vence después de ${Number(knowledge.ttl_hours || 24)} horas sin revisión válida. No se inventan precios, ahorros ni promociones para cubrir información faltante.</p></div></section>
    <section class="panel faq-compact"><header class="panel-head"><h2>Tu operación, bajo tu control</h2></header><div class="panel-body"><p class="field-help">${esc(data.notice || 'El chat y la agenda funcionan en tu servidor. Una venta requiere que el cliente acepte una propuesta.')}</p><div class="automation-help"><button type="button" class="text-link" data-view="conversations">Atender conversaciones ↗</button><button type="button" class="text-link" data-view="settings">Configurar horarios ↗</button><button type="button" class="text-link" data-view="marketing">Preparar borrador local ↗</button></div></div></section>`;
}
async function refreshKnowledge(button) {
  if(button.disabled)return;
  button.disabled=true;button.textContent='Revisando fuentes…';
  $('#knowledge-error').textContent='';
  try {const data=await post('/api/knowledge/refresh',{});if($('#knowledge-content'))$('#knowledge-content').innerHTML=knowledgeContent(data.knowledge || data);toast(data.status==='fresh'?'Fuentes revisadas.':'Revisión completada. Comprueba el estado de cada fuente.');}
  catch(error){if($('#knowledge-error'))$('#knowledge-error').textContent=error.message;}
  finally{if(button.isConnected){button.disabled=false;button.textContent='Revisar ahora';}}
}
async function renderSettings(requestId) {
  const [settings]=await Promise.all([api('/api/settings'),loadUsers()]);if(!current(requestId))return;state.settings=settings;const business=settings.business || {};const admin=state.user.role==='admin';
  content.innerHTML=heading('UN EQUIPO, UN RUMBO','Equipo y ajustes','Cuentas, horarios y conexiones que sostienen tu operación.',admin?actionButton('new-user',state.user.is_owner?'+ Añadir persona':'+ Añadir asesor'):'')+
    `<div class="settings-grid"><div class="settings-stack"><section class="panel"><header class="panel-head"><div><p class="section-kicker">PERSONAS Y DISPONIBILIDAD</p><h2>${admin?'Tu equipo':'Mi disponibilidad'}</h2></div><span class="badge">${state.users.length}</span></header><div class="panel-body"><div class="team-list">${state.users.map(user=>`<article class="team-member"><span class="avatar">${esc(initials(user.name))}</span><div><strong>${esc(user.name)}</strong><p>${esc(user.email)}</p>${badge(user.public_booking?'green':'orange',user.public_booking?'Recibe reservas':'Reservas desactivadas')}${badge(user.is_owner?'orange':'blue',roleLabel(user))}${user.active===false?badge('red','Dado de baja'):''}</div><div class="team-actions">${actionButton('edit-user','Horario',`data-id="${esc(user.id)}"`,'small')}${canOffboard(user)?actionButton('offboard-user','Dar de baja',`data-id="${esc(user.id)}"`,'small danger'):''}</div></article>`).join('')}</div><p class="field-help">Cada asesor define horas, días y duración de las citas. Solo los asesores activos con reservas habilitadas aparecen en la página pública.</p></div></section>
    <section class="panel"><header class="panel-head"><div><p class="section-kicker">IDENTIDAD Y CAPTACIÓN</p><h2>Tu negocio</h2></div></header><div class="panel-body">${admin?`<form id="business-form"><div class="form-grid"><label class="span-2">Nombre comercial<input name="name" required maxlength="120" value="${esc(business.name || 'Power Solar')}"></label><label>Mercado<input name="market" required maxlength="100" value="${esc(business.market || 'Puerto Rico')}"></label><label>Zona horaria<input name="timezone" required value="${esc(business.timezone || 'America/Puerto_Rico')}"></label><label class="span-2">Contacto para privacidad<input name="privacy_contact" maxlength="254" value="${esc(business.privacy_contact || '')}" placeholder="Correo de atención de tu empresa"></label><label class="span-2">URL pública de la app<input name="site_url" type="url" value="${esc(business.site_url || '')}" placeholder="https://tudominio.com/"><span class="field-help">Añádela cuando exista un dominio publicado. Se usa en los enlaces y el SEO.</span></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button primary small" type="submit">Guardar negocio</button></div></form>`:`<div class="detail-summary"><div><small>NEGOCIO</small><p>${esc(business.name || 'Power Solar')}</p></div><div><small>MERCADO</small><p>${esc(business.market || 'Puerto Rico')}</p></div><div><small>ZONA HORARIA</small><p>${esc(business.timezone || timezone())}</p></div></div><p class="field-help">El administrador gestiona la identidad del negocio.</p>`}</div></section></div>
    <div class="settings-stack"><section class="panel"><header class="panel-head"><div><p class="section-kicker">CANALES E INTELIGENCIA ARTIFICIAL</p><h2>Conexiones</h2></div></header><div class="panel-body"><div class="integration-list">${integrationRows(settings.integrations)}</div><p class="hint orange">El chat web funciona en tu servidor. Los canales bloqueados no envían mensajes. Una conexión externa configurada todavía requiere verificar su funcionamiento real.</p>${admin?'<p class="field-help">Las credenciales se configuran en el servidor, fuera del navegador. Consulta la guía de integraciones del proyecto para conectar cada cuenta.</p>':''}</div></section><section class="panel"><header class="panel-head"><div><p class="section-kicker">ACCESO PERSONAL</p><h2>Cambiar contraseña</h2></div></header><div class="panel-body"><form id="password-form"><div class="form-grid"><label class="span-2">Contraseña actual<input name="current_password" type="password" autocomplete="current-password" required></label><label class="span-2">Nueva contraseña<input name="new_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><span class="field-help">Usa al menos 12 caracteres y una contraseña única.</span></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button small" type="submit">Actualizar contraseña</button></div></form></div></section></div></div>`;
  $('#business-form')?.addEventListener('submit',event=>submitForm(event,async(form,data)=>{await post('/api/settings',Object.fromEntries(data),'PATCH');toast('Información del negocio actualizada.');await navigate('settings',false);}));
  $('#password-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{await post('/api/auth/password',Object.fromEntries(data));form.reset();showLogin();toast('Contraseña actualizada. Inicia sesión con tu nueva contraseña.');}));
}
function newUser() {
  openDialog('Añadir persona al equipo',`<form id="user-form"><div class="form-grid"><label class="span-2">Nombre completo<input name="name" required maxlength="120" autocomplete="off"></label><label class="span-2">Correo electrónico<input name="email" type="email" required autocomplete="off"></label><label class="span-2">Contraseña inicial<input name="password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"><span class="field-help">Compártela con el asesor por un canal privado. Podrá cambiarla al entrar.</span></label>${state.user.is_owner?'<label class="span-2">Rol<select name="role"><option value="advisor">Asesor</option><option value="admin">Administrador del equipo</option></select><span class="field-help">Un administrador gestiona asesores y ajustes; no ve la suscripción ni puede dar de baja a otros administradores.</span></label>':''}</div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Cancelar</button><button class="button primary" type="submit">Crear cuenta</button></div></form>`);
  $('#user-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{await post('/api/team',{...Object.fromEntries(data),role:data.get('role')||'advisor'});form.reset();closeDialog();toast('Cuenta creada.');await navigate('settings',false);}));
}
function parseDays(days) {if(Array.isArray(days))return days;if(typeof days==='string'){try{return JSON.parse(days);}catch{return days.split(',').map(Number);}}return [0,1,2,3,4];}
function editUser(id) {
  const user=state.users.find(item=>item.id===id);if(!user)return;const days=parseDays(user.work_days);const admin=state.user.role==='admin';const reactivable=admin&&user.active===false&&user.id!==state.user.id&&(user.role!=='admin'||state.user.is_owner);
  openDialog(`Disponibilidad · ${user.name}`,`<form id="availability-form"><div class="form-grid">${admin?`<label class="span-2">Nombre<input name="name" required maxlength="120" value="${esc(user.name)}"></label>`:''}<label class="span-2 checkbox"><input name="public_booking" type="checkbox" ${user.public_booking?'checked':''}><span>Recibir reservas desde la página de captación. Se mostrará el nombre del asesor y sus horarios disponibles.</span></label><label>Inicio de jornada<input name="work_start" type="time" required value="${esc(user.work_start || '09:00')}"></label><label>Fin de jornada<input name="work_end" type="time" required value="${esc(user.work_end || '17:00')}"></label><label>Duración de cada cita<select name="duration_minutes">${[15,30,45,60,90,120].map(duration=>`<option value="${duration}" ${Number(user.duration_minutes || 30)===duration?'selected':''}>${duration} minutos</option>`).join('')}</select></label><label>Zona horaria<input name="timezone" required value="${esc(user.timezone || 'America/Puerto_Rico')}"></label><div class="span-2"><label>Días de atención</label><div class="day-options">${weekdays.map((day,index)=>`<label><input type="checkbox" name="work_days" value="${index}" ${days.includes(index)?'checked':''}>${day}</label>`).join('')}</div></div>${reactivable?'<label class="span-2 checkbox"><input name="active" type="checkbox"><span>Reactivar esta cuenta. Sus prospectos anteriores no regresan solos.</span></label>':''}</div><p class="hint">Las reservas requieren al menos una hora de anticipación y admiten fechas dentro de los próximos 60 días. Las citas confirmadas bloquean el horario.</p><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Cancelar</button><button class="button primary" type="submit">Guardar disponibilidad</button></div></form>`);
  $('#availability-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{const payload={public_booking:data.has('public_booking'),work_start:data.get('work_start'),work_end:data.get('work_end'),duration_minutes:Number(data.get('duration_minutes')),timezone:data.get('timezone'),work_days:data.getAll('work_days').map(Number)};if(admin)payload.name=data.get('name');if(reactivable&&data.has('active'))payload.active=true;await post(`/api/team/${encodeURIComponent(id)}`,payload,'PATCH');closeDialog();toast('Disponibilidad actualizada.');await navigate('settings',false);}));
}

function roleLabel(user) {return user?.is_owner?'Propietario':user?.role==='admin'?'Administrador':'Asesor';}
function canOffboard(user) {const me=state.user;return me?.role==='admin'&&user.active!==false&&user.id!==me.id&&!user.is_owner&&(user.role!=='admin'||me.is_owner);}
function offboardUser(id) {
  const user=state.users.find(item=>item.id===id);if(!user)return;
  const options=state.users.filter(item=>item.active!==false&&item.id!==id);
  openDialog(`Dar de baja · ${user.name}`,`<form id="offboard-form"><p class="hint orange">La cuenta pierde el acceso en este momento: se cierran sus sesiones y no podrá volver a entrar. Sus prospectos, citas pendientes, tareas y conversaciones pasan a la persona que elijas. No se borra ningún registro.</p><div class="form-grid"><label class="span-2">¿Quién recibe su trabajo?<select name="target_id" required><option value="">Elige una cuenta activa</option>${options.map(item=>`<option value="${esc(item.id)}">${esc(item.name)} · ${esc(roleLabel(item))}</option>`).join('')}</select></label><label class="span-2 checkbox"><input name="confirm" type="checkbox" required><span>Confirmo que ${esc(user.name)} deja el equipo.</span></label></div><p class="form-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-action="close-dialog">Cancelar</button><button class="button danger" type="submit">Dar de baja</button></div></form>`);
  $('#offboard-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{const result=await post(`/api/team/${encodeURIComponent(id)}/offboard`,{target_id:data.get('target_id')});closeDialog();const moved=result.moved||{};const count=(n,one,many)=>`${n||0} ${(n||0)===1?one:many}`;toast(`${user.name} ya no tiene acceso. Se transfirieron ${count(moved.leads,'prospecto','prospectos')}, ${count(moved.appointments,'cita','citas')} y ${count(moved.tasks,'tarea','tareas')}.`);await navigate('settings',false);}));
}
async function renderSubscription(requestId) {
  const data=await api('/api/owner/plans');if(!current(requestId))return;const usage=data.usage||{};
  const price=plan=>plan.monthly_usd==null?'Cotización':`$${esc(plan.monthly_usd)}<small>/mes</small>`;
  content.innerHTML=heading('SOLO PROPIETARIO','Suscripción','Planes propuestos para el uso de R.E.I.G.E.L. por tu equipo. No los ven los administradores, los asesores ni los clientes.')+
    `<section class="panel"><header class="panel-head"><div><p class="section-kicker">LICENCIAS EN USO</p><h2>Tu equipo hoy</h2></div></header><div class="panel-body"><div class="usage-summary"><div><small>ASESORES ACTIVOS</small><p>${esc(usage.advisors??0)}</p></div><div><small>ADMINISTRADORES ACTIVOS</small><p>${esc(usage.admins??0)}</p></div><div><small>CUENTAS DADAS DE BAJA</small><p>${esc(usage.inactive??0)}</p></div></div></div></section>
    <div class="plan-grid">${(data.plans||[]).map(plan=>`<article class="panel plan-card${plan.recommended?' is-recommended':''}"><div class="panel-body"><p class="section-kicker">${esc(plan.audience)}</p><h2>${esc(plan.name)}${plan.recommended?` ${badge('green','Recomendado')}`:''}</h2><p class="plan-price">${price(plan)}</p><ul class="plan-list">${(plan.includes||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ul><p class="field-help">${esc(plan.note)}</p></div></article>`).join('')}</div>
    <p class="hint orange">${esc(data.notice)}</p>`;
}

function closeMenu() {$('#sidebar').classList.remove('open');$('#scrim').hidden=true;$('#menu-button').setAttribute('aria-expanded','false');$('.app-body').inert=false;syncMenu();}
function syncMenu() {const mobile=matchMedia('(max-width:800px)').matches;$('#sidebar').inert=mobile&&!$('#sidebar').classList.contains('open');}
function openMenu() {$('#sidebar').classList.add('open');$('#sidebar').inert=false;$('#scrim').hidden=false;$('#menu-button').setAttribute('aria-expanded','true');$('.app-body').inert=true;$('.nav-item',$('#sidebar')).focus();}
$('#menu-button').addEventListener('click',openMenu);$('#scrim').addEventListener('click',()=>{closeMenu();$('#menu-button').focus();});window.addEventListener('resize',()=>{if(!matchMedia('(max-width:800px)').matches)closeMenu();else syncMenu();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#sidebar').classList.contains('open')){closeMenu();$('#menu-button').focus();}if(event.key==='Tab'&&$('#sidebar').classList.contains('open')){const focusable=$$('a,button:not([disabled])',$('#sidebar'));if(event.shiftKey&&document.activeElement===focusable[0]){event.preventDefault();focusable.at(-1).focus();}else if(!event.shiftKey&&document.activeElement===focusable.at(-1)){event.preventDefault();focusable[0].focus();}}});
$('#close-dialog').addEventListener('click',closeDialog);dialog.addEventListener('click',event=>{if(event.target===dialog){const bounds=dialog.getBoundingClientRect();if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)closeDialog();}});
$('#login-form').addEventListener('submit',event=>submitForm(event,async(form,data)=>{const result=await post('/api/auth/login',{email:data.get('email'),password:data.get('password')});form.reset();await enter(result.user);}));
$('#logout').addEventListener('click',async()=>{try{await post('/api/auth/logout',{});showLogin();toast('Sesión cerrada.');}catch(error){toast(error.message);}});
document.addEventListener('click',async event=>{
  const view=event.target.closest('[data-view]');if(view){if(dialog.open)closeDialog();navigate(view.dataset.view);return;}
  const button=event.target.closest('[data-action]');if(!button)return;const {action,id}=button.dataset;
  const actions={...operationActions(button),refresh:()=>navigate(state.view,false),'new-lead':newLead,'lead-detail':()=>leadDetail(id),'close-dialog':closeDialog,'new-appointment':()=>newAppointment(),'schedule-lead':()=>newAppointment(id),'cancel-appointment':()=>cancelAppointment(id),'new-user':newUser,'edit-user':()=>editUser(id),'offboard-user':()=>offboardUser(id),availability:()=>{closeDialog();return navigate('settings');},'open-conversation':()=>openConversation(id),'conversation-mode':()=>conversationMode(id,button.dataset.mode,button),'copy-template':()=>copy(campaignTemplates[Number(button.dataset.index)].text),'copy-utm':()=>copy($('#utm-link').textContent),'copy-draft':()=>copy($('#draft-text').textContent),'refresh-knowledge':()=>refreshKnowledge(button)};
  try {await actions[action]?.();}catch(error){toast(error.message);}
});
syncMenu();
(async()=>{try{const data=await api('/api/auth/me');await enter(data.user);}catch(error){showLogin();if(error.status!==401)$('#login-error').textContent=error.message;}})();
