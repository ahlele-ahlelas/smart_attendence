// Thin fetch wrapper: JSON in/out, friendly errors, session cookies included.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function handle(res) {
  if (res.ok) {
    const type = res.headers.get('content-type') || '';
    return type.includes('application/json') ? res.json() : res;
  }
  let message = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (body.detail) message = typeof body.detail === 'string' ? body.detail : message;
  } catch { /* non-JSON error body */ }
  throw new ApiError(message, res.status);
}

export function getJSON(url) {
  return fetch(url, { credentials: 'same-origin' }).then(handle);
}

export function postJSON(url, data) {
  return fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(handle);
}

export function postForm(url, formData) {
  return fetch(url, { method: 'POST', credentials: 'same-origin', body: formData }).then(handle);
}

export function del(url) {
  return fetch(url, { method: 'DELETE', credentials: 'same-origin' }).then(handle);
}

// Redirect to the right login page when the session is missing/expired.
export async function requireRole(role, loginPage) {
  const me = await getJSON('/api/auth/me');
  if (me.role !== role) {
    window.location.href = loginPage + window.location.search;
    return null;
  }
  return me;
}

export function logout() {
  return postJSON('/api/auth/logout', {}).then(() => { window.location.href = '/'; });
}
