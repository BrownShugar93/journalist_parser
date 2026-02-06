const els = {
  email: document.getElementById('email'),
  password: document.getElementById('password'),
  loginBtn: document.getElementById('loginBtn'),
  registerBtn: document.getElementById('registerBtn'),
  loginHint: document.getElementById('loginHint'),
  loginPanel: document.getElementById('loginPanel'),
  dashboardPanel: document.getElementById('dashboardPanel'),
  accountInfo: document.getElementById('accountInfo'),
  logoutBtn: document.getElementById('logoutBtn'),
  startDate: document.getElementById('startDate'),
  endDate: document.getElementById('endDate'),
  keywords: document.getElementById('keywords'),
  channels: document.getElementById('channels'),
  videosOnly: document.getElementById('videosOnly'),
  runBtn: document.getElementById('runBtn'),
  runHint: document.getElementById('runHint'),
  results: document.getElementById('results'),
  linksOutput: document.getElementById('linksOutput'),
  downloadCsv: document.getElementById('downloadCsv'),
  downloadTxt: document.getElementById('downloadTxt'),
  introText: document.getElementById('introText'),
  introCursor: document.getElementById('introCursor'),
  legalBtn: document.getElementById('legalBtn'),
  legalModal: document.getElementById('legalModal'),
  legalClose: document.getElementById('legalClose'),
  legalCloseBtn: document.getElementById('legalCloseBtn'),
  tariffsBtn: document.getElementById('tariffsBtn'),
  tariffsModal: document.getElementById('tariffsModal'),
  tariffsClose: document.getElementById('tariffsClose'),
  tariffsCloseBtn: document.getElementById('tariffsCloseBtn'),
  registerModal: document.getElementById('registerModal'),
  registerClose: document.getElementById('registerClose'),
  registerCloseBtn: document.getElementById('registerCloseBtn'),
  regEmail: document.getElementById('regEmail'),
  regPassword: document.getElementById('regPassword'),
  regPassword2: document.getElementById('regPassword2'),
  registerSubmit: document.getElementById('registerSubmit'),
  registerHint: document.getElementById('registerHint'),
};

const store = {
  get token() { return localStorage.getItem('token'); },
  set token(v) { if (v) localStorage.setItem('token', v); else localStorage.removeItem('token'); },
  get apiUrl() { return localStorage.getItem('apiUrl') || ''; },
  set apiUrl(v) { if (v) localStorage.setItem('apiUrl', v); },
};

function setStatus(text) {
  if (els.statusText) {
    els.statusText.textContent = text;
  }
}

function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

function todayISO() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function csvBlob(rows) {
  const header = 'link,text\n';
  const lines = rows.map(([link, text]) => {
    const esc = (s) => '"' + String(s).replace(/"/g, '""') + '"';
    return `${esc(link)},${esc(text)}`;
  });
  return new Blob([header + lines.join('\n') + '\n'], { type: 'text/csv' });
}

function txtBlob(links) {
  return new Blob([links.join('\n') + '\n'], { type: 'text/plain' });
}

async function apiFetch(path, options = {}) {
  const apiUrl = (window.API_URL || '').trim() || store.apiUrl || 'http://localhost:8000';
  if (!apiUrl) throw new Error('API URL не задан');
  const headers = options.headers || {};
  if (store.token) headers['Authorization'] = `Bearer ${store.token}`;
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${apiUrl}${path}`, { ...options, headers });
  return res;
}

async function loadMe() {
  const res = await apiFetch('/auth/me');
  if (res.status !== 200) {
    throw new Error('Не удалось получить статус');
  }
  return res.json();
}

function setAccountInfo(me) {
  const remaining = me.daily_runs_remaining ?? 0;
  els.accountInfo.textContent = `Запусков осталось сегодня: ${remaining}`;
}

async function init() {
  const greeting = 'Quaerendo invenietis. Ища, найдёте.';
  if (els.introText && els.introCursor && !els.introText.dataset.typed) {
    let i = 0;
    els.introText.textContent = '';
    els.introCursor.classList.add('hidden');
    const timer = setInterval(() => {
      els.introText.textContent = greeting.slice(0, i + 1);
      i += 1;
      if (i >= greeting.length) {
        clearInterval(timer);
        els.introText.dataset.typed = '1';
        els.introCursor.classList.remove('hidden');
      }
    }, 56);
  }

  const apiUrl = (window.API_URL || '').trim() || store.apiUrl || 'http://localhost:8000';
  store.apiUrl = apiUrl;
  els.startDate.value = todayISO();
  els.endDate.value = todayISO();

  if (store.token) {
    try {
      const me = await loadMe();
      hide(els.loginPanel);
      show(els.dashboardPanel);
      setAccountInfo(me);
      setStatus('Онлайн');
      return;
    } catch (e) {
      store.token = null;
    }
  }

  show(els.loginPanel);
  hide(els.dashboardPanel);
  setStatus('Ожидание входа');
}

els.loginBtn.addEventListener('click', async () => {
  els.loginHint.textContent = '';

  try {
    const res = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: els.email.value.trim(),
        password: els.password.value,
      }),
    });

    if (res.status !== 200) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Ошибка входа');
    }

    const data = await res.json();
    store.token = data.token;
    await init();
  } catch (e) {
    els.loginHint.textContent = e.message;
  }
});

function openRegister() {
  els.registerModal.classList.remove('hidden');
  els.registerModal.setAttribute('aria-hidden', 'false');
  if (els.registerHint) els.registerHint.textContent = '';
}

function closeRegister() {
  els.registerModal.classList.add('hidden');
  els.registerModal.setAttribute('aria-hidden', 'true');
}

if (els.registerBtn) {
  els.registerBtn.addEventListener('click', openRegister);
}
if (els.registerClose) {
  els.registerClose.addEventListener('click', closeRegister);
}
if (els.registerCloseBtn) {
  els.registerCloseBtn.addEventListener('click', closeRegister);
}

if (els.registerSubmit) {
  els.registerSubmit.addEventListener('click', async () => {
    if (els.registerHint) els.registerHint.textContent = '';
    const email = (els.regEmail.value || '').trim();
    const p1 = els.regPassword.value || '';
    const p2 = els.regPassword2.value || '';

    if (!email || !p1 || !p2) {
      els.registerHint.textContent = 'Заполни все поля.';
      return;
    }
    if (p1 !== p2) {
      els.registerHint.textContent = 'Пароли не совпадают.';
      return;
    }

    try {
      const res = await apiFetch('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password: p1 }),
      });

      if (res.status !== 200) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Ошибка регистрации');
      }

      const data = await res.json();
      store.token = data.token;
      closeRegister();
      await init();
    } catch (e) {
      els.registerHint.textContent = e.message;
    }
  });
}

els.logoutBtn.addEventListener('click', async () => {
  try {
    await apiFetch('/auth/logout', { method: 'POST' });
  } catch (_) {}
  store.token = null;
  await init();
});

els.videosOnly.addEventListener('click', () => {
  const isActive = els.videosOnly.classList.toggle('is-active');
  els.videosOnly.dataset.active = isActive ? '1' : '0';
});

els.runBtn.addEventListener('click', async () => {
  els.runHint.textContent = '';
  els.results.classList.add('hidden');
  els.linksOutput.textContent = '';

  const keywords = els.keywords.value
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
  const channels = els.channels.value
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  if (!keywords.length) {
    els.runHint.textContent = 'Ключевые слова пустые.';
    return;
  }
  if (!channels.length) {
    els.runHint.textContent = 'Каналы пустые.';
    return;
  }

  const payload = {
    channels,
    keywords,
    start_date: els.startDate.value,
    end_date: els.endDate.value,
    videos_only: els.videosOnly.classList.contains('is-active'),
  };

  els.runBtn.disabled = true;
  els.runBtn.textContent = 'Поиск...';

  try {
    const res = await apiFetch('/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (res.status !== 200) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Ошибка');
    }

    const data = await res.json();
    const links = data.links || [];
    const rows = data.rows || [];

    els.linksOutput.textContent = links.join('\n');
    els.results.classList.remove('hidden');

    els.downloadCsv.onclick = () => {
      const blob = csvBlob(rows);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'tg_links.csv';
      a.click();
      URL.revokeObjectURL(url);
    };

    els.downloadTxt.onclick = () => {
      const blob = txtBlob(links);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'tg_links.txt';
      a.click();
      URL.revokeObjectURL(url);
    };

    const me = await loadMe();
    setAccountInfo(me);
  } catch (e) {
    els.runHint.textContent = e.message;
  } finally {
    els.runBtn.disabled = false;
    els.runBtn.textContent = 'Запуск';
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (els.registerModal && !els.registerModal.classList.contains('hidden')) {
    closeRegister();
  }
});

init();
