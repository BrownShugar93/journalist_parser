const els = {
  loginBtn: document.getElementById('loginBtn'),
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
  resultsPanel: document.getElementById('resultsPanel'),
  splash: document.getElementById('splash'),
  workspace: document.getElementById('workspace'),
  linksOutput: document.getElementById('linksOutput'),
  downloadCsv: document.getElementById('downloadCsv'),
  downloadTxt: document.getElementById('downloadTxt'),
  introText: document.getElementById('introText'),
  introCursor: document.getElementById('introCursor'),
  channelList: document.getElementById('channelList'),
};

const store = {
  get token() { return localStorage.getItem('token'); },
  set token(v) { if (v) localStorage.setItem('token', v); else localStorage.removeItem('token'); },
  get apiUrl() { return localStorage.getItem('apiUrl') || ''; },
  set apiUrl(v) { if (v) localStorage.setItem('apiUrl', v); },
};

const GUEST_MODE = window.GUEST_MODE === true;

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

const channelLists = {
  voenkory: [
    'https://t.me/dontstopwar',
    'https://t.me/mod_russia',
    'https://t.me/rogozin_do',
    'https://t.me/ramzayiegokomanda',
    'https://t.me/warhistoryalconafter',
    'https://t.me/epoddubny',
    'https://t.me/svodkidpr180',
    'https://t.me/orchestra_w',
    'https://t.me/notes_veterans',
    'https://t.me/rusich_army',
    'https://t.me/zvezdanews',
    'https://t.me/RVvoenkor',
    'https://t.me/akashevarova',
    'https://t.me/Sladkov_plus',
    'https://t.me/ghost_of_novorossia',
    'https://t.me/panteri_panteri',
    'https://t.me/creamy_caprice',
    'https://t.me/prolivstalina',
    'https://t.me/z4lpr',
    'https://t.me/Lunay14',
    'https://t.me/ttambyl',
    'https://t.me/UAVDEV',
    'https://t.me/sudoplatov_official',
    'https://t.me/vault8pro',
    'https://t.me/MSP1307',
    'https://t.me/tulaovod',
    'https://t.me/russian_shock_volunteer_brigade',
    'https://t.me/RUSSIARB',
    'https://t.me/dronnitsa',
    'https://t.me/song_infantry',
    'https://t.me/voron_fpv',
    'https://t.me/battalion106',
    'https://t.me/video_s_svo',
    'https://t.me/operationall_space',
    'https://t.me/korobov_latyncev',
    'https://t.me/voickokipchaka',
    'https://t.me/heartlandfire',
    'https://t.me/DKulko',
    'https://t.me/ChDambiev',
    'https://t.me/Warhronika',
    'https://t.me/btr80',
    'https://t.me/sashakots',
  ],
  news: [
    'https://t.me/rian_ru',
    'https://t.me/tass_agency',
    'https://t.me/rbc_news',
    'https://t.me/kommersant',
    'https://t.me/izvestia',
    'https://t.me/gazetaru',
    'https://t.me/truekpru',
    'https://t.me/vestiru24',
    'https://t.me/ntvnews',
    'https://t.me/rentv_news',
    'https://t.me/rt_russian',
    'https://t.me/lentadnya',
    'https://t.me/meduzalive',
    'https://t.me/mash',
    'https://t.me/breakingmash',
    'https://t.me/bazabazon',
    'https://t.me/shot_shot',
    'https://t.me/readovkanews',
    'https://t.me/ostorozhno_novosti',
    'https://t.me/dimsmirnov175',
  ],
  custom: [],
};

function applyChannelList(key) {
  const list = channelLists[key] || [];
  els.channels.value = list.join('\n');
}

async function init() {
  const apiUrl = (window.API_URL || '').trim() || store.apiUrl || 'http://localhost:8000';
  store.apiUrl = apiUrl;
  els.startDate.value = todayISO();
  els.endDate.value = todayISO();

  show(els.splash);
  hide(els.workspace);
  setStatus('');
}

els.loginBtn.addEventListener('click', async () => {
  els.loginHint.textContent = '';
  hide(els.splash);
  show(els.workspace);
  show(els.dashboardPanel);
  show(els.resultsPanel);
  els.accountInfo.textContent = 'Гостевой режим';
  if (els.channelList) {
    if (!els.channelList.value) els.channelList.value = 'custom';
    if (!els.channels.value.trim() && els.channelList.value !== 'custom') {
      applyChannelList(els.channelList.value);
    }
  }
});

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

if (els.channelList) {
  els.channelList.addEventListener('change', () => {
    const val = els.channelList.value;
    if (val === 'custom') {
      els.channels.value = '';
      return;
    }
    applyChannelList(val);
  });
}

if (els.channels && els.channelList) {
  els.channels.addEventListener('input', () => {
    if (els.channelList.value !== 'custom') {
      els.channelList.value = 'custom';
    }
  });
}

els.runBtn.addEventListener('click', async () => {
  els.runHint.textContent = '';
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

    els.linksOutput.textContent = links.length ? links.join('\n') : 'Пока пусто.';

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
});

init();
