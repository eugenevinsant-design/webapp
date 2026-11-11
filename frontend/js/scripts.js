const API_BASE = '/api/chat';
const ECG_BASE = '/api/ecg';
const AUTH_BASE = '/api/auth';

const state = {
  sessionId: null,
  currentResponseId: null,
  history: [],
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

// ---- API ----
async function apiChat(text) {
  const res = await authFetch(`${API_BASE}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, session_id: state.sessionId })
  });
  if (res.status === 401) { showAuthModal(); throw new Error('Требуется авторизация'); }
  if (!res.ok) throw new Error('Ошибка API: ' + res.status);
  return res.json();
}

async function apiGrade(responseId, grade) {
  const res = await authFetch(`${API_BASE}/grade?session_id=${state.sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response_id: responseId, grade })
  });
  if (res.status === 401) { showAuthModal(); throw new Error('Требуется авторизация'); }
  if (!res.ok) throw new Error('Ошибка API: ' + res.status);
  return res.json();
}

async function apiRegenerate(responseId) {
  const res = await authFetch(`${API_BASE}/regenerate?session_id=${state.sessionId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response_id: responseId })
  });
  if (res.status === 401) { showAuthModal(); throw new Error('Требуется авторизация'); }
  if (!res.ok) throw new Error('Ошибка API: ' + res.status);
  return res.json();
}

async function apiGetPackages() {
  const res = await authFetch(`${ECG_BASE}/`);
  if (res.status === 401) { showAuthModal(); throw new Error('Требуется авторизация'); }
  if (!res.ok) throw new Error('Ошибка API: ' + res.status);
  return res.json();
}

// ---- UI ----
// Загружаем marked.js для рендеринга Markdown (с fallback)
let markedLoaded = false;
const script = document.createElement('script');
script.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
script.onload = () => { markedLoaded = true; };
document.head.appendChild(script);

function addMessage(text, sender) {
  const container = $('#chat-container');
  const div = document.createElement('div');
  div.className = `message ${sender}`;
  
  // Если это ответ модели и marked загружен — рендерим Markdown
  if (sender === 'bot' && markedLoaded && typeof marked !== 'undefined') {
    div.innerHTML = marked.parse(text);
  } else {
    div.textContent = text;
  }
  
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function addHistory(text) {
  state.history.push(text);
  const list = $('#history-list');
  // Удаляем "История пуста", если она есть
  const empty = list.querySelector('.empty-history');
  if (empty) empty.remove();
  
  const div = document.createElement('div');
  div.className = 'history-item';
  div.textContent = text;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
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
    renderOptions(packages);
    $('#selected-package-text').textContent = 'Выберите пакет...';
  } catch (e) {
    console.error('Ошибка загрузки пакетов:', e);
    $('#selected-package-text').textContent = 'Ошибка загрузки';
  }
}

// ---- Обработчики ----
async function handleAnalyze() {
  const pkgName = selectedPackage;
  if (!pkgName) {
    alert('Сначала выберите пакет из списка');
    return;
  }
  // 1. Отправляем на сервер правильную команду
  const serverText = `\\choose_pkg ${pkgName} Сделай аннотацию этого сигнала`;
  
  // 2. Показываем пользователю красивое сообщение
  addMessage(`Выбран сигнал: ${pkgName}. Запуск анализа...`, 'user');
  addHistory(`Выбран пакет: ${pkgName}`);
  showLoader();

  // 3. Вызываем API напрямую, минуя поле ввода
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
    alert('Ошибка при выставлении оценки: ' + e.message);
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
    alert('Ошибка при перегенерации: ' + e.message);
  }
}

function init() {
  $('#start-btn').addEventListener('click', () => {
    $('#hero-screen').classList.add('hidden');
    $('#workspace-screen').classList.remove('hidden');
    // Загружаем пакеты при первом открытии
    loadPackages();
  });

  $('#back-to-hero').addEventListener('click', () => {
    $('#workspace-screen').classList.add('hidden');
    $('#hero-screen').classList.remove('hidden');
  });

  $('#send-btn').addEventListener('click', handleSend);
  $('#chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSend();
  });

  document.querySelectorAll('.grade-btn').forEach(btn => {
    btn.addEventListener('click', () => handleGrade(parseInt(btn.dataset.grade)));
  });

  $('#regenerate-btn').addEventListener('click', handleRegenerate);

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

  $('#new-chat-btn').addEventListener('click', () => {
    state.sessionId = null;
    state.currentResponseId = null;
    $('#chat-container').innerHTML = '<div class="message bot">Здравствуйте! Выберите пакет ЭКГ и задайте вопрос.</div>';
    $('#history-list').innerHTML = '<p class="empty-history">История пуста</p>';
    showGradeActions(false);
    showRegenerateAction(false);
  });
}

// ---- АУТЕНТИФИКАЦИЯ ----
function showAuthModal() {
  $('#auth-modal').classList.remove('hidden');
}

function hideAuthModal() {
  $('#auth-modal').classList.add('hidden');
}

async function checkAuth() {
  const token = getToken();
  if (!token) {
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
    // Заполняем поля профиля
    $('#user-token').value = token;
    $('#user-name').textContent = data.username;
    return true;
  } catch (e) {
    clearToken();
    showAuthModal();
    return false;
  }
}

async function handleRegister() {
  const username = $('#register-username').value.trim();
  if (username.length < 3) {
    $('#auth-error').textContent = 'Ник должен быть не короче 3 символов';
    $('#auth-error').classList.remove('hidden');
    return;
  }
  try {
    const res = await fetch(`${AUTH_BASE}/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username })
    });
    if (!res.ok) throw new Error('Ошибка регистрации: ' + res.status);
    const data = await res.json();
    setToken(data.api_token);
    hideAuthModal();
    alert('Регистрация успешна! Ваш токен сохранен. Скопируйте его для входа с другого устройства: ' + data.api_token);
    loadPackages();
  } catch (e) {
    $('#auth-error').textContent = e.message;
    $('#auth-error').classList.remove('hidden');
  }
}

async function handleLogin() {
  const token = $('#login-token').value.trim();
  if (!token) {
    $('#auth-error').textContent = 'Введите токен';
    $('#auth-error').classList.remove('hidden');
    return;
  }
  try {
    const res = await fetch(`${AUTH_BASE}/me`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (!res.ok) throw new Error('Неверный токен');
    setToken(token);
    hideAuthModal();
    loadPackages();
  } catch (e) {
    $('#auth-error').textContent = e.message;
    $('#auth-error').classList.remove('hidden');
  }
}

function init() {
  // Вкладки аутентификации
  $('#tab-register').addEventListener('click', () => {
    $('#tab-register').classList.add('active');
    $('#tab-login').classList.remove('active');
    $('#form-register').classList.remove('hidden');
    $('#form-login').classList.add('hidden');
  });
  $('#tab-login').addEventListener('click', () => {
    $('#tab-login').classList.add('active');
    $('#tab-register').classList.remove('active');
    $('#form-login').classList.remove('hidden');
    $('#form-register').classList.add('hidden');
  });

  $('#register-btn').addEventListener('click', handleRegister);
  $('#login-btn').addEventListener('click', handleLogin);

  // Проверка токена при загрузке
  checkAuth().then(isAuth => {
    if (isAuth) {
      // Если уже авторизован — загружаем пакеты при первом открытии платформы
      // (loadPackages вызывается по кнопке 'Открыть платформу')
    }
  });

  $('#start-btn').addEventListener('click', () => {
    $('#hero-screen').classList.add('hidden');
    $('#workspace-screen').classList.remove('hidden');
    loadPackages();
    // Подставляем токен и ник в профиль (на случай, если checkAuth не сработал)
    const token = getToken();
    if (token) {
      $('#user-token').value = token;
    }
  });

  $('#back-to-hero').addEventListener('click', () => {
    $('#workspace-screen').classList.add('hidden');
    $('#hero-screen').classList.remove('hidden');
  });

  $('#send-btn').addEventListener('click', handleSend);
  $('#chat-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleSend();
  });

  document.querySelectorAll('.grade-btn').forEach(btn => {
    btn.addEventListener('click', () => handleGrade(parseInt(btn.dataset.grade)));
  });

  $('#regenerate-btn').addEventListener('click', handleRegenerate);
  $('#analyze-btn').addEventListener('click', handleAnalyze);

  $('#package-select-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleOptions();
  });

  document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.custom-select-wrapper');
    if (wrapper && !wrapper.contains(e.target)) {
      $('#package-options').classList.add('hidden');
      $('#package-select-btn').classList.remove('active');
    }
  });

  $('#new-chat-btn').addEventListener('click', () => {
    state.sessionId = null;
    state.currentResponseId = null;
    $('#chat-container').innerHTML = '<div class="message bot">Здравствуйте! Выберите пакет ЭКГ и задайте вопрос.</div>';
    $('#history-list').innerHTML = '<p class="empty-history">История пуста</p>';
    showGradeActions(false);
    showRegenerateAction(false);
  });

  // Заполняем токен при загрузке (если он уже есть)
  const existingToken = getToken();
  if (existingToken) {
    $('#user-token').value = existingToken;
  }

  // Кнопка копирования токена
  $('#copy-token-btn').addEventListener('click', () => {
    const token = $('#user-token').value;
    if (token) {
      navigator.clipboard.writeText(token);
      alert('Токен скопирован в буфер обмена!');
    }
  });

  // Кнопка выхода
  $('#logout-btn').addEventListener('click', () => {
    clearToken();
    $('#user-token').value = '';
    $('#user-name').textContent = 'Пользователь';
    showAuthModal();
  });
}

document.addEventListener('DOMContentLoaded', init);
