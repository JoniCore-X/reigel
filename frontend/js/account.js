(() => {
  const $ = id => document.getElementById(id);
  const state = {csrf: '', customer: null, config: {providers: [], verification: {}}, verifying: ''};

  async function api(path, {method = 'GET', body} = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (state.csrf && method !== 'GET') headers['X-Reigel-CSRF'] = state.csrf;
    const response = await fetch(path, {method, credentials: 'same-origin', headers, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(data.detail || 'No se pudo completar la operación.'), {status: response.status});
    return data;
  }

  function notify(text, ok = false) {
    $('account-message').textContent = text;
    $('account-message').classList.toggle('ok', ok);
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function actionButton(label, handler) {
    const button = element('button', label, 'id-button quiet compact');
    button.type = 'button';
    button.addEventListener('click', () => run(button, handler));
    return button;
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

  function show(view) {
    for (const id of ['auth-view', 'recovery-view', 'profile-view']) $(id).hidden = id !== view;
  }

  function tab(name) {
    const login = name === 'login';
    $('login-form').hidden = !login;
    $('register-form').hidden = login;
    $('tab-login').setAttribute('aria-selected', String(login));
    $('tab-register').setAttribute('aria-selected', String(!login));
  }

  function renderProviders() {
    const box = $('social-buttons');
    box.replaceChildren(...state.config.providers.map(provider => {
      const button = element('button', provider.label, 'id-button quiet');
      button.type = 'button';
      button.addEventListener('click', () => run(button, async () => {
        const result = await api(`/api/customer/oauth/${encodeURIComponent(provider.id)}/start`, {method: 'POST', body: {mode: 'login'}});
        location.assign(result.url);
      }));
      return button;
    }));
    $('social-block').hidden = !state.config.providers.length;
  }

  async function renderProfile() {
    const customer = state.customer;
    $('account-title').textContent = `Hola, ${customer.display_name || customer.username}`;
    $('identifier-list').replaceChildren(rowFor('Usuario', customer.username), ...customer.identifiers.map(item => {
      const row = rowFor(item.kind === 'email' ? 'Correo' : 'Teléfono', item.value, item.verified ? 'Verificado' : 'Sin verificar');
      if (!item.verified && state.config.verification[item.kind]) {
        row.append(actionButton('Verificar', async () => {
          await api('/api/customer/verify/start', {method: 'POST', body: {identifier_id: item.id}});
          state.verifying = item.id;
          $('verify-form').hidden = false;
          notify('Te enviamos un código.', true);
        }));
      }
      return row;
    }));
    const linked = new Map(customer.providers.map(item => [item.provider, item]));
    const rows = state.config.providers.map(provider => {
      const row = rowFor(provider.label, linked.has(provider.id) ? 'Vinculada' : 'Sin vincular');
      row.append(linked.has(provider.id)
        ? actionButton('Quitar', async () => {
          state.customer = (await api(`/api/customer/oauth/${encodeURIComponent(provider.id)}`, {method: 'DELETE'})).customer;
          await renderProfile();
        })
        : actionButton('Vincular', async () => {
          const result = await api(`/api/customer/oauth/${encodeURIComponent(provider.id)}/start`, {method: 'POST', body: {mode: 'link'}});
          location.assign(result.url);
        }));
      return row;
    });
    $('provider-list').replaceChildren(...rows);
    $('provider-section').hidden = !rows.length;
    const {items} = await api('/api/customer/entitlements');
    $('entitlement-list').replaceChildren(...(items.length ? items.map(item => rowFor(item.name, item.permission)) : [rowFor('Sin productos activos', 'Aquí verás tus planes y compras.')]));
    show('profile-view');
  }

  function rowFor(title, detail, extra) {
    const row = element('li', undefined, 'id-row');
    const text = element('span', title);
    text.append(element('small', extra ? `${detail} · ${extra}` : detail));
    row.append(text);
    return row;
  }

  function submit(id, work) {
    $(id).addEventListener('submit', event => {
      event.preventDefault();
      const form = event.currentTarget;
      run(form.querySelector('[type=submit]'), () => work(Object.fromEntries(new FormData(form)), form));
    });
  }

  async function entered(result, form) {
    state.csrf = result.csrf;
    state.customer = result.customer;
    form.reset();
    await renderProfile();
  }

  submit('login-form', async (data, form) => entered(await api('/api/customer/login', {method: 'POST', body: data}), form));
  submit('register-form', async (data, form) => {
    if (!data.email && !data.phone) throw new Error('Añade un correo o un teléfono.');
    const body = {username: data.username, password: data.password};
    if (data.email) body.email = data.email;
    if (data.phone) body.phone = data.phone;
    await entered(await api('/api/customer/register', {method: 'POST', body}), form);
  });
  submit('recover-start', async data => {
    const result = await api('/api/customer/recover/start', {method: 'POST', body: data});
    state.recovery = data.identifier;
    notify(result.message, true);
  });
  submit('recover-finish', async (data, form) => {
    const identifier = state.recovery || $('recover-start').elements.identifier.value;
    await api('/api/customer/recover/finish', {method: 'POST', body: {...data, identifier}});
    form.reset();
    show('auth-view');
    tab('login');
    notify('Contraseña actualizada. Inicia sesión.', true);
  });
  submit('verify-form', async (data, form) => {
    state.customer = (await api('/api/customer/verify/finish', {method: 'POST', body: {identifier_id: state.verifying, code: data.code}})).customer;
    form.reset();
    form.hidden = true;
    await renderProfile();
    notify('Dato verificado.', true);
  });

  $('tab-login').addEventListener('click', () => tab('login'));
  $('tab-register').addEventListener('click', () => tab('register'));
  $('show-recovery').addEventListener('click', () => { notify(''); show('recovery-view'); });
  $('back-login').addEventListener('click', () => { notify(''); show('auth-view'); });
  $('logout').addEventListener('click', event => run(event.currentTarget, async () => {
    await api('/api/customer/logout', {method: 'POST'});
    state.csrf = '';
    state.customer = null;
    $('account-title').textContent = 'Bienvenido a R.E.I.G.E.L.';
    show('auth-view');
  }));

  (async () => {
    if (new URLSearchParams(location.search).get('error') === 'oauth') {
      notify('No se pudo completar el acceso con ese proveedor.');
      history.replaceState(null, '', '/cuenta');
    }
    try {
      state.config = await api('/api/customer/config');
      renderProviders();
      const me = await api('/api/customer/me');
      state.csrf = me.csrf;
      state.customer = me.customer;
      await renderProfile();
    } catch (error) {
      if (error.status !== 401) notify(error.message);
      show('auth-view');
    }
  })();
})();
