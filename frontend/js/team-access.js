(() => {
  const $ = id => document.getElementById(id);
  const state = {csrf: '', profile: null, withGrant: false};

  async function api(path, {method = 'GET', body} = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && state.csrf) headers['X-Reigel-CSRF'] = state.csrf;
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
      notify(error.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function options(select, users) {
    select.replaceChildren(...users.map(user => {
      const option = document.createElement('option');
      option.value = user.id;
      option.textContent = `${user.name} · ${user.email}`;
      return option;
    }));
  }

  function showSetup(setup) {
    $('setup-secret').textContent = setup.secret.match(/.{1,4}/g).join(' ');
    $('setup-secret').dataset.secret = setup.secret;
    $('setup-link').href = setup.otpauth_uri;
    $('setup-qr').src = setup.qr;
    $('setup-view').hidden = false;
    $('guest-view').hidden = true;
    $('member-view').hidden = true;
    $('confirm-form').elements.code.focus();
  }

  function hideSetup() {
    $('setup-secret').textContent = '';
    delete $('setup-secret').dataset.secret;
    $('setup-link').href = '#';
    $('setup-qr').removeAttribute('src');
    $('setup-view').hidden = true;
  }

  async function renderMember() {
    state.profile = await api('/api/team-identity/me');
    state.csrf = state.profile.csrf;
    const {user} = state.profile;
    $('member-name').textContent = `${user.name} · ${user.team_role}`;
    // A team session only exists after Google Authenticator; there is no way to turn it off here.
    $('totp-state').textContent = 'Activo: al entrar se te pide tu contraseña y un código de 6 dígitos.';

    const isAdmin = user.team_role === 'administrador';
    $('admin-section').hidden = !isAdmin;
    if (isAdmin) {
      const {users} = await api('/api/team');
      // Mirrors the server rules (the server decides): never the owner; administrators only for the owner.
      const others = users.filter(item => item.id !== user.id && item.active && !item.is_owner && (item.role !== 'admin' || user.is_owner));
      options($('grant-user'), others);
      options($('role-user'), others.filter(item => item.role !== 'admin'));
    }
    $('policy-section').hidden = !user.is_owner;
    $('member-view').hidden = false;
    $('guest-view').hidden = true;
  }

  function submit(id, work) {
    $(id).addEventListener('submit', event => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = event.submitter || form.querySelector('[type=submit]');
      run(button, () => work(Object.fromEntries(new FormData(form)), form, button));
    });
  }

  $('copy-secret').addEventListener('click', event => run(event.currentTarget, async () => {
    await navigator.clipboard.writeText($('setup-secret').dataset.secret);
    notify('Clave copiada.', true);
  }));
  submit('grant-setup-form', async (data, form) => {
    state.withGrant = true;
    const {setup} = await api('/api/team-identity/totp/setup', {method: 'POST', body: data});
    form.reset();
    showSetup(setup);
  });
  submit('confirm-form', async (data, form) => {
    await api('/api/team-identity/totp/confirm', {method: 'POST', body: {code: data.code, with_grant: state.withGrant}});
    form.reset();
    hideSetup();
    if (state.withGrant) {
      state.withGrant = false;
      $('guest-view').hidden = false;
      notify('Listo. Entra con tu contraseña y el siguiente código de la app.', true);
      return;
    }
    await renderMember();
    notify('Nuevo teléfono registrado en Google Authenticator. Se cerraron tus otras sesiones.', true);
  });
  submit('manage-totp-form', async (data, form) => {
    state.withGrant = false;
    const {setup} = await api('/api/team-identity/totp/setup', {method: 'POST', body: {current_code: data.code}});
    form.reset();
    showSetup(setup);
  });
  submit('grant-form', async (data, form) => {
    const result = await api(`/api/team-identity/users/${encodeURIComponent(data.user_id)}/grant`, {method: 'POST', body: {purpose: data.purpose, reason: data.reason}});
    form.elements.reason.value = '';
    $('grant-code').textContent = result.code;
    $('grant-code').hidden = false;
    const expires = new Date(result.expires_at).toLocaleString('es-PR', {dateStyle: 'medium', timeStyle: 'short'});
    notify(`Entrega este código en persona; no lo envíes por correo ni por chat. Es de un solo uso, vence el ${expires} y no se volverá a mostrar.`, true);
  });
  submit('role-form', async data => {
    await api(`/api/team-identity/users/${encodeURIComponent(data.user_id)}/role`, {method: 'PUT', body: {role: data.role}});
    notify('Rol actualizado.', true);
  });
  (async () => {
    try {
      await renderMember();
    } catch (error) {
      if (error.status !== 401) notify(error.message);
      $('guest-view').hidden = false;
    }
  })();
})();
