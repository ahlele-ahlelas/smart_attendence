// Small UI helpers: toasts, modals, tabs, button loading, escaping.

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

let stack;
export function toast(message, kind = '') {
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'toast-stack';
    stack.setAttribute('role', 'status');
    stack.setAttribute('aria-live', 'polite');
    document.body.appendChild(stack);
  }
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ` toast--${kind}` : '');
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

// <dialog class="modal"> helpers. Markup contract:
// <dialog class="modal" id="x"><div class="modal-head"><h3>..</h3>
// <button class="modal-close">..</button></div><div class="modal-body">..</div></dialog>
export function openModal(id) {
  const dlg = document.getElementById(id);
  if (!dlg.dataset.wired) {
    dlg.dataset.wired = '1';
    dlg.querySelector('.modal-close')?.addEventListener('click', () => dlg.close());
    dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  }
  dlg.showModal();
  return dlg;
}
export function closeModal(id) { document.getElementById(id)?.close(); }

// Accessible tabs. Container: .tabs with [role=tab][data-panel=<id>] buttons.
export function wireTabs(container, onChange) {
  const tabs = [...container.querySelectorAll('[role="tab"]')];
  function select(tab) {
    tabs.forEach(t => {
      const on = t === tab;
      t.setAttribute('aria-selected', on);
      const panel = document.getElementById(t.dataset.panel);
      if (panel) panel.hidden = !on;
    });
    onChange?.(tab.dataset.panel);
  }
  tabs.forEach(t => t.addEventListener('click', () => select(t)));
  container.addEventListener('keydown', e => {
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    let next = null;
    if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
    if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
    if (next) { next.focus(); select(next); e.preventDefault(); }
  });
  return { select: id => select(tabs.find(t => t.dataset.panel === id) || tabs[0]) };
}

// Run an async action with a spinner on the button and errors as toasts.
export async function withBusy(btn, fn) {
  if (btn.classList.contains('is-loading')) return;
  btn.classList.add('is-loading');
  btn.disabled = true;
  try {
    return await fn();
  } catch (err) {
    toast(err.message || 'Something went wrong.', 'danger');
    return undefined;
  } finally {
    btn.classList.remove('is-loading');
    btn.disabled = false;
  }
}

export function meterClass(pct) {
  if (pct === null || pct === undefined) return '';
  if (pct >= 75) return 'meter-fill--ok';
  if (pct >= 50) return 'meter-fill--warn';
  return 'meter-fill--danger';
}

export function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(String(ts).replace(' ', 'T'));
  if (isNaN(d)) return ts;
  return d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
}
