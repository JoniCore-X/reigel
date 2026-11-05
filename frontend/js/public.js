'use strict';

const $ = selector=>document.querySelector(selector);
const esc = value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const publicState={timezone:'America/Puerto_Rico',advisors:[],ready:false,slotRequest:0};
function errorText(data){if(typeof data?.detail==='string')return data.detail;if(Array.isArray(data?.detail))return data.detail.map(item=>`${item.loc?.at(-1)||'Campo'}: ${item.msg || 'valor inválido'}`).join('. ');return 'No se pudo completar tu solicitud. Intenta nuevamente.';}
async function publicApi(path,options={}) {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
  try {const response=await fetch(path,{...options,headers:{'Content-Type':'application/json'},signal:controller.signal});const data=await response.json().catch(()=>({}));if(!response.ok){const error=new Error(errorText(data));error.status=response.status;throw error;}return data;}
  catch(error){if(error.name==='AbortError')throw new Error('La conexión tardó demasiado. Si reservaste, consulta al equipo antes de repetir para evitar duplicados.');if(error instanceof TypeError)throw new Error('No pudimos conectar con el equipo. Revisa tu conexión y vuelve a intentar.');throw error;}finally{clearTimeout(timer);}
}
function day(offset=0){const date=new Date(Date.now()+offset*86400000);return new Intl.DateTimeFormat('en-CA',{timeZone:publicState.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(date);}
function time(value){return new Intl.DateTimeFormat('es-PR',{timeZone:publicState.timezone,hour:'numeric',minute:'2-digit'}).format(new Date(value));}
function fullDate(value){return new Intl.DateTimeFormat('es-PR',{timeZone:publicState.timezone,weekday:'long',day:'numeric',month:'long',hour:'numeric',minute:'2-digit'}).format(new Date(value));}
function modeChanged(){const booking=$('input[name="mode"]:checked').value==='book';$('#public-booking-fields').hidden=!booking;$('#public-advisor').required=booking;$('#public-date').required=booking;$('#public-submit').textContent=booking?'Confirmar mi cita ↗':'Solicitar contacto ↗';if(booking)loadSlots();}
async function loadSlots(){
  const request=++publicState.slotRequest;$('#public-start').value='';const advisor=$('#public-advisor').value,date=$('#public-date').value;
  if(!advisor||!date){$('#public-slots').innerHTML='<p class="slot-empty">Selecciona un asesor y una fecha para ver los horarios.</p>';return;}
  $('#public-slots').innerHTML='<p class="status-inline">Consultando horarios…</p>';
  try{const data=await publicApi(`/api/public/slots?advisor_id=${encodeURIComponent(advisor)}&date=${encodeURIComponent(date)}`);if(request!==publicState.slotRequest)return;publicState.timezone=data.timezone || publicState.timezone;$('#public-timezone').textContent=`Los horarios se muestran en ${publicState.timezone}.`;
    $('#public-slots').innerHTML=(data.slots || []).length?data.slots.map(slot=>`<button type="button" class="slot-button" data-start="${esc(slot.start_at)}" aria-pressed="false">${esc(time(slot.start_at))}</button>`).join(''):'<p class="slot-empty span-2">No hay horarios disponibles este día. Elige otra fecha o solicita que te contactemos.</p>';
    document.querySelectorAll('[data-start]').forEach(button=>button.addEventListener('click',()=>{$('#public-start').value=button.dataset.start;document.querySelectorAll('[data-start]').forEach(other=>{other.classList.toggle('selected',other===button);other.setAttribute('aria-pressed',String(other===button));});}));
  }catch(error){if(request===publicState.slotRequest)$('#public-slots').innerHTML=`<p class="form-error" role="alert">${esc(error.message)}</p>`;}
}
document.querySelectorAll('input[name="mode"]').forEach(input=>input.addEventListener('change',modeChanged));$('#public-advisor').addEventListener('change',loadSlots);$('#public-date').addEventListener('change',loadSlots);
$('#public-lead-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,button=$('#public-submit');if(button.disabled)return;$('#public-form-error').textContent='';
  const data=new FormData(form);const booking=data.get('mode')==='book';
  if(!String(data.get('email')||'').trim()&&!String(data.get('phone')||'').trim()){$('#public-form-error').textContent='Incluye un correo electrónico o teléfono para que podamos responderte.';return;}
  if(booking&&!data.get('start_at')){$('#public-form-error').textContent='Selecciona un horario disponible para confirmar tu cita.';return;}
  button.disabled=true;const original=button.textContent;button.textContent=booking?'Confirmando tu cita…':'Guardando tu solicitud…';
  const params=new URLSearchParams(location.search);
  const payload={name:String(data.get('name')).trim(),email:String(data.get('email')||'').trim(),phone:String(data.get('phone')||'').trim(),municipality:String(data.get('municipality')||'').trim(),monthly_bill:data.get('monthly_bill')?Number(data.get('monthly_bill')):null,consent:data.has('consent'),source:'web',utm_source:(params.get('utm_source')||'').slice(0,100),utm_medium:(params.get('utm_medium')||'').slice(0,100),utm_campaign:(params.get('utm_campaign')||'').slice(0,150),website:data.get('website')||''};
  if(booking){payload.advisor_id=data.get('advisor_id');payload.start_at=data.get('start_at');}
  try{const result=await publicApi(booking?'/api/public/book':'/api/public/leads',{method:'POST',body:JSON.stringify(payload)});
    const appointment=result.appointment;$('#booking-card').innerHTML=booking&&appointment?`<div class="booking-success" role="status" tabindex="-1"><p class="eyebrow">TU CITA ESTÁ CONFIRMADA</p><h3>Nos vemos pronto.</h3><p>${esc(fullDate(appointment.start_at))}<br>Con ${esc(appointment.advisor_name || 'el equipo de Power Solar')}.</p><p class="calendar-zone">Zona horaria: ${esc(publicState.timezone)}</p><span class="reference">Referencia: ${esc(appointment.id)}</span><p class="field-help">Guarda esta confirmación. Si necesitas cambiar la cita, comunícate con el equipo que te atienda.</p></div>`:`<div class="booking-success" role="status" tabindex="-1"><p class="eyebrow">RECIBIMOS TU INTERÉS</p><h3>El primer paso está dado.</h3><p>Tu solicitud quedó registrada para el equipo de Power Solar. Podrán contactarte por los medios que compartiste.</p><p class="field-help">Esta solicitud de contacto no confirma una cita.</p></div>`;
    $('.booking-success').focus();
  }catch(error){$('#public-form-error').textContent=error.message;if(error.status===409&&booking)await loadSlots();button.disabled=false;button.textContent=original;}
});
(async()=>{try{const config=await publicApi('/api/public/config');publicState.advisors=config.advisors || [];publicState.timezone=config.business?.timezone || publicState.timezone;publicState.ready=true;$('#public-date').min=day();$('#public-date').max=day(60);$('#public-date').value=day(1);$('#public-timezone').textContent=`Zona horaria: ${publicState.timezone}`;
  $('#public-advisor').innerHTML='<option value="">Selecciona un asesor</option>'+publicState.advisors.map(user=>`<option value="${esc(user.id)}">${esc(user.name)}</option>`).join('');
  if(publicState.advisors.length===1)$('#public-advisor').value=publicState.advisors[0].id;
  $('#public-config-status').textContent=publicState.advisors.length?'Puedes solicitar contacto o reservar un horario disponible.':'El equipo aún no ha publicado horarios. Puedes dejar tu solicitud de contacto.';$('#book-mode').disabled=!publicState.advisors.length;
  if(config.business?.privacy_contact)$('#public-privacy-contact').textContent=` Contacto de privacidad: ${config.business.privacy_contact}.`;
}catch(error){$('#public-config-status').textContent=error.message;$('#book-mode').disabled=true;}})();
