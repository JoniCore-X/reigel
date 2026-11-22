(() => {
  const toBytes = value => {
    const base = value.replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(base + '='.repeat((4 - base.length % 4) % 4)), char => char.charCodeAt(0));
  };
  const toText = buffer => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const supported = () => Boolean(window.PublicKeyCredential) && window.isSecureContext && !/^(\d+\.){3}\d+$|^\[/.test(location.hostname);

  async function request(path, body, csrf) {
    const headers = {'Content-Type': 'application/json'};
    if (csrf) headers['X-Reigel-CSRF'] = csrf;
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', headers, body: JSON.stringify(body || {})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'No se pudo completar la operación.');
    return data;
  }

  async function create(options) {
    const publicKey = {...options, challenge: toBytes(options.challenge), user: {...options.user, id: toBytes(options.user.id)},
      excludeCredentials: (options.excludeCredentials || []).map(item => ({...item, id: toBytes(item.id)}))};
    const credential = await navigator.credentials.create({publicKey});
    return {id: credential.id, rawId: toText(credential.rawId), type: credential.type, response: {
      clientDataJSON: toText(credential.response.clientDataJSON), attestationObject: toText(credential.response.attestationObject),
      transports: credential.response.getTransports ? credential.response.getTransports() : []}};
  }

  async function get(options) {
    const credential = await navigator.credentials.get({publicKey: {...options, challenge: toBytes(options.challenge)}});
    return {id: credential.id, rawId: toText(credential.rawId), type: credential.type, response: {
      clientDataJSON: toText(credential.response.clientDataJSON), authenticatorData: toText(credential.response.authenticatorData),
      signature: toText(credential.response.signature), userHandle: credential.response.userHandle ? toText(credential.response.userHandle) : ''}};
  }

  async function login() {
    const {publicKey} = await request('/api/team-identity/passkeys/login/options');
    return request('/api/team-identity/passkeys/login/verify', {credential: await get(publicKey)});
  }

  async function register({csrf, email, code, label}) {
    const body = code ? {email, code} : {};
    const {publicKey} = await request('/api/team-identity/passkeys/register/options', body, csrf);
    return request('/api/team-identity/passkeys/register/verify', {credential: await create(publicKey), label, with_code: Boolean(code)}, csrf);
  }

  const message = error => error && error.name === 'NotAllowedError' ? 'La verificación se canceló o venció.' : (error && error.message) || 'No se pudo completar la operación.';
  window.ReigelPasskey = {supported, request, login, register, message};

  const button = document.getElementById('passkey-login');
  if (button && supported()) {
    button.hidden = false;
    button.addEventListener('click', async () => {
      const error = document.getElementById('login-error');
      error.textContent = '';
      button.disabled = true;
      try {
        await login();
        location.assign('/app');
      } catch (failure) {
        error.textContent = message(failure);
        button.disabled = false;
      }
    });
  }
})();
