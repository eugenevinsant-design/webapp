// Адрес бэкенда задаётся в js/config.js (window.__API_BASE_URL).
// Пустая строка -> относительные пути (локальный запуск, один процесс).
// Абсолютный URL -> GitHub Pages + отдельный GPU-сервер с FastAPI/vLLM.
const API_ROOT = (typeof window !== 'undefined' && window.__API_BASE_URL) || '';
const API_BASE = `${API_ROOT}/api/chat`;
const ECG_BASE = `${API_ROOT}/api/ecg`;
const AUTH_BASE = `${API_ROOT}/api/auth`;

const state = {
  sessionId: null,
  currentResponseId: null,
  history: [],
  packages: [],
};

const $ = (sel) => document.querySelector(sel);

// ---- Токен ----
function getToken() {
  return localStorage.getItem('api_token');
}

function setToken(token) {
  localStorage.setItem('api_token', token);
}

function clearToken() {
  localStorage.removeItem('api_token');
}

// Обертка для fetch с авторизацией
async function authFetch(url, options = {}) {
  const token = getToken();
  const headers = options.headers || {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return fetch(url, { ...options, headers });
}

// ---- Обработка ответов API ----
// Возвращает JSON или бросает понятную ошибку. 401 -> модалка входа, 503 -> LLM недоступна.
async function parseApiResponse(res) {
  if (res.status === 401) {
    showAuthModal();
    throw new Error('Требуется авторизация');
  }
  if (res.status === 503) {
    let detail = 'LLM-сервис недоступен. Повторите позже.';
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  if (!res.ok) {
    throw new Error('Ошибка API: ' + res.status);
  }
  return res.json();
}

// ---- API ----
async function apiChat(text) {
  const res = await authFetch(`${API_BASE}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, session_id: state.sessionId })
  });
  return parseApiResponse(res);
}

async function apiGrade(responseId, grade) {
  const res = await authFetch(`${API_BASE}/grade?session_id=${state.sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response_id: responseId, grade })
  });
  return parseApiResponse(res);
}

async function apiRegenerate(responseId) {
  const res = await authFetch(`${API_BASE}/regenerate?session_id=${state.sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response_id: responseId })
  });
  return parseApiResponse(res);
}

async function apiGetPackages() {
  const res = await authFetch(`${ECG_BASE}/`);
  return parseApiResponse(res);
}

async function apiGetHistory() {
  const res = await authFetch(`${API_BASE}/history?limit=50`);
  return parseApiResponse(res);
}

// Отрисовать реальную историю с сервера.
async function loadHistory() {
  const list = $('#history-list');
  try {
    const items = await apiGetHistory();
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<p class="empty-history">История пуста</p>';
      return;
    }
    items.forEach(it => {
      const div = document.createElement('div');
      div.className = 'history-item';
      const label = it.pkg ? `${it.pkg}` : 'без пакета';
      const grade = it.grade != null ? ` · оценка ${it.grade}/10` : '';
      div.textContent = `${label}${grade} — ${it.question || it.excerpt || ''}`.slice(0, 90);
      div.title = (it.excerpt || it.question || '');
      div.addEventListener('click', () => {
        if (it.pkg) {
          state.sessionId = it.session_id;
          addMessage(`Сессия ${it.session_id} · пакет ${it.pkg}`, 'bot');
        }
      });
      list.appendChild(div);
    });
  } catch (e) {
    console.error('Не удалось загрузить историю:', e);
  }
}

// ---- Markdown ----
// marked.js подключён локально (js/vendor/marked.min.js) — без CDN.
const markedLoaded = typeof marked !== 'undefined' && !window.__markedMissing;

// Экранирование HTML: защита от XSS при вставке пользовательских/серверных строк.
function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderBotMarkdown(text) {
  if (markedLoaded) {
    try {
      return marked.parse(text);
    } catch (e) {
      console.error('marked.parse упал, fallback на plain text:', e);
    }
  }
  // Fallback: безопасный plain text с переносами строк
  return escapeHtml(text).replace(/\n/g, '<br>');
}

function addMessage(text, sender) {
  const container = $('#chat-container');
  const div = document.createElement('div');
  div.className = `message ${sender}`;

  if (sender === 'bot') {
    div.innerHTML = renderBotMarkdown(text);
  } else {
    // Пользовательский текст — всегда как plain text, без HTML-интерпретации
    div.textContent = text;
  }

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function addHistory(text) {
  state.history.push(text);
  const list = $('#history-list');
  const empty = list.querySelector('.empty-history');
  if (empty) empty.remove();

  const div = document.createElement('div');
  div.className = 'history-item';
  div.textContent = text;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
}

// ---- График ЭКГ ----
const ECG_POINTS = 1000;

async function apiGetSignalData(signalId) {
  const res = await authFetch(`${ECG_BASE}/${signalId}/data`);
  return parseApiResponse(res);
}

function drawEcgChart(data) {
  const canvas = $('#ecg-chart');
  if (!canvas || !data || !Array.isArray(data.data) || !data.data.length) return;

  const panel = $('#ecg-chart-panel');
  panel.classList.remove('hidden');
  $('#ecg-chart-title').textContent = `Сигнал ${data.name}`;
  $('#ecg-chart-meta').textContent = `fs=${data.fs} Гц · точек: ${data.total_points}`;

  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 800;
  const cssH = 180;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.style.height = cssH + 'px';

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  // Сетка
  ctx.strokeStyle = 'rgba(95,191,220,0.10)';
  ctx.lineWidth = 1;
  for (let x = 0; x < cssW; x += 40) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, cssH); ctx.stroke();
  }
  for (let y = 0; y < cssH; y += 30) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(cssW, y); ctx.stroke();
  }

  const pts = data.data;
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const span = (max - min) || 1;
  const padY = 12;
  const usableH = cssH - padY * 2;

  ctx.beginPath();
  pts.forEach((v, i) => {
    const x = (i / (pts.length - 1)) * cssW;
    const y = padY + (1 - (v - min) / span) * usableH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = '#42eaff';
  ctx.lineWidth = 1.6;
  ctx.shadowColor = '#42eaff';
  ctx.shadowBlur = 8;
  ctx.stroke();
  ctx.shadowBlur = 0;
}

async function showEcgChart(signalId) {
  try {
    const data = await apiGetSignalData(signalId);
    drawEcgChart(data);
  } catch (e) {
    console.error('Не удалось загрузить данные графика:', e);
  }
}

function hideEcgChart() {
  $('#ecg-chart-panel').classList.add('hidden');
}

// Лоадер
function showLoader() {
  const container = $('#chat-container');
  const div = document.createElement('div');
  div.className = 'message bot loader';
  div.id = 'loader-message';
  div.textContent = 'Анализируем...';
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function hideLoader() {
  const loader = $('#loader-message');
  if (loader) loader.remove();
}

function showGradeActions(visible) {
  $('#grade-actions').classList.toggle('hidden', !visible);
}

function showRegenerateAction(visible) {
  $('#regenerate-action').classList.toggle('hidden', !visible);
}

// ---- Кастомный выпадающий список ----
let selectedPackage = null;

function toggleOptions() {
  const options = $('#package-options');
  const btn = $('#package-select-btn');
  options.classList.toggle('hidden');
  btn.classList.toggle('active');
}

function selectOption(name) {
  selectedPackage = name;
  $('#selected-package-text').textContent = name;
  const options = $('#package-options');
  const btn = $('#package-select-btn');
  options.classList.add('hidden');
  btn.classList.remove('active');
}

function renderOptions(packages) {
  const container = $('#package-options');
  container.innerHTML = '';
  if (!packages.length) {
    container.innerHTML = '<div class="custom-option">Нет доступных пакетов</div>';
    return;
  }
  packages.forEach(p => {
    const opt = document.createElement('div');
    opt.className = 'custom-option';
    opt.textContent = `${p.name} (${p.fs} Hz, ${p.n_sig} каналов)`;
    opt.addEventListener('click', () => selectOption(p.name));
    container.appendChild(opt);
  });
}

// ---- Загрузка пакетов ----
async function loadPackages() {
  try {
    const packages = await apiGetPackages();
    state.packages = packages;
    renderOptions(packages);
    $('#selected-package-text').textContent = 'Выберите пакет...';
  } catch (e) {
    console.error('Ошибка загрузки пакетов:', e);
    $('#selected-package-text').textContent = 'Ошибка загрузки';
  }
}

// ---- Статус LLM (ecgllm setup_llm/process_text) ----
async function loadLlmStatus() {
  const el = $('#llm-status');
  if (!el) return;
  try {
    const res = await authFetch(`${API_BASE}/llm-status`);
    const s = await parseApiResponse(res);
    const host = (s.url || '').replace(/^https?:\/\//, '').split('/')[0];
    el.innerHTML = s.via_module
      ? `LLM через ecgllm process_text<br><b>${escapeHtml(s.model)}</b> @ ${escapeHtml(host)}`
      : `LLM напрямую (httpx)<br><b>${escapeHtml(s.model)}</b> @ ${escapeHtml(host)}`;
    el.classList.toggle('ok', !!s.api_key_set || host.startsWith('llm') || host.startsWith('localhost') || host.startsWith('127.'));
    el.title = `url: ${s.url}\napi_key: ${s.api_key_set ? 'задан' : 'не задан'}\nmax_tokens: ${s.max_tokens}`;
  } catch (e) {
    el.textContent = 'LLM: статус недоступен';
    el.classList.add('err');
  }
}

// ---- Обработчики ----
async function handleAnalyze() {
  const pkgName = selectedPackage;
  if (!pkgName) {
    alert('Сначала выберите пакет из списка');
    return;
  }
  // Отправляем на сервер команду \choose_pkg (один бэкслеш в строке).
  const serverText = `\\choose_pkg ${pkgName} Сделай аннотацию этого сигнала`;

  addMessage(`Выбран сигнал: ${pkgName}. Запуск анализа...`, 'user');
  addHistory(`Выбран пакет: ${pkgName}`);

  // Показываем график выбранного сигнала (по имени находим id в списке)
  const pkg = (state.packages || []).find(p => p.name === pkgName);
  if (pkg) showEcgChart(pkg.id);

  showLoader();

  try {
    const data = await apiChat(serverText);
    hideLoader();
    if (data.session_id) state.sessionId = data.session_id;
    if (data.response_id) state.currentResponseId = data.response_id;

    addMessage(data.context, 'bot');
    if (data.available_packages) {
      const list = data.available_packages.map(p => `• ${p.name} (fs=${p.fs}Hz)`).join('<br>');
      addMessage('Доступные пакеты:<br>' + list, 'bot');
    }
    showGradeActions(data.can_grade);
    showRegenerateAction(data.can_regenerate);
    loadHistory();
  } catch (e) {
    hideLoader();
    addMessage('Ошибка: ' + e.message, 'bot');
  }
}

async function handleSend() {
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  addMessage(text, 'user');
  addHistory(text);
  showLoader();

  try {
    const data = await apiChat(text);
    hideLoader();

    if (data.session_id) state.sessionId = data.session_id;
    if (data.response_id) state.currentResponseId = data.response_id;

    addMessage(data.context, 'bot');

    if (data.available_packages) {
      const list = data.available_packages.map(p => `• ${p.name} (fs=${p.fs}Hz)`).join('<br>');
      addMessage('Доступные пакеты:<br>' + list, 'bot');
    }

    showGradeActions(data.can_grade);
    showRegenerateAction(data.can_regenerate);
    loadHistory();
  } catch (e) {
    hideLoader();
    addMessage('Ошибка: ' + e.message, 'bot');
  }
}

async function handleGrade(grade) {
  if (!state.currentResponseId) return;
  try {
    const data = await apiGrade(state.currentResponseId, grade);
    addMessage(`Вы оценили ответ на ${grade}/10.`, 'user');
    addHistory(`Оценка: ${grade}/10`);
    showGradeActions(data.can_grade);
    showRegenerateAction(data.can_regenerate);
  } catch (e) {
    addMessage('Ошибка при выставлении оценки: ' + e.message, 'bot');
  }
}

async function handleRegenerate() {
  if (!state.currentResponseId) return;
  showLoader();
  try {
    const data = await apiRegenerate(state.currentResponseId);
    hideLoader();
    addMessage('Перегенерация завершена. Вот новый ответ:', 'bot');
    addMessage(data.context, 'bot');
    showGradeActions(data.can_grade);
    showRegenerateAction(data.can_regenerate);
  } catch (e) {
    hideLoader();
    addMessage('Ошибка при перегенерации: ' + e.message, 'bot');
  }
}

// ---- АУТЕНТИФИКАЦИЯ (3 шага: платформа -> регистрация -> вход) ----
function getPlatformToken() {
  return localStorage.getItem('platform_token');
}

function setPlatformToken(token) {
  localStorage.setItem('platform_token', token);
}

function showAuthError(msg) {
  const el = $('#auth-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideAuthError() {
  $('#auth-error').classList.add('hidden');
}

// Показать конкретный шаг модалки: 'platform' или 'main'
function showAuthStep(step) {
  $('#auth-step-platform').classList.toggle('hidden', step !== 'platform');
  $('#auth-step-main').classList.toggle('hidden', step !== 'main');
  hideAuthError();
}

// Переключение вкладок Вход/Регистрация
function showAuthTab(tab) {
  const isLogin = tab === 'login';
  $('#tab-login').classList.toggle('active', isLogin);
  $('#tab-register').classList.toggle('active', !isLogin);
  $('#form-login').classList.toggle('hidden', !isLogin);
  $('#form-register').classList.toggle('hidden', isLogin);
  $('#register-success').classList.add('hidden');
  hideAuthError();
}

function showAuthModal() {
  // Если токен платформы уже проверен — сразу шаг входа/регистрации
  showAuthStep(getPlatformToken() ? 'main' : 'platform');
  $('#auth-modal').classList.remove('hidden');
}

function hideAuthModal() {
  $('#auth-modal').classList.add('hidden');
}

async function checkAuth() {
  const token = getToken();
  if (!token || !getPlatformToken()) {
    showAuthModal();
    return false;
  }
  try {
    const res = await authFetch(`${AUTH_BASE}/me`);
    if (!res.ok) {
      clearToken();
      showAuthModal();
      return false;
    }
    const data = await res.json();
    $('#user-token').value = token;
    $('#user-name').textContent = data.username;
    return true;
  } catch (e) {
    clearToken();
    showAuthModal();
    return false;
  }
}

// Шаг 1: проверка токена доступа к платформе
async function handlePlatformAccess() {
  const platformToken = $('#platform-token-input').value.trim();
  if (!platformToken) {
    showAuthError('Введите токен доступа к платформе');
    return;
  }
  try {
    const res = await fetch(`${AUTH_BASE}/platform-access`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform_token: platformToken })
    });
    if (res.status === 403) throw new Error('Неверный токен доступа к платформе');
    if (!res.ok) throw new Error('Ошибка сервера: ' + res.status);
    setPlatformToken(platformToken);
    showAuthStep('main');
  } catch (e) {
    showAuthError(e.message);
  }
}

// Шаг 2: регистрация (логин + токен платформы) -> показать личный токен,
// затем вернуть пользователя на экран входа
async function handleRegister() {
  const username = $('#register-username').value.trim();
  if (username.length < 3) {
    showAuthError('Логин должен быть не короче 3 символов');
    return;
  }
  try {
    const res = await fetch(`${AUTH_BASE}/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, platform_token: getPlatformToken() })
    });
    if (res.status === 403) throw new Error('Токен платформы недействителен. Обновите страницу.');
    if (!res.ok) throw new Error('Ошибка регистрации: ' + res.status);
    const data = await res.json();

    // Показываем личный токен ОДИН раз, вход — только через форму входа
    $('#register-token-value').value = data.api_token;
    $('#form-register').classList.add('hidden');
    $('#register-success').classList.remove('hidden');
    // Запомним логин, чтобы подставить в форму входа
    $('#login-username').value = data.username;
    hideAuthError();
  } catch (e) {
    showAuthError(e.message);
  }
}

// Шаг 3: вход по паре логин + личный токен
async function handleLogin() {
  const username = $('#login-username').value.trim();
  const token = $('#login-token').value.trim();
  if (!username || !token) {
    showAuthError('Введите логин и личный токен');
    return;
  }
  try {
    const res = await fetch(`${AUTH_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, token })
    });
    if (res.status === 401) throw new Error('Неверный логин или токен');
    if (!res.ok) throw new Error('Ошибка сервера: ' + res.status);
    const data = await res.json();
    setToken(token);
    hideAuthModal();
    $('#user-token').value = token;
    $('#user-name').textContent = data.username;
    addMessage(`С возвращением, ${data.username}!`, 'bot');
    await loadPackages();
    await loadHistory();
  } catch (e) {
    showAuthError(e.message);
  }
}

// ---- ИНИЦИАЛИЗАЦИЯ (единственная init) ----
function init() {
  // Шаг 1: токен доступа к платформе
  $('#platform-access-btn').addEventListener('click', handlePlatformAccess);
  $('#platform-token-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handlePlatformAccess();
  });

  // Вкладки Вход/Регистрация (шаги 2-3)
  $('#tab-login').addEventListener('click', () => showAuthTab('login'));
  $('#tab-register').addEventListener('click', () => showAuthTab('register'));

  $('#register-btn').addEventListener('click', handleRegister);
  $('#login-btn').addEventListener('click', handleLogin);
  $('#login-token').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleLogin();
  });

  // После регистрации: копирование токена и возврат на экран входа
  $('#register-token-copy').addEventListener('click', () => {
    const token = $('#register-token-value').value;
    if (token) navigator.clipboard.writeText(token);
  });
  $('#go-to-login-btn').addEventListener('click', () => {
    $('#register-success').classList.add('hidden');
    showAuthTab('login');
  });

  // Кнопка "Открыть платформу": показываем рабочую область.
  // Пакеты грузим только если авторизованы (иначе — модалка входа).
  $('#start-btn').addEventListener('click', async () => {
    $('#hero-screen').classList.add('hidden');
    $('#workspace-screen').classList.remove('hidden');
    loadLlmStatus();
    const token = getToken();
    if (token) {
      $('#user-token').value = token;
      await loadPackages();
      await loadHistory();
    } else {
      showAuthModal();
    }
  });

  // Закрыть панель графика
  $('#ecg-chart-close').addEventListener('click', hideEcgChart);

  $('#back-to-hero').addEventListener('click', () => {
    $('#workspace-screen').classList.add('hidden');
    $('#hero-screen').classList.remove('hidden');
  });

  // Чат
  $('#send-btn').addEventListener('click', handleSend);
  $('#chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSend();
  });

  // Оценка и перегенерация
  document.querySelectorAll('.grade-btn').forEach(btn => {
    btn.addEventListener('click', () => handleGrade(parseInt(btn.dataset.grade)));
  });
  $('#regenerate-btn').addEventListener('click', handleRegenerate);

  // Анализ выбранного пакета
  $('#analyze-btn').addEventListener('click', handleAnalyze);

  // Кастомный дропдаун
  $('#package-select-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleOptions();
  });

  // Закрытие списка при клике вне его
  document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.custom-select-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
      $('#package-options').classList.add('hidden');
      $('#package-select-btn').classList.remove('active');
    }
  });

  // Новый чат
  $('#new-chat-btn').addEventListener('click', () => {
    state.sessionId = null;
    state.currentResponseId = null;
    $('#chat-container').innerHTML = '<div class="message bot">Здравствуйте! Выберите пакет ЭКГ и задайте вопрос.</div>';
    showGradeActions(false);
    showRegenerateAction(false);
    hideEcgChart();
    loadHistory();
  });

  // Копирование токена
  $('#copy-token-btn').addEventListener('click', () => {
    const token = $('#user-token').value;
    if (token) {
      navigator.clipboard.writeText(token);
      addMessage('Токен скопирован в буфер обмена.', 'bot');
    }
  });

  // Выход (токен платформы сохраняется — «пропуск» уже проверен)
  $('#logout-btn').addEventListener('click', () => {
    clearToken();
    $('#user-token').value = '';
    $('#user-name').textContent = 'Пользователь';
    showAuthModal();
  });

  // Подставляем существующий токен в профиль (если есть)
  const existingToken = getToken();
  if (existingToken) {
    $('#user-token').value = existingToken;
  }

  // Проверяем токен при загрузке. Если валиден — грузим пакеты.
  checkAuth().then(isAuth => {
    if (isAuth) {
      loadPackages();
    }
  });
}

document.addEventListener('DOMContentLoaded', init);
