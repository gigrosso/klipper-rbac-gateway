/* klipper-rbac-gateway — "Users" tab inside Mainsail's Interface Settings (admins only)
   and the name of who created each file/folder in the G-code file list (everyone). */
(() => {
  'use strict';
  if (window.__rbacUi) return;
  window.__rbacUi = true;

  const API = '/_rbac/api';
  const ICON_USERS = 'M16 17V19H2V17S2 13 9 13 16 17 16 17M12.5 7.5A3.5 3.5 0 1 0 9 11A3.5 3.5 0 0 0 12.5 7.5M15.94 13A5.32 5.32 0 0 1 18 17V19H22V17S22 13.37 15.94 13M15 4A3.39 3.39 0 0 0 13.07 4.59A5 5 0 0 1 13.07 10.41A3.39 3.39 0 0 0 15 11A3.5 3.5 0 0 0 15 4Z';
  const ICON_LOCK = 'M12,17A2,2 0 0,0 14,15C14,13.89 13.1,13 12,13A2,2 0 0,0 10,15A2,2 0 0,0 12,17M18,8A2,2 0 0,1 20,10V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V10C4,8.89 4.9,8 6,8H7V6A5,5 0 0,1 12,1A5,5 0 0,1 17,6V8H18M12,3A3,3 0 0,0 9,6V8H15V6A3,3 0 0,0 12,3Z';
  const ROLE_NAMES = { viewer: 'Viewer', operator: 'Operator', admin: 'Admin' };
  const ROLE_HINTS = { viewer: 'view only', operator: 'prints and operates the machine', admin: 'full access' };

  const CSS = `
  .rbac-panel{position:absolute;inset:0;overflow:auto;padding:16px 20px;z-index:5;font-size:14px;color:rgba(255,255,255,.87)}
  .rbac-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}
  .rbac-top h3{margin:0;font-size:1.1rem;font-weight:500}
  .rbac-btn{border:0;border-radius:4px;padding:0 16px;height:36px;font-family:inherit;font-size:.875rem;font-weight:500;
    letter-spacing:.089em;text-transform:uppercase;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
  .rbac-btn-primary{background:var(--rbac-primary,#2196f3);color:#fff}
  .rbac-btn-danger{background:#ff5252;color:#fff}
  .rbac-btn-text{background:transparent;color:rgba(255,255,255,.87)}
  .rbac-btn-text:hover{background:rgba(255,255,255,.08)}
  .rbac-btn:disabled{background:rgba(255,255,255,.12)!important;color:rgba(255,255,255,.3)!important;cursor:not-allowed}
  .rbac-table{width:100%;border-collapse:collapse;border:1px solid rgba(255,255,255,.12)}
  .rbac-table th{text-align:left;font-size:.75rem;font-weight:500;color:rgba(255,255,255,.6);padding:10px 12px;
    border-bottom:1px solid rgba(255,255,255,.12)}
  .rbac-table td{padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.08)}
  .rbac-table tr:last-child td{border-bottom:0}
  .rbac-table tbody tr:hover{background:rgba(255,255,255,.04)}
  .rbac-col-check{width:44px}
  .rbac-table input[type=checkbox]{width:18px;height:18px;accent-color:var(--rbac-primary,#2196f3);cursor:pointer;vertical-align:middle}
  .rbac-table input[type=checkbox]:disabled{cursor:not-allowed;opacity:.35}
  .rbac-chip{display:inline-flex;align-items:center;gap:6px;border-radius:16px;padding:4px 12px;font-family:inherit;
    font-size:.8rem;border:1px solid currentColor;background:transparent;cursor:pointer}
  .rbac-chip:not(:disabled):hover{background:rgba(255,255,255,.08)}
  .rbac-chip:disabled{cursor:default}
  .rbac-r-admin{color:#ef5350}.rbac-r-operator{color:#ffa726}.rbac-r-viewer{color:#90a4ae}
  .rbac-you{font-size:.72rem;color:rgba(255,255,255,.5);margin-left:6px}
  .rbac-footer{margin-top:16px}
  .rbac-empty{text-align:center;color:rgba(255,255,255,.5)}
  .rbac-error{background:rgba(255,82,82,.12);color:#ff8a80;border-radius:4px;padding:8px 12px;font-size:.85rem}
  .rbac-backdrop{position:absolute;inset:0;pointer-events:auto;background:rgba(0,0,0,.6);display:flex;align-items:center;
    justify-content:center;z-index:1000}
  .rbac-modal{width:min(92vw,420px);border-radius:6px;box-shadow:0 11px 15px -7px rgba(0,0,0,.4),0 24px 38px 3px rgba(0,0,0,.28);
    color:rgba(255,255,255,.87);font-size:14px;background:#1e1e1e}
  .rbac-modal header{padding:14px 20px;font-size:1.1rem;font-weight:500;border-bottom:1px solid rgba(255,255,255,.12)}
  .rbac-modal .rbac-body{padding:16px 20px;display:grid;gap:14px}
  .rbac-modal footer{display:flex;justify-content:flex-end;gap:8px;padding:12px 20px;border-top:1px solid rgba(255,255,255,.12)}
  .rbac-field label{display:block;font-size:.75rem;color:rgba(255,255,255,.6);margin-bottom:4px}
  .rbac-field input,.rbac-field select{width:100%;height:40px;padding:0 12px;border-radius:4px;border:1px solid rgba(255,255,255,.24);
    background:rgba(255,255,255,.04);color:inherit;font-family:inherit;font-size:.95rem;outline:none}
  .rbac-field input:focus,.rbac-field select:focus{border-color:var(--rbac-primary,#2196f3)}
  .rbac-field select option{background:#1e1e1e;color:#fff}
  .rbac-help{font-size:.75rem;color:rgba(255,255,255,.5);margin-top:4px}
  .rbac-text{margin:0;line-height:1.5}
  .rbac-hide-active .v-tab--active:not(.rbac-tab){color:rgba(255,255,255,.6)!important}
  .rbac-hide-active .v-tab--active:not(.rbac-tab)::before{opacity:0!important}
  .rbac-hide-active .v-tabs-slider-wrapper{display:none!important}
  .rbac-tab.rbac-tab--active{color:var(--rbac-primary,#2196f3)!important;box-shadow:inset 2px 0 0 var(--rbac-primary,#2196f3)}
  .rbac-owner{display:inline-flex;align-items:center;gap:3px;margin-left:8px;padding:0 7px;border-radius:10px;
    font-size:.72rem;line-height:18px;vertical-align:middle;white-space:nowrap;color:rgba(255,255,255,.6);background:rgba(255,255,255,.08)}
  .rbac-owner--you{color:var(--rbac-primary,#2196f3);background:rgba(33,150,243,.12)}
  .rbac-owner--none{font-style:italic;color:rgba(255,255,255,.4);background:transparent;border:1px dashed rgba(255,255,255,.2)}
  `;

  const state = { users: [], roles: ['viewer', 'operator', 'admin'], selected: new Set() };
  let panel = null, contentCol = null, rbacTab = null, tabsEl = null, originalMinHeight = '', backdrop = null;

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const svg = (d, size = 16) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path fill="currentColor" d="${d}"/></svg>`;

  async function api(method, path, body) {
    const r = await fetch(API + path, {
      method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Rbac': '1' },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await r.json(); } catch (e) { /* empty body */ }
    if (!r.ok) throw new Error(data.error || `Error ${r.status}`);
    return data;
  }

  function backgroundOf(el) {
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const bg = getComputedStyle(n).backgroundColor;
      if (bg && bg !== 'transparent' && !/rgba\(\s*0,\s*0,\s*0,\s*0\s*\)/.test(bg)) return bg;
    }
    return '#1e1e1e';
  }

  // ------------------------------------------------------------------ tab
  function settingsDialog() {
    for (const d of document.querySelectorAll('.v-dialog.v-dialog--active')) {
      const tabs = d.querySelector('.v-tabs--vertical');
      if (tabs) return { dialog: d, tabs };
    }
    return null;
  }

  function installTab() {
    const found = settingsDialog();
    if (!found) {
      if (panel && panel.isConnected) hidePanel();
      return;
    }
    const { tabs } = found;
    if (tabs.querySelector('.rbac-tab')) return;
    const existing = tabs.querySelectorAll('.v-tab');
    if (!existing.length) return;

    const active = tabs.querySelector('.v-tab--active');
    if (active) document.documentElement.style.setProperty('--rbac-primary', getComputedStyle(active).color);

    const template = existing[existing.length - 1];
    const tab = template.cloneNode(true);
    tab.classList.remove('v-tab--active');
    tab.classList.add('rbac-tab');
    tab.removeAttribute('href');
    tab.removeAttribute('aria-selected');
    tab.setAttribute('role', 'tab');
    tab.tabIndex = 0;
    const iconPath = tab.querySelector('svg path');
    if (iconPath) iconPath.setAttribute('d', ICON_USERS);
    const walker = document.createTreeWalker(tab, NodeFilter.SHOW_TEXT);
    let lastText = null;
    while (walker.nextNode()) if (walker.currentNode.textContent.trim()) lastText = walker.currentNode;
    if (lastText) lastText.textContent = ' Users ';
    else tab.append('Users');

    const open = e => { e.preventDefault(); e.stopPropagation(); showPanel(tabs, tab); };
    tab.addEventListener('click', open);
    tab.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') open(e); });
    template.after(tab);

    // clicking any other tab closes the users panel
    tabs.addEventListener('click', e => {
      const t = e.target.closest('.v-tab');
      if (t && !t.classList.contains('rbac-tab')) hidePanel();
    }, true);
  }

  function showPanel(tabs, tab) {
    const col = tabs.closest('.col, .col-auto, [class^="col-"], [class*=" col-"]');
    contentCol = (col && col.nextElementSibling) || tabs.closest('.v-dialog').querySelector('.v-card__text') || tabs.closest('.v-dialog');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'rbac-panel';
      panel.addEventListener('click', onPanelClick);
      panel.addEventListener('change', onCheck);
    }
    panel.style.background = backgroundOf(contentCol);
    if (getComputedStyle(contentCol).position === 'static') contentCol.style.position = 'relative';
    originalMinHeight = contentCol.style.minHeight;
    contentCol.style.minHeight = '460px';
    contentCol.appendChild(panel);
    tabs.classList.add('rbac-hide-active');
    tab.classList.add('rbac-tab--active');
    rbacTab = tab;
    tabsEl = tabs;
    load();
  }

  function hidePanel() {
    closeModal();
    if (panel) panel.remove();
    if (contentCol) contentCol.style.minHeight = originalMinHeight;
    if (tabsEl) tabsEl.classList.remove('rbac-hide-active');
    if (rbacTab) rbacTab.classList.remove('rbac-tab--active');
  }

  // ------------------------------------------------------------------ panel
  async function load() {
    panel.innerHTML = '<div class="rbac-empty">Loading…</div>';
    try {
      const d = await api('GET', '/users');
      state.users = d.users;
      state.roles = d.roles;
      state.selected = new Set([...state.selected].filter(u => d.users.some(x => x.username === u && !x.primary && !x.self)));
      render();
    } catch (e) {
      panel.innerHTML = `<div class="rbac-error">${esc(e.message)}</div>`;
    }
  }

  function render() {
    const rows = state.users.map(u => {
      const locked = u.primary || u.self;
      const chipHint = u.primary ? 'Primary admin: the role cannot be changed'
        : u.self ? 'You cannot change your own role' : 'Click to change the role';
      const checkHint = u.primary ? 'The primary admin cannot be deleted'
        : u.self ? 'You cannot delete yourself' : 'Select';
      return `<tr>
        <td class="rbac-col-check"><input type="checkbox" data-u="${esc(u.username)}" title="${checkHint}"
          ${state.selected.has(u.username) ? 'checked' : ''} ${locked ? 'disabled' : ''}></td>
        <td>${esc(u.username)}${u.self ? '<span class="rbac-you">(you)</span>' : ''}</td>
        <td><button type="button" class="rbac-chip rbac-r-${esc(u.role)}" data-action="role" data-u="${esc(u.username)}"
          title="${chipHint}" ${locked ? 'disabled' : ''}>${u.primary ? svg(ICON_LOCK, 14) : ''}${esc(ROLE_NAMES[u.role] || u.role)}</button></td>
      </tr>`;
    }).join('');
    panel.innerHTML = `
      <div class="rbac-top"><h3>Users</h3>
        <button type="button" class="rbac-btn rbac-btn-primary" data-action="new">${svg(ICON_USERS)} New user</button></div>
      <table class="rbac-table">
        <thead><tr><th class="rbac-col-check"></th><th>Username</th><th>Role</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="3" class="rbac-empty">No users</td></tr>'}</tbody>
      </table>
      <div class="rbac-footer"><button type="button" class="rbac-btn rbac-btn-danger" data-action="delete"></button></div>`;
    updateDeleteButton();
  }

  function updateDeleteButton() {
    const b = panel.querySelector('[data-action="delete"]');
    if (!b) return;
    const n = state.selected.size;
    b.disabled = n === 0;
    b.textContent = n > 1 ? `Delete users (${n})` : 'Delete user';
  }

  function onPanelClick(e) {
    const b = e.target.closest('[data-action]');
    if (!b || b.disabled) return;
    if (b.dataset.action === 'new') newUserModal();
    else if (b.dataset.action === 'role') changeRoleModal(b.dataset.u);
    else if (b.dataset.action === 'delete') deleteModal();
  }

  function onCheck(e) {
    const c = e.target;
    if (c.type !== 'checkbox' || !c.dataset.u) return;
    if (c.checked) state.selected.add(c.dataset.u);
    else state.selected.delete(c.dataset.u);
    updateDeleteButton();
  }

  // ------------------------------------------------------------------ modals
  function openModal(title, bodyHtml, okLabel, okClass, onConfirm) {
    closeModal();
    // Mounted inside .v-dialog so Vuetify neither steals focus nor blocks clicks.
    const host = (panel && panel.closest('.v-dialog')) || document.body;
    if (host !== document.body && getComputedStyle(host).position === 'static') host.style.position = 'relative';
    backdrop = document.createElement('div');
    backdrop.className = 'rbac-backdrop';
    if (host === document.body) backdrop.style.position = 'fixed';
    backdrop.innerHTML = `<div class="rbac-modal" role="dialog" aria-modal="true">
      <header>${esc(title)}</header>
      <form class="rbac-body" novalidate>${bodyHtml}
        <div class="rbac-error" hidden></div><button type="submit" hidden></button></form>
      <footer><button type="button" class="rbac-btn rbac-btn-text" data-m="cancel">Cancel</button>
        <button type="button" class="rbac-btn ${okClass}" data-m="ok">${esc(okLabel)}</button></footer></div>`;
    if (panel) backdrop.querySelector('.rbac-modal').style.background = panel.style.background;
    const form = backdrop.querySelector('form');
    const error = backdrop.querySelector('.rbac-error');
    const ok = backdrop.querySelector('[data-m="ok"]');
    const confirm = async () => {
      error.hidden = true;
      ok.disabled = true;
      try {
        await onConfirm(form);
        closeModal();
        await load();
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        ok.disabled = false;
      }
    };
    ok.addEventListener('click', confirm);
    form.addEventListener('submit', e => { e.preventDefault(); confirm(); });
    backdrop.querySelector('[data-m="cancel"]').addEventListener('click', closeModal);
    backdrop.addEventListener('mousedown', e => { if (e.target === backdrop) closeModal(); });
    backdrop.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); closeModal(); }
    });
    host.appendChild(backdrop);
    (form.querySelector('input, select') || ok).focus();
  }

  function closeModal() {
    if (backdrop) { backdrop.remove(); backdrop = null; }
  }

  const roleOptions = current => state.roles.map(r =>
    `<option value="${esc(r)}" ${r === current ? 'selected' : ''}>${esc(ROLE_NAMES[r] || r)} (${esc(ROLE_HINTS[r] || '')})</option>`).join('');

  function newUserModal() {
    openModal('New user', `
      <div class="rbac-field"><label>Username</label><input name="username" autocomplete="off" maxlength="32" spellcheck="false">
        <div class="rbac-help">2 to 32 characters: letters, digits, dot, hyphen and underscore</div></div>
      <div class="rbac-field"><label>Password</label><input name="password" type="password" autocomplete="new-password">
        <div class="rbac-help">At least 6 characters</div></div>
      <div class="rbac-field"><label>Confirm password</label><input name="password2" type="password" autocomplete="new-password"></div>
      <div class="rbac-field"><label>Role</label><select name="role">${roleOptions('viewer')}</select></div>`,
    'Create user', 'rbac-btn-primary', async f => {
      const username = f.elements.username.value.trim();
      const password = f.elements.password.value;
      if (!/^[A-Za-z0-9._-]{2,32}$/.test(username)) throw new Error('Invalid username.');
      if (password.length < 6) throw new Error('The password must have at least 6 characters.');
      if (password !== f.elements.password2.value) throw new Error('Passwords do not match.');
      await api('POST', '/users', { username, password, role: f.elements.role.value });
    });
  }

  function changeRoleModal(name) {
    const u = state.users.find(x => x.username === name);
    if (!u || u.primary || u.self) return;
    openModal('Change role', `
      <p class="rbac-text">User: <strong>${esc(name)}</strong><br>Current role: <strong>${esc(ROLE_NAMES[u.role] || u.role)}</strong></p>
      <div class="rbac-field"><label>New role</label><select name="role">${roleOptions(u.role)}</select>
        <div class="rbac-help">The change takes effect immediately, including for users already signed in.</div></div>`,
    'Confirm change', 'rbac-btn-primary', async f => {
      const role = f.elements.role.value;
      if (role === u.role) throw new Error('Choose a role different from the current one.');
      await api('PUT', `/users/${encodeURIComponent(name)}/role`, { role });
    });
  }

  function deleteModal() {
    const list = [...state.selected];
    if (!list.length) return;
    const many = list.length > 1;
    openModal(many ? 'Delete users' : 'Delete user', `
      <p class="rbac-text">Delete ${many ? 'users' : 'user'} <strong>${list.map(esc).join(', ')}</strong>?<br>
      Open sessions will be signed out. This cannot be undone.</p>`,
    'Delete', 'rbac-btn-danger', async () => {
      for (const name of list) {
        await api('DELETE', `/users/${encodeURIComponent(name)}`);
        state.selected.delete(name);
      }
    });
  }

  // ------------------------------------------------------------------ file owners
  // Rows of Mainsail's G-code file list are Vue 2 components: tr.__vue__ holds the item and the current folder.
  const ICON_PERSON = 'M12,4A4,4 0 0,1 16,8A4,4 0 0,1 12,12A4,4 0 0,1 8,8A4,4 0 0,1 12,4M12,14C16.42,14 20,15.79 20,18V20H4V18C4,15.79 7.58,14 12,14Z';
  const owners = { folder: null, map: {}, seen: new Set(), fetchedAt: 0, startedAt: 0, ok: false, fetching: false };
  const firstSeen = new Map();  // 'folder/name' -> when it first appeared in the list
  let myName = '';

  async function fetchOwners(folder, names) {
    if (owners.fetching) return;
    owners.fetching = true;
    const seen = new Set(names);
    const startedAt = Date.now();
    try {
      const d = await api('GET', `/owners?folder=${encodeURIComponent(folder)}`);
      Object.assign(owners, { folder, map: d.owners || {}, seen, fetchedAt: Date.now(), startedAt, ok: true });
    } catch (e) {
      Object.assign(owners, { folder, map: {}, seen, fetchedAt: Date.now(), startedAt, ok: false });
    } finally {
      owners.fetching = false;
    }
    markOwners();
  }

  function nameCell(tr, name) {
    for (const td of tr.children) {
      const t = td.firstChild;
      if (t && t.nodeType === Node.TEXT_NODE && t.data.trim() === name) return td;
    }
    return null;
  }

  function markOwners() {
    const rows = [];
    for (const tr of document.querySelectorAll('tr.file-list-cursor')) {
      const vm = tr.__vue__;
      if (!vm || !vm.item || typeof vm.item.filename !== 'string' || typeof vm.currentPath !== 'string') continue;
      if (typeof vm.deleteFile !== 'function' && typeof vm.deleteDirectory !== 'function') continue;
      rows.push({ tr, name: vm.item.filename, folder: 'gcodes' + vm.currentPath });
    }
    if (!rows.length) return;
    const folder = rows[0].folder;
    // what is already in the folder when it opens is old (0); what shows up later may be an upload in progress
    const now = folder === owners.folder ? Date.now() : 0;
    for (const r of rows) if (!firstSeen.has(`${r.folder}/${r.name}`)) firstSeen.set(`${r.folder}/${r.name}`, now);
    const stale = Date.now() - owners.fetchedAt > 15000;
    const newItem = rows.some(r => !owners.seen.has(r.name));  // a new file/folder appeared
    if (folder !== owners.folder || stale || newItem) fetchOwners(folder, rows.map(r => r.name));
    // the list may show up before the gateway records the owner: check again shortly after
    if (newItem && folder === owners.folder) setTimeout(() => { owners.fetchedAt = 0; markOwners(); }, 2500);
    if (folder !== owners.folder) return;
    for (const { tr, name } of rows) {
      const td = nameCell(tr, name);
      if (!td) continue;
      const owner = owners.map[name] || '';
      let tag = td.querySelector('.rbac-owner');
      // no owner: only mark it after a lookup made well after the item appeared (the gateway may
      // still be recording a fresh upload) and only if the lookup succeeded
      const noRecord = !owner && owners.ok && owners.startedAt - firstSeen.get(`${folder}/${name}`) >= 2000;
      if (!owner && !noRecord) { if (tag) tag.remove(); continue; }
      const key = owner || '-';
      if (tag && tag.dataset.owner === key) continue;
      if (!tag) { tag = document.createElement('span'); td.appendChild(tag); }
      tag.dataset.owner = key;
      if (noRecord) {
        tag.className = 'rbac-owner rbac-owner--none';
        tag.title = 'Created outside the gateway (SSH, direct copy...): no record of who created it. Only an admin can delete it.';
        tag.innerHTML = `${svg(ICON_PERSON, 12)}no record`;
        continue;
      }
      tag.className = 'rbac-owner' + (owner === myName ? ' rbac-owner--you' : '');
      tag.title = `Created by ${owner}`;
      tag.innerHTML = `${svg(ICON_PERSON, 12)}${esc(owner === myName ? `${owner} (you)` : owner)}`;
    }
  }

  // ------------------------------------------------------------------ start
  async function start() {
    let me;
    try { me = await api('GET', '/me'); } catch (e) { return; }
    myName = me.username;
    const admin = me.role === 'admin';
    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);
    const refresh = () => { if (admin) installTab(); markOwners(); };
    let scheduled = false;
    new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => { scheduled = false; refresh(); });
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    setInterval(markOwners, 5000);
    refresh();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
