// ============================================
// НАСТРОЙКИ
// ============================================
const API_BASE = '/api/ecg';
const STORAGE_KEY = 'ecg_analyzer_history_v1';

// ============================================
// СОСТОЯНИЕ
// ============================================
let currentSignals = [];
let selectedSignalId = null;
let chatHistory = [];          // {type, content, time}
let analysisHistory = [];      // {id, signal_name, date, report, quality_score, anomalies_count}
let currentTaskId = null;
let refreshInterval = null;
let lastSignalsHash = '';

// ============================================
// DOM ЭЛЕМЕНТЫ
// ============================================
const signalList       = document.getElementById('signalList');
const statusDot        = document.getElementById('statusDot');
const statusText       = document.getElementById('statusText');
const countBadge       = document.getElementById('countBadge');
const messages         = document.getElementById('messages');
const chatMessages     = document.getElementById('chatMessages');
const chatInput        = document.getElementById('chatInput');
const chatSendBtn      = document.getElementById('chatSendBtn');
const historyList      = document.getElementById('historyList');
const reportModal      = document.getElementById('reportModal');
const reportContent    = document.getElementById('reportContent');
const refreshBtn       = document.getElementById('refreshBtn');
const reloadBtn        = document.getElementById('reloadBtn');
const exportChatBtn    = document.getElementById('exportChatBtn');
const clearHistoryBtn  = document.getElementById('clearHistoryBtn');
const closeReportBtn   = document.getElementById('closeReportBtn');
const exportReportBtn  = document.getElementById('exportReportBtn');

// ============================================
// УТИЛИТЫ
// ============================================
function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function renderMarkdown(text) {
    if (typeof marked !== 'undefined' && marked && typeof marked.parse === 'function') {
        try { return marked.parse(text); } catch (e) { /* fallthrough */ }
    }
    return escapeHtml(text);
}

function nowTime() {
    return new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

// ============================================
// LOCAL STORAGE
// ============================================
function saveHistory() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(analysisHistory));
    } catch (e) {
        console.warn('Не удалось сохранить историю:', e);
    }
}

function restoreHistory() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) analysisHistory = parsed;
    } catch (e) {
        console.warn('Не удалось восстановить историю:', e);
    }
}

// ============================================
// НАВИГАЦИЯ
// ============================================
document.querySelectorAll('.sidebar-nav a').forEach(link => {
    link.addEventListener('click', function (e) {
        e.preventDefault();
        const page = this.dataset.page;

        document.querySelectorAll('.sidebar-nav a').forEach(a => a.classList.remove('active'));
        this.classList.add('active');

        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        const pageEl = document.getElementById(`page-${page}`);
        if (pageEl) pageEl.classList.add('active');

        if (page === 'history') loadHistory();
        if (page === 'analytics') updateAnalytics();
    });
});

// ============================================
// ОСНОВНЫЕ ФУНКЦИИ
// ============================================
async function loadSignals() {
    try {
        setStatus('loading', 'Загрузка...');

        const response = await fetch(`${API_BASE}/`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const signals = await response.json();

        // Не перерисовываем, если ничего не изменилось
        const newHash = JSON.stringify(signals);
        if (newHash !== lastSignalsHash) {
            currentSignals = signals;
            lastSignalsHash = newHash;
            renderSignals(currentSignals);
        } else {
            currentSignals = signals; // на случай, если пришли те же данные, но с другим порядком
        }

        updateCount(currentSignals.length);
        setStatus('online', `Готово (${currentSignals.length})`);
        updateAnalytics();

        console.log('📊 Загружено сигналов:', currentSignals.length);

    } catch (error) {
        console.error('❌ Ошибка загрузки:', error);
        setStatus('offline', 'Ошибка подключения');
        showMessage('error', '❌ Не удалось загрузить сигналы. Проверьте сервер.');
        renderSignals([]);
    }
}

async function reloadSignals() {
    try {
        setStatus('loading', 'Пересканирование...');
        showMessage('info', '🔍 Пересканирование папки...');

        const response = await fetch(`${API_BASE}/reload`, { method: 'POST' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        lastSignalsHash = '';   // форсируем перерисовку
        await loadSignals();
        showMessage('success', '✅ Папка пересканирована');

    } catch (error) {
        console.error('❌ Ошибка пересканирования:', error);
        showMessage('error', '❌ Ошибка пересканирования');
        setStatus('offline', 'Ошибка');
    }
}

// ============================================
// РЕНДЕРИНГ
// ============================================
function renderSignals(signals) {
    if (!signals || signals.length === 0) {
        signalList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📂</span>
                <p>Нет ЭКГ сигналов</p>
                <small>Положите <code>.hea</code> и <code>.mat</code> файлы в папку <code>data/signals</code></small>
            </div>
        `;
        return;
    }

    signalList.innerHTML = signals.map(signal => {
        const typeLabel = signal.signal_type === 'ecg' ? 'ЭКГ' : 'Вибрация';
        const typeClass = signal.signal_type === 'ecg' ? 'ecg' : 'vibration';
        const icon      = signal.signal_type === 'ecg' ? '❤️' : '📳';
        const safeName  = escapeHtml(signal.name || signal.file_name || `#${signal.id}`);

        return `
            <div class="signal-card ${selectedSignalId === signal.id ? 'selected' : ''}"
                 onclick="selectSignal(${signal.id})">
                <span class="icon">${icon}</span>
                <div class="name">${safeName}</div>
                <span class="badge-type ${typeClass}">${typeLabel}</span>
                <div class="meta">
                    <span>${signal.fs ? signal.fs + ' Hz' : '—'}</span>
                    <span>${signal.n_sig ? signal.n_sig + ' каналов' : '—'}</span>
                    <span>${signal.duration ? signal.duration.toFixed(1) + ' с' : '—'}</span>
                </div>
                <div class="size">📄 ${signal.size_kb || 0} KB</div>
            </div>
        `;
    }).join('');
}

// ============================================
// ВЫБОР СИГНАЛА
// ============================================
async function selectSignal(id) {
    selectedSignalId = id;
    const signal = currentSignals.find(s => s.id === id);
    if (!signal) return;

    showDetails(signal);
    renderSignals(currentSignals);
    addChatMessage('system', `📊 Выбран сигнал: **${signal.name}** (${signal.fs || '?'} Hz, ${signal.duration ? signal.duration.toFixed(1) : '?'} сек)`);

    // Загружаем данные — с проверкой актуальности внутри
    await loadSignalData(id);

    showMessage('info', `✅ Выбран: ${signal.name}`);
}

// ============================================
// ДЕТАЛИ СИГНАЛА
// ============================================
function showDetails(signal) {
    let panel = document.getElementById('detailsPanel');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'detailsPanel';
        panel.className = 'details-panel';
        signalList.parentNode.insertBefore(panel, signalList.nextSibling);
    }

    const safeName = escapeHtml(signal.name || signal.file_name || `#${signal.id}`);
    const safeFile = escapeHtml(signal.file_name || '—');

    panel.innerHTML = `
        <div class="details-header">
            <h2>📊 ${safeName}</h2>
            <button onclick="closeDetails()" class="btn-close">✕</button>
        </div>
        <div class="detail-grid">
            <div class="detail-item"><div class="label">Имя файла</div><div class="value">${safeFile}</div></div>
            <div class="detail-item"><div class="label">.mat файл</div><div class="value">${signal.mat_file ? '✅ Есть' : '❌ Нет'}</div></div>
            <div class="detail-item"><div class="label">Частота</div><div class="value">${signal.fs || '—'} Hz</div></div>
            <div class="detail-item"><div class="label">Каналы</div><div class="value">${signal.n_sig || '—'}</div></div>
            <div class="detail-item"><div class="label">Длительность</div><div class="value">${signal.duration ? signal.duration.toFixed(2) + ' с' : '—'}</div></div>
            <div class="detail-item"><div class="label">Размер</div><div class="value">${signal.size_kb || 0} KB</div></div>
        </div>
        <div class="detail-actions">
            <button class="btn btn-primary" onclick="analyzeSignal(${signal.id})">🔬 Анализировать</button>
            <button class="btn btn-secondary" onclick="loadSignalData(${signal.id})">📊 Данные</button>
        </div>
    `;
    panel.style.display = 'block';
}

function closeDetails() {
    const panel = document.getElementById('detailsPanel');
    if (panel) panel.style.display = 'none';
    selectedSignalId = null;
    renderSignals(currentSignals);
}

// ============================================
// ЗАГРУЗКА ДАННЫХ СИГНАЛА
// ============================================
async function loadSignalData(id) {
    try {
        // Запрос устарел, если пользователь уже выбрал другой сигнал
        if (selectedSignalId !== id) return null;

        showMessage('info', '📊 Загрузка данных...');

        const response = await fetch(`${API_BASE}/${id}/data`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();

        if (selectedSignalId !== id) return null; // ещё раз проверили после await

        console.log('📊 Данные сигнала:', data);

        const signal = currentSignals.find(s => s.id === id);
        const name = signal ? signal.name : `#${id}`;
        const shownPoints = Array.isArray(data.data) ? data.data.length : 0;

        addChatMessage('assistant',
            `📊 **Данные сигнала ${escapeHtml(name)}**\n\n` +
            `- **Частота:** ${data.fs} Hz\n` +
            `- **Точек данных:** ${data.total_points}\n` +
            `- **Выборка:** ${shownPoints} точек для отображения`
        );

        showMessage('success', `✅ Загружено ${data.total_points} точек (${data.fs} Hz)`);
        return data;

    } catch (error) {
        console.error('❌ Ошибка загрузки данных:', error);
        if (selectedSignalId === id) {
            showMessage('error', '❌ Ошибка загрузки данных');
        }
        return null;
    }
}

// ============================================
// АНАЛИЗ СИГНАЛА
// ============================================
async function analyzeSignal(id) {
    const signal = currentSignals.find(s => s.id === id);
    if (!signal) {
        showMessage('error', '❌ Сигнал не найден');
        return;
    }

    try {
        showMessage('info', `🔬 Запуск анализа ${signal.name}...`);
        addChatMessage('system', `⏳ Запуск анализа **${escapeHtml(signal.name)}**...`);

        const response = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: id, params: {} })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const result = await response.json();
        currentTaskId = result.task_id;

        showMessage('info', `🔄 Анализ запущен (ID: ${result.task_id.slice(0, 8)}...)`);
        addChatMessage('assistant',
            `⏳ Анализ запущен. Ожидайте результатов...\n\n` +
            `**ID задачи:** \`${result.task_id}\``
        );

        await waitForAnalysis(result.task_id, signal);

    } catch (error) {
        console.error('❌ Ошибка анализа:', error);
        showMessage('error', '❌ Ошибка запуска анализа');
        addChatMessage('assistant', `❌ Ошибка анализа: ${escapeHtml(error.message)}`);
    }
}

async function waitForAnalysis(taskId, signal) {
    let attempts = 0;
    const maxAttempts = 60;
    let lastShownProgress = 0;

    while (attempts < maxAttempts) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        attempts++;

        try {
            const response = await fetch(`${API_BASE}/status/${taskId}`);
            if (!response.ok) continue;

            const status = await response.json();

            if (status.status === 'completed') {
                const resultResponse = await fetch(`${API_BASE}/results/${taskId}`);
                const result = await resultResponse.json();

                showReport(result);

                analysisHistory.push({
                    id: taskId,
                    signal_name: signal.name,
                    date: new Date().toISOString(),
                    report: result.report_markdown || '',
                    quality_score: typeof result.quality_score === 'number' ? result.quality_score : null,
                    anomalies_count: (result.anomalies || []).length
                });
                saveHistory();

                const qualityPct = typeof result.quality_score === 'number'
                    ? Math.round(result.quality_score * 100)
                    : '—';

                addChatMessage('assistant',
                    `✅ **Анализ ${escapeHtml(signal.name)} завершен!**\n\n` +
                    `📊 **Качество сигнала:** ${qualityPct}%\n` +
                    `🔍 **Обнаружено аномалий:** ${(result.anomalies || []).length}\n\n` +
                    `Нажмите **"Показать отчёт"** для деталей.`
                );

                showMessage('success', `✅ Анализ ${signal.name} завершен!`);
                loadHistory();
                updateAnalytics();
                return;

            } else if (status.status === 'failed') {
                addChatMessage('assistant', `❌ **Ошибка анализа:** ${escapeHtml(status.error || 'Неизвестная ошибка')}`);
                showMessage('error', '❌ Анализ завершился с ошибкой');
                return;

            } else {
                const progress = status.progress || 0;
                if (progress >= lastShownProgress + 20) {
                    lastShownProgress = progress;
                    addChatMessage('system', `⏳ Прогресс: ${progress}%`);
                }
            }

        } catch (e) {
            console.log('⏳ Ожидание результата...');
        }
    }

    addChatMessage('assistant', `⏰ Превышено время ожидания для анализа ${escapeHtml(signal.name)}`);
    showMessage('error', '⏰ Превышено время ожидания');
}

// ============================================
// ОТЧЁТ
// ============================================
function showReport(result) {
    reportContent.innerHTML = result.report_markdown
        ? renderMarkdown(result.report_markdown)
        : '<em>Отчёт недоступен</em>';
    reportModal.style.display = 'flex';
    exportReportBtn.disabled = !result.report_markdown;
}

function closeReport() {
    reportModal.style.display = 'none';
    exportReportBtn.disabled = true;
}

// ============================================
// ЧАТ
// ============================================
function addChatMessage(type, content) {
    const welcome = chatMessages.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const message = document.createElement('div');
    message.className = `chat-message ${type}`;

    const time = nowTime();

    const html = (type === 'user')
        ? escapeHtml(content)
        : renderMarkdown(content);

    message.innerHTML = `<div>${html}</div><span class="time">${time}</span>`;

    chatMessages.appendChild(message);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    chatHistory.push({ type, content, time });
}

async function sendChatMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    addChatMessage('user', text);
    chatInput.value = '';
    chatSendBtn.disabled = true;

    try {
        const lowerText = text.toLowerCase();

        if (lowerText.includes('анализ') || lowerText.includes('проанализируй')) {
            if (selectedSignalId) {
                // Запускаем анализ в фоне, не блокируя чат
                analyzeSignal(selectedSignalId);
                addChatMessage('assistant', '⏳ Анализ запущен в фоне. Результат появится в чате.');
            } else {
                addChatMessage('assistant', 'ℹ️ Сначала выберите сигнал из списка для анализа.');
            }

        } else if (lowerText.includes('список') || lowerText.includes('сигналы')) {
            if (currentSignals.length === 0) {
                addChatMessage('assistant', '📋 Список сигналов пуст. Положите `.hea` и `.mat` файлы в `data/signals` и нажмите **Пересканировать**.');
            } else {
                const list = currentSignals.map(s =>
                    `- **${escapeHtml(s.name)}** (${s.fs || '?'} Hz, ${s.duration ? s.duration.toFixed(1) : '?'} сек)`
                ).join('\n');
                addChatMessage('assistant', `📋 **Доступные сигналы (${currentSignals.length}):**\n\n${list}`);
            }

        } else if (lowerText.includes('помощь') || lowerText.includes('help')) {
            addChatMessage('assistant',
                `**📖 Помощь по ECG Analyzer**\n\n` +
                `🔹 **Выберите сигнал** — кликните на карточку\n` +
                `🔹 **Анализ** — "Проанализируй сигнал"\n` +
                `🔹 **Данные** — "Покажи данные"\n` +
                `🔹 **Список** — "Покажи сигналы"\n` +
                `🔹 **Помощь** — "Помощь"`
            );

        } else {
            addChatMessage('assistant',
                `🤔 Я получил ваш запрос: *"${escapeHtml(text)}"*\n\n` +
                `Я могу помочь с анализом ЭКГ сигналов. Выберите сигнал и отправьте команду **"Проанализируй"**.`
            );
        }

    } catch (error) {
        console.error('❌ Ошибка чата:', error);
        addChatMessage('assistant', '❌ Извините, произошла ошибка. Попробуйте позже.');
    } finally {
        chatSendBtn.disabled = false;
        chatInput.focus();
    }
}

// ============================================
// ИСТОРИЯ
// ============================================
function loadHistory() {
    if (analysisHistory.length === 0) {
        historyList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📜</span>
                <p>История пуста</p>
                <small>Проведите анализ сигнала, чтобы он появился здесь</small>
            </div>
        `;
        return;
    }

    historyList.innerHTML = analysisHistory.slice().reverse().map(item => {
        const dateStr = new Date(item.date).toLocaleString('ru-RU');
        const preview = escapeHtml((item.report || '').replace(/[#*`>|]/g, ' ').split('\n').filter(Boolean).slice(0, 3).join(' ').substring(0, 140));
        const safeName = escapeHtml(item.signal_name || 'Без имени');

        return `
            <div class="history-item">
                <div class="top">
                    <span class="signal-name">❤️ ${safeName}</span>
                    <span class="date">${dateStr}</span>
                </div>
                <div class="preview">${preview}...</div>
                <div style="margin-top:8px;">
                    <button class="btn btn-secondary" onclick="showReportById('${item.id}')">📄 Показать отчёт</button>
                </div>
            </div>
        `;
    }).join('');
}

function showReportById(id) {
    const item = analysisHistory.find(h => h.id === id);
    if (item && item.report) {
        reportContent.innerHTML = renderMarkdown(item.report);
        reportModal.style.display = 'flex';
        exportReportBtn.disabled = false;
    } else {
        showMessage('error', '❌ Отчёт не найден');
    }
}

// ============================================
// АНАЛИТИКА
// ============================================
function updateAnalytics() {
    const totalSignals = currentSignals.length;
    const totalAnalyses = analysisHistory.length;

    let totalAnomalies = 0;
    let totalQuality = 0;
    let qualityCount = 0;

    analysisHistory.forEach(item => {
        totalAnomalies += item.anomalies_count || 0;
        if (typeof item.quality_score === 'number') {
            totalQuality += item.quality_score * 100;
            qualityCount++;
        }
    });

    const avgQuality = qualityCount > 0 ? totalQuality / qualityCount : 0;

    document.getElementById('totalSignals').textContent   = totalSignals;
    document.getElementById('totalAnomalies').textContent = totalAnomalies;
    document.getElementById('totalAnalyses').textContent  = totalAnalyses;
    document.getElementById('avgQuality').textContent     = avgQuality > 0 ? avgQuality.toFixed(1) + '%' : '—';
}

// ============================================
// ВСПОМОГАТЕЛЬНЫЕ
// ============================================
function setStatus(state, text) {
    statusDot.className = 'dot ' + state;
    statusText.textContent = text;
}

function updateCount(count) {
    countBadge.textContent = count;
}

function showMessage(type, text) {
    const msg = document.createElement('div');
    msg.className = `message ${type}`;
    msg.textContent = text;
    messages.appendChild(msg);

    setTimeout(() => {
        msg.style.opacity = '0';
        msg.style.transition = 'opacity 0.5s';
        setTimeout(() => msg.remove(), 500);
    }, 4000);
}

// ============================================
// ЭКСПОРТ
// ============================================
function download(filename, content, mime = 'text/plain') {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function exportChat() {
    if (chatHistory.length === 0) {
        showMessage('error', 'Нет сообщений для экспорта');
        return;
    }

    let text = '=== ECG Analyzer Чат ===\n\n';
    chatHistory.forEach(m => {
        const role = m.type === 'user' ? 'Пользователь' : (m.type === 'system' ? 'Система' : 'AI');
        text += `[${m.time}] ${role}: ${m.content}\n\n`;
    });

    const date = new Date().toISOString().slice(0, 10);
    download(`chat_export_${date}.txt`, text, 'text/plain');
    showMessage('success', '✅ Чат экспортирован');
}

function exportReport() {
    const content = reportContent.textContent.trim();
    if (!content) {
        showMessage('error', 'Нет отчёта для скачивания');
        return;
    }

    const md = reportContent.innerHTML
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/(p|div|h[1-6]|li|tr)>/gi, '\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/\n{3,}/g, '\n\n')
        .trim();

    const date = new Date().toISOString().slice(0, 10);
    download(`report_${date}.md`, md, 'text/markdown');
    showMessage('success', '✅ Отчёт скачан');
}

// ============================================
// СОБЫТИЯ
// ============================================
refreshBtn.addEventListener('click', loadSignals);
reloadBtn.addEventListener('click', reloadSignals);
exportChatBtn.addEventListener('click', exportChat);

chatSendBtn.addEventListener('click', sendChatMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});

closeReportBtn.addEventListener('click', closeReport);
exportReportBtn.addEventListener('click', exportReport);

clearHistoryBtn.addEventListener('click', () => {
    if (confirm('Очистить историю анализов?')) {
        analysisHistory = [];
        saveHistory();
        loadHistory();
        updateAnalytics();
        showMessage('info', '🗑️ История очищена');
    }
});

reportModal.addEventListener('click', (e) => {
    if (e.target === reportModal) closeReport();
});

// Автообновление — только когда вкладка активна и открыта страница сигналов
function tickRefresh() {
    if (document.hidden) return;
    const signalsPage = document.getElementById('page-signals');
    if (signalsPage && signalsPage.classList.contains('active')) {
        loadSignals();
    }
}

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) tickRefresh();
});

// ============================================
// ИНИЦИАЛИЗАЦИЯ
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    console.log('❤️ ECG Analyzer Pro загружен!');
    console.log(`📡 API: ${API_BASE}`);

    // Восстанавливаем историю из localStorage
    restoreHistory();

    // Динамический API-URL в настройках
    const apiUrlEl = document.getElementById('apiUrl');
    if (apiUrlEl) apiUrlEl.textContent = window.location.origin;

    // Кнопка скачивания отчёта — disabled, пока не открыт отчёт
    exportReportBtn.disabled = true;

    loadSignals();
    loadHistory();
    updateAnalytics();

    // Периодическое обновление (см. tickRefresh)
    refreshInterval = setInterval(tickRefresh, 15000);

    // Приветственное сообщение
    setTimeout(() => {
        addChatMessage('assistant',
            '👋 **Добро пожаловать в ECG Analyzer!**\n\n' +
            'Я помогу вам анализировать ЭКГ сигналы. Вот что я умею:\n' +
            '• 📋 **Покажи сигналы** — список доступных файлов\n' +
            '• 🔬 **Проанализируй [имя]** — анализ сигнала\n' +
            '• 📊 **Данные [имя]** — загрузка данных\n' +
            '• 📖 **Помощь** — эта справка\n\n' +
            'Выберите сигнал из списка или отправьте команду!'
        );
    }, 500);
});

console.log('✅ ECG Analyzer Pro готов к работе!');