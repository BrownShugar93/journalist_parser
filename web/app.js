const els = {
  loginBtn: document.getElementById('loginBtn'),
  loginHint: document.getElementById('loginHint'),
  splash: document.getElementById('splash'),
  workspace: document.getElementById('workspace'),
  openChannels: document.getElementById('openChannels'),
  openKeywords: document.getElementById('openKeywords'),
  openDates: document.getElementById('openDates'),
  channelsSummary: document.getElementById('channelsSummary'),
  keywordsSummary: document.getElementById('keywordsSummary'),
  datesSummary: document.getElementById('datesSummary'),
  videosOnly: document.getElementById('videosOnly'),
  runBtn: document.getElementById('runBtn'),
  progressWrap: document.getElementById('progressWrap'),
  progressBar: document.getElementById('progressBar'),
  logBox: document.getElementById('logBox'),
  resultsPanel: document.getElementById('resultsPanel'),
  linksOutput: document.getElementById('linksOutput'),
  downloadCsv: document.getElementById('downloadCsv'),
  downloadTxt: document.getElementById('downloadTxt'),
  channelsModal: document.getElementById('channelsModal'),
  keywordsModal: document.getElementById('keywordsModal'),
  datesModal: document.getElementById('datesModal'),
  channelList: document.getElementById('channelList'),
  channels: document.getElementById('channels'),
  keywords: document.getElementById('keywords'),
  excludeKeywords: document.getElementById('excludeKeywords'),
  startDate: document.getElementById('startDate'),
  endDate: document.getElementById('endDate'),
};

const store = {
  get apiUrl() { return localStorage.getItem('apiUrl') || ''; },
  set apiUrl(v) { if (v) localStorage.setItem('apiUrl', v); },
};

let activeRunSeq = 0;
const MAX_STATUS_WAIT_MS = 12 * 60 * 1000;

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
    'https://t.me/NgP_raZVedka',
    'https://t.me/periodu',
    'https://t.me/alchemiedeslebens',
    'https://t.me/texBPLA',
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
  chp_omsk: [
    'https://t.me/chp_55',
    'https://t.me/chpomsk',
    'https://t.me/omsk_vk',
    'https://t.me/omsk_signal',
    'https://t.me/omskonlain',
    'https://t.me/omsk_55reg',
    'https://t.me/chp_omsk',
  ],
  chp_tyumen: [
    'https://t.me/tumen_chp',
    'https://t.me/smi_tyumen',
    'https://t.me/chp_tyumen',
    'https://t.me/tyumen_xxxx',
    'https://t.me/dtpichptyumen',
  ],
  custom: [],
};

function applyChannelList(key) {
  const list = channelLists[key] || [];
  els.channels.value = list.join('\n');
}

function openModal(modal) {
  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
}

function closeModal(modal) {
  modal.classList.add('hidden');
  modal.setAttribute('aria-hidden', 'true');
}

function updateRunState() {
  const hasChannels = (els.channels.value || '').trim().length > 0;
  const hasKeywords = (els.keywords.value || '').trim().length > 0;
  const hasDates = (els.startDate.value || '').trim() && (els.endDate.value || '').trim();
  const ok = hasChannels && hasKeywords && hasDates;
  els.runBtn.disabled = !ok;
  els.runBtn.classList.toggle('enabled', ok);

  const chCount = (els.channels.value || '').split(/\n/).map((s) => s.trim()).filter(Boolean).length;
  const kwCount = (els.keywords.value || '').split(/[\n,]/).map((s) => s.trim()).filter(Boolean).length;
  const exCount = (els.excludeKeywords.value || '').split(/[\n,]/).map((s) => s.trim()).filter(Boolean).length;
  els.channelsSummary.textContent = chCount ? `Выбрано каналов: ${chCount}` : 'Не выбраны';
  if (kwCount || exCount) {
    const exPart = exCount ? `, минус: ${exCount}` : '';
    els.keywordsSummary.textContent = `Ключей: ${kwCount}${exPart}`;
  } else {
    els.keywordsSummary.textContent = 'Не выбраны';
  }
  if (els.startDate.value && els.endDate.value) {
    els.datesSummary.textContent = `Период: ${els.startDate.value} → ${els.endDate.value}`;
  } else {
    els.datesSummary.textContent = 'Не выбраны';
  }
}

function log(msg) {
  els.logBox.textContent = msg;
}

async function apiFetch(path, options = {}) {
  const apiUrl = (window.API_URL || '').trim() || store.apiUrl || 'http://localhost:8000';
  store.apiUrl = apiUrl;
  const headers = options.headers || {};
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${apiUrl}${path}`, { ...options, headers });
  return res;
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

els.loginBtn.addEventListener('click', () => {
  els.splash.classList.add('hidden');
  els.workspace.classList.remove('hidden');
});

els.openChannels.addEventListener('click', () => openModal(els.channelsModal));
els.openKeywords.addEventListener('click', () => openModal(els.keywordsModal));
els.openDates.addEventListener('click', () => openModal(els.datesModal));

els.channelList.addEventListener('change', () => {
  if (els.channelList.value === 'custom') {
    els.channels.value = '';
  } else {
    applyChannelList(els.channelList.value);
  }
  updateRunState();
});

els.channels.addEventListener('input', () => {
  if (els.channelList.value !== 'custom') {
    els.channelList.value = 'custom';
  }
  updateRunState();
});

els.keywords.addEventListener('input', updateRunState);
els.excludeKeywords.addEventListener('input', updateRunState);
els.startDate.addEventListener('change', updateRunState);
els.endDate.addEventListener('change', updateRunState);

els.runBtn.addEventListener('click', async () => {
  if (els.runBtn.disabled) return;
  activeRunSeq += 1;
  const runSeq = activeRunSeq;
  els.resultsPanel.classList.add('hidden');
  els.linksOutput.textContent = '';
  els.progressWrap.classList.remove('hidden');
  els.progressBar.style.width = '10%';
  log('Запрос отправлен...');

  const payload = {
    channels: (els.channels.value || '').split(/\n/).map((s) => s.trim()).filter(Boolean),
    keywords: (els.keywords.value || '').split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
    exclude_keywords: (els.excludeKeywords.value || '').split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
    start_date: els.startDate.value,
    end_date: els.endDate.value,
    videos_only: els.videosOnly.classList.contains('is-active'),
  };
  try {
    log('Создаю задачу...');
    const startRes = await apiFetch('/search/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (startRes.status !== 200) {
      const data = await startRes.json().catch(() => ({}));
      throw new Error(data.detail || 'Ошибка');
    }
    const { job_id } = await startRes.json();
    if (!job_id) throw new Error('Не получил job_id');

    const startedAt = Date.now();
    let done = false;
    while (!done) {
      if (runSeq !== activeRunSeq) {
        throw new Error('Запуск отменён новым запросом');
      }
      if (Date.now() - startedAt > MAX_STATUS_WAIT_MS) {
        throw new Error('Таймаут ожидания результата. Повтори запуск.');
      }
      const st = await apiFetch(`/search/status/${job_id}`);
      if (st.status !== 200) {
        const data = await st.json().catch(() => ({}));
        throw new Error(data.detail || 'Ошибка статуса');
      }
      const data = await st.json();
      const pct = Math.max(0, Math.min(100, data.progress || 0));
      els.progressBar.style.width = `${pct}%`;
      if (data.log) log(data.log);
      if (data.error) throw new Error(data.error);
      if (data.done) {
        const links = data.links || [];
        const rows = data.rows || [];
        const cleaned = links
          .flatMap((l) => String(l).split(/[\r\n]+/))
          .map((s) => s.trim())
          .filter(Boolean);
        els.linksOutput.textContent = cleaned.length ? cleaned.join('\n') : 'Пока пусто.';
        els.resultsPanel.classList.remove('hidden');

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

        log('Готово');
        done = true;
      } else {
        await new Promise((r) => setTimeout(r, 800));
      }
    }
  } catch (e) {
    log(e?.message || String(e));
  } finally {
    if (runSeq !== activeRunSeq) return;
    els.progressBar.style.width = '100%';
    setTimeout(() => {
      els.progressWrap.classList.add('hidden');
      els.progressBar.style.width = '0%';
    }, 600);
  }
});

els.videosOnly.addEventListener('click', () => {
  els.videosOnly.classList.toggle('is-active');
});

Array.from(document.querySelectorAll('[data-close]')).forEach((el) => {
  el.addEventListener('click', () => {
    const key = el.getAttribute('data-close');
    const modal = key === 'channels' ? els.channelsModal : key === 'keywords' ? els.keywordsModal : els.datesModal;
    closeModal(modal);
  });
});

window.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  [els.channelsModal, els.keywordsModal, els.datesModal].forEach((m) => m && closeModal(m));
});

updateRunState();
