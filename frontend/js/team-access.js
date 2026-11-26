(() => {
  const $ = id => document.getElementById(id);
  const state = {csrf: '', profile: null, withGrant: false, copy: {}};

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
    const message = $('team-message');
    // Errors interrupt (alert); confirmations wait their turn (status).
    message.setAttribute('role', ok ? 'status' : 'alert');
    message.classList.toggle('ok', ok);
    message.textContent = text;
    if (text) message.scrollIntoView({block: 'nearest'});
  }

  // Step indicator: it only mirrors the view that is already on screen.
  function syncSteps() {
    const current = !$('setup-view').hidden ? 2 : !$('member-view').hidden ? 3 : 1;
    document.querySelectorAll('#auth-steps .auth-step').forEach(item => {
      const step = Number(item.dataset.step);
      item.classList.toggle('is-done', step < current);
      if (step === current) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
      item.querySelector('.auth-sr').textContent = step < current ? 'Completado: ' : '';
    });
    $('auth-step-detail').textContent = current === 2 ? 'Autenticador' : '';
  }

  // The fields of an access form are flagged while its error is on screen (the server does not say which one failed).
  function flag(form, invalid) {
    form?.querySelectorAll('input').forEach(field => {
      if (invalid) {
        field.setAttribute('aria-invalid', 'true');
        field.setAttribute('aria-describedby', 'team-message');
      } else {
        field.removeAttribute('aria-invalid');
        field.removeAttribute('aria-describedby');
      }
    });
  }

  async function run(button, work, form) {
    notify('');
    flag(form, false);
    if (button) button.disabled = true;
    try {
      await work();
    } catch (error) {
      notify(error.message);
      // A throttled or failed request is not a field error.
      if (error.status >= 400 && error.status < 500 && error.status !== 429) flag(form, true);
    } finally {
      if (button) button.disabled = false;
    }
  }

  // Texts about access management come from the server for the signed-in role; this file carries none.
  function copyText(group, key, fallback = '') {
    const value = state.copy?.[group]?.[key];
    return typeof value === 'string' && value ? value : fallback;
  }

  function note(id, text) {
    $(id).textContent = text;
    $(id).hidden = !text;
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
    syncSteps();
    $('confirm-form').elements.code.focus();
  }

  function hideSetup() {
    $('setup-secret').textContent = '';
    delete $('setup-secret').dataset.secret;
    $('setup-link').href = '#';
    $('setup-qr').removeAttribute('src');
    $('setup-view').hidden = true;
    syncSteps();
  }

  async function renderMember() {
    state.profile = await api('/api/team-identity/me');
    state.csrf = state.profile.csrf;
    const {user} = state.profile;
    $('member-name').textContent = `${user.name} · ${user.team_role}`;
    state.copy = await api('/api/team-access/copy').then(data => data.copy || {}).catch(() => ({}));
    note('totp-note', copyText('member', 'totp_note'));
    $('totp-state').textContent = 'Activo: al entrar se te pide tu contraseña y un código de 6 dígitos.';

    const isAdmin = user.team_role === 'administrador';
    $('admin-section').hidden = !isAdmin;
    if (isAdmin) {
      const {users} = await api('/api/team');
      // Only decides which people to list; the server authorizes every action again.
      const others = users.filter(item => item.id !== user.id && item.active && !item.is_owner && (item.role !== 'admin' || user.is_owner));
      options($('grant-user'), others);
      options($('role-user'), others.filter(item => item.role !== 'admin'));
      note('grant-scope', copyText('admin', 'grant_scope'));
      for (const option of $('grant-purpose').options) {
        option.textContent = copyText('admin', `grant_purpose_${option.value}`, option.textContent);
      }
    }
    $('policy-section').hidden = !user.is_owner;
    note('policy-note', copyText('owner', 'policy_note'));
    $('member-view').hidden = false;
    $('guest-view').hidden = true;
    syncSteps();
  }

  function submit(id, work, access = false) {
    $(id).addEventListener('submit', event => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = event.submitter || form.querySelector('[type=submit]');
      run(button, () => work(Object.fromEntries(new FormData(form)), form, button), access ? form : null);
    });
    // One message covers the whole form, so correcting any field clears them all.
    if (access) $(id).addEventListener('input', event => flag(event.currentTarget, false));
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
  }, true);
  submit('confirm-form', async (data, form) => {
    await api('/api/team-identity/totp/confirm', {method: 'POST', body: {code: data.code, with_grant: state.withGrant}});
    form.reset();
    hideSetup();
    if (state.withGrant) {
      state.withGrant = false;
      $('guest-view').hidden = false;
      syncSteps();
      notify('Listo. Entra con tu contraseña y el siguiente código de la app.', true);
      $('team-message').focus();
      return;
    }
    await renderMember();
    notify(copyText('member', 'phone_changed', 'Nuevo teléfono registrado en Google Authenticator.'), true);
    $('team-message').focus();
  }, true);
  submit('manage-totp-form', async (data, form) => {
    state.withGrant = false;
    const {setup} = await api('/api/team-identity/totp/setup', {method: 'POST', body: {current_code: data.code}});
    form.reset();
    showSetup(setup);
  }, true);
  submit('grant-form', async (data, form) => {
    const result = await api(`/api/team-identity/users/${encodeURIComponent(data.user_id)}/grant`, {method: 'POST', body: {purpose: data.purpose, reason: data.reason}});
    form.elements.reason.value = '';
    $('grant-code').textContent = result.code;
    $('grant-code').hidden = false;
    const expires = new Date(result.expires_at).toLocaleString('es-PR', {dateStyle: 'medium', timeStyle: 'short'});
    notify(copyText('admin', 'grant_delivery', 'Código emitido. Vence el {expires}.').replace('{expires}', expires), true);
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
      syncSteps();
    }
  })();
})();
