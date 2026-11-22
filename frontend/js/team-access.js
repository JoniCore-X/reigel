(() => {
  const $ = id => document.getElementById(id);
  const passkey = window.ReigelPasskey;
  const state = {csrf: '', profile: null};
  const statusLabel = {approved: 'Aprobada', pending: 'Pendiente de aprobación'};

  async function api(path, {method = 'GET', body} = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') headers['X-Reigel-CSRF'] = state.csrf;
    const response = await fetch(path, {method, credentials: 'same-origin', headers, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(data.detail || 'No se pudo completar la operación.'), {status: response.status});
    return data;
  }

  function notify(text, ok = false) {
    $('team-message').textContent = text;
    $('team-message').classList.toggle('ok', ok);
  }

  async function run(button, work) {
    notify('');
    if (button) button.disabled = true;
    try {
      await work();
    } catch (error) {
      notify(passkey.message(error));
    } finally {
      if (button) button.disabled = false;
    }
  }

  function row(title, detail, ...actions) {
    const item = document.createElement('li');
    item.className = 'id-row';
    const text = document.createElement('span');
    text.textContent = title;
    const small = document.createElement('small');
    small.textContent = detail;
    text.append(small);
    item.append(text);
    if (actions.length) {
      const box = document.createElement('span');
      box.className = 'id-actions';
      box.append(...actions);
      item.append(box);
    }
    return item;
  }

  function action(label, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'id-button quiet compact';
    button.textContent = label;
    button.addEventListener('click', () => run(button, handler));
    return button;
  }

  function options(select, users) {
    select.replaceChildren(...users.map(user => {
      const option = document.createElement('option');
      option.value = user.id;
      option.textContent = `${user.name} · ${user.email}`;
      return option;
    }));
  }

  async function renderMember() {
    state.profile = await api('/api/team-identity/me');
    state.csrf = state.profile.csrf;
    const {user, passkeys, passkey_required: required} = state.profile;
    $('member-name').textContent = `${user.name} · ${user.team_role}`;
    $('key-list').replaceChildren(...(passkeys.length ? passkeys.map(key => row(key.label, statusLabel[key.status] || key.status, action('Quitar', async () => {
      await api(`/api/team-identity/passkeys/${encodeURIComponent(key.id)}`, {method: 'DELETE'});
      await renderMember();
    }))) : [row('Sin llaves registradas', 'Añade una para entrar sin contraseña.')]));

    const canReview = user.team_role !== 'consultor';
    $('pending-section').hidden = !canReview;
    if (canReview) {
      const {items} = await api('/api/team-identity/devices/pending');
      const decide = (id, approve) => async () => {
        await api(`/api/team-identity/devices/${encodeURIComponent(id)}/decision`, {method: 'POST', body: {approve}});
        await renderMember();
      };
      $('pending-list').replaceChildren(...(items.length ? items.map(item => row(`${item.user_name} · ${item.label}`, item.team_role,
        action('Aprobar', decide(item.id, true)), action('Rechazar', decide(item.id, false)))) : [row('Sin solicitudes', 'No hay dispositivos pendientes.')]));
    }

    const isAdmin = user.team_role === 'administrador';
    $('admin-section').hidden = !isAdmin;
    if (isAdmin) {
      const {users} = await api('/api/team');
      const others = users.filter(item => item.id !== user.id && item.active && (item.role !== 'admin' || user.is_owner));
      options($('grant-user'), others);
      options($('role-user'), others.filter(item => item.role !== 'admin'));
    }
    $('policy-section').hidden = !user.is_owner;
    $('policy-state').textContent = required ? 'Todo el equipo debe entrar con llave de acceso.' : 'Transición gradual: quien aún no tenga llave puede usar su contraseña.';
    $('policy-toggle').textContent = required ? 'Volver a transición gradual' : 'Exigir llave de acceso a todo el equipo';
    $('member-view').hidden = false;
    $('guest-view').hidden = true;
  }

  function submit(id, work) {
    $(id).addEventListener('submit', event => {
      event.preventDefault();
      const form = event.currentTarget;
      run(form.querySelector('[type=submit]'), () => work(Object.fromEntries(new FormData(form)), form));
    });
  }

  const supported = passkey.supported();
  $('team-unsupported').hidden = supported;
  for (const button of [$('verify-identity'), $('enroll-form').querySelector('[type=submit]'), $('add-key-form').querySelector('[type=submit]')]) button.disabled = !supported;

  $('verify-identity').addEventListener('click', event => run(event.currentTarget, async () => {
    await passkey.login();
    location.assign('/app');
  }));
  submit('enroll-form', async (data, form) => {
    const result = await passkey.register({email: data.email, code: data.code, label: data.label});
    form.reset();
    notify(result.passkey.status === 'approved' ? 'Llave registrada. Ya puedes verificar tu identidad.' : 'Llave registrada. Espera la aprobación.', true);
  });
  submit('add-key-form', async (data, form) => {
    const result = await passkey.register({csrf: state.csrf, label: data.label});
    form.reset();
    await renderMember();
    notify(result.passkey.status === 'approved' ? 'Llave registrada.' : 'Llave registrada. Debe aprobarla un responsable.', true);
  });
  submit('grant-form', async (data, form) => {
    const result = await api(`/api/team-identity/users/${encodeURIComponent(data.user_id)}/grant`, {method: 'POST', body: {purpose: data.purpose, reason: data.reason}});
    form.elements.reason.value = '';
    $('grant-code').textContent = result.code;
    $('grant-code').hidden = false;
    notify('Entrega este código por un canal seguro. Vence en 60 minutos y no se volverá a mostrar.', true);
  });
  submit('role-form', async data => {
    await api(`/api/team-identity/users/${encodeURIComponent(data.user_id)}/role`, {method: 'PUT', body: {role: data.role}});
    notify('Rol actualizado.', true);
  });
  $('policy-toggle').addEventListener('click', event => run(event.currentTarget, async () => {
    await api('/api/team-identity/policy', {method: 'PUT', body: {passkey_required: !state.profile.passkey_required}});
    await renderMember();
  }));

  (async () => {
    try {
      await renderMember();
    } catch (error) {
      if (error.status !== 401) notify(error.message);
      $('guest-view').hidden = false;
    }
  })();
})();
