// ============================================
// SCRIPTS.JS — основная логика ECG Analyzer
// ============================================

const API_BASE = '/api';
const ECG_BASE = '/api/ecg';
const STORAGE_KEY = 'ecg_analyzer_history_v1';

// ============================================
// СОСТОЯНИЕ
// ============================================
let currentSignals = [];
let selectedSignalId = null;
let chatHistory = [];
let analysisHistory = [];
let currentTaskId = null;
let refreshInterval = null;
let lastSignalsHash = '';

// ============================================
// DOM ЭЛЕМЕНТЫ
// ============================================
const $ = (id) => document.getElementById(id);

const signalList       = $('signalList');
const statusDot        = $('statusDot');
const statusText       = $('statusText');
const countBadge       = $('countBadge');
const messages         = $('messages');
const chatMessages     = $('chatMessages');
const chatInput        = $('chatInput');
const chatSendBtn      = $('chatSendBtn');
const historyList      = $('historyList');
const reportModal      = $('reportModal');
const reportContent    = $('reportContent');
const refreshBtn       = $('refreshBtn');
const reloadBtn        = $('reloadBtn');
const exportChatBtn    = $('exportChatBtn');
const clearHistoryBtn  = $('clearHistoryBtn');
const closeReportBtn   = $('closeReportBtn');
const exportReportMd   = $('exportReportMdBtn');
const exportReportTxt  = $('exportReportTxtBtn');
const overviewSignalList = $('overviewSignalList');
const overviewReloadBtn  = $('overviewReloadBtn');

// ============================================
// TOAST — уведомления
// ============================================
const Toast = (() => {
    const container = document.getElementById('toastContainer');

    function show(text, type = 'info', duration = 3500) {
        if (!container) return;
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.textContent = text;
        container.appendChild(el);

        // Ограничим количество
        while (container.children.length > 5) {
            container.removeChild(container.firstChild);
        }

        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transition = 'opacity 0.4s';
            setTimeout(() => el.remove(), 400);
        }, duration);
    }

    return { show };
})();

// ============================================
// APP — навигация и API-инфо
// ============================================
const App = (() => {
    function goto(pageName) {
        const link = document.querySelector(`.sidebar-nav a[data-page="${pageName}"]`);
        if (link) link.click();
    }

    return { goto };
})();

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
        try { return marked.parse(text); } catch (e) {}
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
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(analysisHistory)); } catch (e) {}
}

function restoreHistory() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) analysisHistory = parsed;
    } catch (e) {}
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
        if (page === 'upload' && window.Upload) Upload.loadUploaded();
        if (page === 'overview') loadOverview();
    });
});

// ============================================
// СИГНАЛЫ
// ============================================
async function loadSignals() {
    try {
        setStatus('loading', 'Загрузка...');

        const response = await fetch(`${ECG_BASE}/`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const signals = await response.json();
        currentSignals = signals;

        const newHash = JSON.stringify(signals);
        if (newHash !== lastSignalsHash) {
            lastSignalsHash = newHash;
            renderSignals(signals);
            if (overviewSignalList) renderOverviewSignals(signals);
        }

        updateCount(signals.length);
        setStatus('online', `Готово (${signals.length})`);
        updateAnalytics();

    } catch (error) {
        console.error('Ошибка загрузки:', error);
        setStatus('offline', 'Ошибка');
        renderSignals([]);
    }
}

async function reloadSignals() {
    try {
        setStatus('loading', 'Пересканирование...');
        await fetch(`${ECG_BASE}/reload`, { method: 'POST' });
        lastSignalsHash = '';
        await loadSignals();
        Toast.show('✅ Папка пересканирована', 'success');
    } catch (e) {
        Toast.show('❌ Ошибка пересканирования', 'error');
    }
}

// ============================================
// РЕНДЕР СИГНАЛОВ
// ============================================
function renderSignals(signals) {
    if (!signalList) return;

    if (!signals || signals.length === 0) {
        signalList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📂</span>
                <p>Нет сигналов</p>
                <small>Загрузите CSV/TXT или положите .hea/.mat в data/signals</small>
            </div>
        `;
        return;
    }

    signalList.innerHTML = signals.map(signal => {
        const isCsv = signal.source_type === 'csv' || signal.source_type === 'txt';
        const icon = isCsv ? '📄' : '❤️';
        const badge = isCsv ? 'CSV' : 'WFDB';
        const badgeClass = isCsv ? 'csv' : 'wfdb';
        const name = escapeHtml(signal.name || signal.file_name || `#${signal.id}`);
        const channels = signal.channels ? signal.channels.slice(0, 3).join(', ') : '';

        return `
            <div class="signal-card ${selectedSignalId === signal.id ? 'selected' : ''}"
                 onclick="selectSignal(${signal.id})">
                <div class="signal-card-top">
                    <span class="signal-icon">${icon}</span>
                    <span class="signal-badge ${badgeClass}">${badge}</span>
                </div>
                <div class="signal-name">${name}</div>
                <div class="signal-meta">
                    <span>${signal.fs ? signal.fs + ' Гц' : '—'}</span>
                    <span>${signal.n_sig ? signal.n_sig + ' кан.' : '—'}</span>
                    <span>${signal.duration ? signal.duration.toFixed(2) + ' с' : '—'}</span>
                </div>
                ${channels ? `<div class="signal-channels">${escapeHtml(channels)}${signal.channels.length > 3 ? '…' : ''}</div>` : ''}
                <div class="signal-size">📄 ${signal.size_kb || 0} KB</div>
            </div>
        `;
    }).join('');
}

function renderOverviewSignals(signals) {
    if (!overviewSignalList) return;

    if (!signals || signals.length === 0) {
        overviewSignalList.innerHTML = '<p class="muted">Нет сигналов</p>';
        return;
    }

    const top = signals.slice(0, 5);
    overviewSignalList.innerHTML = top.map(sig => {
        const isCsv = sig.source_type === 'csv' || sig.source_type === 'txt';
        const icon = isCsv ? '📄' : '❤️';
        return `
            <div class="overview-signal-item" onclick="selectSignal(${sig.id}); App.goto('signals');">
                <span class="overview-signal-icon">${icon}</span>
                <div class="overview-signal-info">
                    <div class="overview-signal-name">${escapeHtml(sig.name)}</div>
                    <div class="overview-signal-meta">
                        ${sig.fs || '?'} Гц · ${sig.n_sig || '?'} кан. · ${sig.source_type}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function loadOverview() {
    const mSignals = $('metricSignals');
    const mAnalyses = $('metricAnalyses');
    const mAnomalies = $('metricAnomalies');
    const mQuality = $('metricQuality');

    if (mSignals) mSignals.textContent = currentSignals.length;
    if (mAnalyses) mAnalyses.textContent = analysisHistory.length;

    let anom = 0, qSum = 0, qCount = 0;
    analysisHistory.forEach(item => {
        anom += item.anomalies_count || 0;
        if (typeof item.quality_score === 'number') {
            qSum += item.quality_score * 100;
            qCount++;
        }
    });

    if (mAnomalies) mAnomalies.textContent = anom;
    if (mQuality) mQuality.textContent = qCount > 0 ? (qSum / qCount).toFixed(1) + '%' : '—';
    if (overviewSignalList) renderOverviewSignals(currentSignals);
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
    addChatMessage('system', `📊 Выбран: **${escapeHtml(signal.name)}**`);
    await loadSignalData(id);
}

function showDetails(signal) {
    let panel = $('detailsPanel');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'detailsPanel';
        panel.className = 'details-panel';
        if (signalList && signalList.parentNode) {
            signalList.parentNode.insertBefore(panel, signalList.nextSibling);
        }
    }

    const isCsv = signal.source_type === 'csv' || signal.source_type === 'txt';
    const channels = signal.channels ? signal.channels.join(', ') : '—';

    panel.innerHTML = `
        <div class="details-header">
            <h2>${escapeHtml(signal.name)}</h2>
            <button onclick="closeDetails()" class="btn-close">✕</button>
        </div>
        <div class="detail-grid">
            <div class="detail-item"><div class="label">Источник</div><div class="value">${signal.source_type.toUpperCase()}</div></div>
            <div class="detail-item"><div class="label">Частота</div><div class="value">${signal.fs || '—'} Гц</div></div>
            <div class="detail-item"><div class="label">Каналы</div><div class="value">${signal.n_sig || '—'}</div></div>
            <div class="detail-item"><div class="label">Точек</div><div class="value">${signal.sig_len || '—'}</div></div>
            <div class="detail-item"><div class="label">Длительность</div><div class="value">${signal.duration ? signal.duration.toFixed(2) + ' с' : '—'}</div></div>
            <div class="detail-item"><div class="label">Размер</div><div class="value">${signal.size_kb || 0} КБ</div></div>
        </div>
        ${isCsv && signal.channels ? `<div class="detail-channels"><b>Каналы:</b> ${escapeHtml(channels)}</div>` : ''}
        <canvas id="signalCanvas" class="signal-canvas"></canvas>
        <div class="detail-actions">
            <button class="btn btn-primary" onclick="analyzeSignal(${signal.id})">🔬 Анализировать</button>
            <button class="btn btn-secondary" onclick="loadSignalData(${signal.id})">📊 Обновить график</button>
        </div>
    `;
    panel.style.display = 'block';
}

function closeDetails() {
    const panel = $('detailsPanel');
    if (panel) panel.style.display = 'none';
    selectedSignalId = null;
    renderSignals(currentSignals);
}

// ============================================
// ЗАГРУЗКА ДАННЫХ СИГНАЛА
// ============================================
async function loadSignalData(id) {
    try {
        if (selectedSignalId !== id) return null;

        const response = await fetch(`${ECG_BASE}/${id}/data`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        if (selectedSignalId !== id) return null;

        // Рисуем график
        const signal = currentSignals.find(s => s.id === id);
        if (typeof Charts !== 'undefined') {
            setTimeout(() => {
                Charts.drawSignal('signalCanvas', data.data, {
                    fs: data.fs,
                    duration: data.total_points / data.fs,
                    channelLabel: data.channels ? data.channels[0] : null,
                });
            }, 50);
        }

        const shown = Array.isArray(data.data) ? data.data.length : 0;
        addChatMessage('assistant',
            `📊 **${escapeHtml(signal ? signal.name : '#' + id)}**\n\n` +
            `- Каналов: ${data.channels ? data.channels.length : '—'}\n` +
            `- Точек: ${data.total_points}\n` +
            `- Показано: ${shown}\n` +
            `- fs: ${data.fs} Гц`
        );

        return data;
    } catch (e) {
        console.error('loadSignalData:', e);
        Toast.show('❌ Ошибка загрузки данных', 'error');
        return null;
    }
}

// ============================================
// АНАЛИЗ
// ============================================
async function analyzeSignal(id) {
    const signal = currentSignals.find(s => s.id === id);
    if (!signal) return;

    try {
        Toast.show(`🔬 Анализ «${signal.name}» запущен`, 'info');
        addChatMessage('system', `⏳ Запуск анализа **${escapeHtml(signal.name)}**...`);

        const response = await fetch(`${ECG_BASE}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_id: id, params: {} })
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const result = await response.json();
        currentTaskId = result.task_id;

        addChatMessage('assistant', `⏳ Анализ запущен. ID: \`${result.task_id.slice(0, 8)}...\``);
        await waitForAnalysis(result.task_id, signal);

    } catch (e) {
        console.error(e);
        Toast.show('❌ Ошибка запуска анализа', 'error');
    }
}

async function waitForAnalysis(taskId, signal) {
    let attempts = 0;
    const maxAttempts = 60;
    let lastProgress = 0;

    while (attempts < maxAttempts) {
        await new Promise(r => setTimeout(r, 1000));
        attempts++;

        try {
            const r = await fetch(`${ECG_BASE}/status/${taskId}`);
            if (!r.ok) continue;
            const status = await r.json();

            if (status.status === 'completed') {
                const result = await (await fetch(`${ECG_BASE}/results/${taskId}`)).json();
                showReport(result);

                analysisHistory.push({
                    id: taskId,
                    signal_name: signal.name,
                    date: new Date().toISOString(),
                    report: result.report_markdown || '',
                    quality_score: typeof result.quality_score === 'number' ? result.quality_score : null,
                    anomalies_count: (result.anomalies || []).length,
                });
                saveHistory();

                const q = typeof result.quality_score === 'number'
                    ? Math.round(result.quality_score * 100) : '—';

                addChatMessage('assistant',
                    `✅ **Анализ завершён**\n\n` +
                    `- Качество: ${q}%\n` +
                    `- Аномалий: ${(result.anomalies || []).length}`
                );
                Toast.show('✅ Анализ завершён', 'success');
                loadHistory();
                updateAnalytics();
                loadOverview();
                return;

            } else if (status.status === 'failed') {
                addChatMessage('assistant', `❌ **Ошибка:** ${escapeHtml(status.error || '')}`);
                Toast.show('❌ Анализ упал', 'error');
                return;

            } else {
                const p = status.progress || 0;
                if (p >= lastProgress + 20) {
                    lastProgress = p;
                    addChatMessage('system', `⏳ Прогресс: ${p}%`);
                }
            }
        } catch (e) {}
    }

    addChatMessage('assistant', `⏰ Превышено время ожидания`);
    Toast.show('⏰ Превышено время ожидания', 'error');
}

// ============================================
// ОТЧЁТ
// ============================================
function showReport(result) {
    if (!reportContent) return;
    reportContent.innerHTML = result.report_markdown
        ? renderMarkdown(result.report_markdown)
        : '<em>Отчёт недоступен</em>';
    reportModal.style.display = 'flex';
    exportReportMd.disabled = false;
    exportReportTxt.disabled = false;
}

function closeReport() {
    if (reportModal) reportModal.style.display = 'none';
    if (exportReportMd) exportReportMd.disabled = true;
    if (exportReportTxt) exportReportTxt.disabled = true;
}

// ============================================
// ЧАТ
// ============================================
function addChatMessage(type, content) {
    if (!chatMessages) return;
    const welcome = chatMessages.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    const message = document.createElement('div');
    message.className = `chat-message ${type}`;
    const time = nowTime();

    const html = (type === 'user') ? escapeHtml(content) : renderMarkdown(content);
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
        const lower = text.toLowerCase();

        if (lower.includes('анализ') || lower.includes('проанализируй')) {
            if (selectedSignalId) {
                analyzeSignal(selectedSignalId);
                addChatMessage('assistant', '⏳ Анализ запущен в фоне.');
            } else {
                addChatMessage('assistant', 'ℹ️ Сначала выберите сигнал.');
            }
        } else if (lower.includes('список') || lower.includes('сигналы')) {
            if (currentSignals.length === 0) {
                addChatMessage('assistant', '📋 Список пуст.');
            } else {
                const list = currentSignals.map(s =>
                    `- **${escapeHtml(s.name)}** (${s.source_type}, ${s.fs || '?'} Гц)`
                ).join('\n');
                addChatMessage('assistant', `📋 **Сигналы (${currentSignals.length}):**\n\n${list}`);
            }
        } else if (lower.includes('помощь') || lower.includes('help')) {
            addChatMessage('assistant',
                `**📖 Помощь**\n\n` +
                `- **Покажи сигналы** — список\n` +
                `- **Проанализируй** — анализ выбранного\n` +
                `- **Помощь** — эта справка`
            );
        } else {
            addChatMessage('assistant',
                `🤔 Получил: *"${escapeHtml(text)}"*\n\nВыберите сигнал и напишите **«Проанализируй»**.`
            );
        }
    } catch (e) {
        addChatMessage('assistant', '❌ Ошибка.');
    } finally {
        chatSendBtn.disabled = false;
        chatInput.focus();
    }
}

// ============================================
// ИСТОРИЯ
// ============================================
function loadHistory() {
    if (!historyList) return;

    if (analysisHistory.length === 0) {
        historyList.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📜</span>
                <p>История пуста</p>
            </div>
        `;
        return;
    }

    historyList.innerHTML = analysisHistory.slice().reverse().map(item => {
        const date = new Date(item.date).toLocaleString('ru-RU');
        const preview = escapeHtml((item.report || '').replace(/[#*`>|]/g, ' ')
            .split('\n').filter(Boolean).slice(0, 3).join(' ').substring(0, 140));
        return `
            <div class="history-item">
                <div class="history-top">
                    <span class="history-name">❤️ ${escapeHtml(item.signal_name)}</span>
                    <span class="history-date">${date}</span>
                </div>
                <div class="history-preview">${preview}...</div>
                <button class="btn btn-secondary" onclick="showReportById('${item.id}')">📄 Открыть</button>
            </div>
        `;
    }).join('');
}

function showReportById(id) {
    const item = analysisHistory.find(h => h.id === id);
    if (item && item.report) {
        reportContent.innerHTML = renderMarkdown(item.report);
        reportModal.style.display = 'flex';
        exportReportMd.disabled = false;
        exportReportTxt.disabled = false;
    }
}

// ============================================
// АНАЛИТИКА
// ============================================
function updateAnalytics() {
    let anom = 0, qSum = 0, qCount = 0;
    analysisHistory.forEach(item => {
        anom += item.anomalies_count || 0;
        if (typeof item.quality_score === 'number') {
            qSum += item.quality_score * 100;
            qCount++;
        }
    });
    const avg = qCount > 0 ? qSum / qCount : 0;

    const el = (id) => document.getElementById(id);
    if (el('totalSignals')) el('totalSignals').textContent = currentSignals.length;
    if (el('totalAnomalies')) el('totalAnomalies').textContent = anom;
    if (el('totalAnalyses')) el('totalAnalyses').textContent = analysisHistory.length;
    if (el('avgQuality')) el('avgQuality').textContent = avg > 0 ? avg.toFixed(1) + '%' : '—';
    if (el('metricSignals')) el('metricSignals').textContent = currentSignals.length;
    if (el('metricAnalyses')) el('metricAnalyses').textContent = analysisHistory.length;
    if (el('metricAnomalies')) el('metricAnomalies').textContent = anom;
    if (el('metricQuality')) el('metricQuality').textContent = avg > 0 ? avg.toFixed(1) + '%' : '—';
}

// ============================================
// ВСПОМОГАТЕЛЬНЫЕ
// ============================================
function setStatus(state, text) {
    if (statusDot) statusDot.className = 'dot ' + state;
    if (statusText) statusText.textContent = text;
}

function updateCount(count) {
    if (countBadge) countBadge.textContent = count;
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
        Toast.show('Нет сообщений', 'error');
        return;
    }
    const text = '=== ECG Analyzer Чат ===\n\n' +
        chatHistory.map(m => `[${m.time}] ${m.type === 'user' ? 'Вы' : 'AI'}: ${m.content}`).join('\n\n');
    download(`chat_${new Date().toISOString().slice(0, 10)}.txt`, text);
    Toast.show('✅ Чат сохранён', 'success');
}

function exportReportMdFile() {
    const html = reportContent.innerHTML;
    const md = html.replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/(p|div|h[1-6]|li|tr)>/gi, '\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/\n{3,}/g, '\n\n').trim();
    download(`report_${new Date().toISOString().slice(0, 10)}.md`, md, 'text/markdown');
    Toast.show('✅ Отчёт .md скачан', 'success');
}

function exportReportTxtFile() {
    const md = reportContent.textContent || '';
    download(`report_${new Date().toISOString().slice(0, 10)}.txt`, md, 'text/plain');
    Toast.show('✅ Отчёт .txt скачан', 'success');
}

// ============================================
// СОБЫТИЯ
// ============================================
if (refreshBtn) refreshBtn.addEventListener('click', loadSignals);
if (reloadBtn) reloadBtn.addEventListener('click', reloadSignals);
if (overviewReloadBtn) overviewReloadBtn.addEventListener('click', reloadSignals);
if (exportChatBtn) exportChatBtn.addEventListener('click', exportChat);

if (chatSendBtn) chatSendBtn.addEventListener('click', sendChatMessage);
if (chatInput) chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});

if (closeReportBtn) closeReportBtn.addEventListener('click', closeReport);
if (exportReportMd) exportReportMd.addEventListener('click', exportReportMdFile);
if (exportReportTxt) exportReportTxt.addEventListener('click', exportReportTxtFile);

if (clearHistoryBtn) clearHistoryBtn.addEventListener('click', () => {
    if (confirm('Очистить историю?')) {
        analysisHistory = [];
        saveHistory();
        loadHistory();
        updateAnalytics();
        loadOverview();
        Toast.show('🗑️ История очищена', 'success');
    }
});

if (reportModal) reportModal.addEventListener('click', e => {
    if (e.target === reportModal) closeReport();
});

// ============================================
// АВТООБНОВЛЕНИЕ
// ============================================
function tickRefresh() {
    if (document.hidden) return;
    const signalsPage = document.getElementById('page-signals');
    const overviewPage = document.getElementById('page-overview');
    if ((signalsPage && signalsPage.classList.contains('active')) ||
        (overviewPage && overviewPage.classList.contains('active'))) {
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
    console.log('❤️ ECG Analyzer загружен');

    restoreHistory();

    const apiUrlEl = document.getElementById('apiUrl');
    if (apiUrlEl) apiUrlEl.textContent = window.location.origin;

    if (exportReportMd) exportReportMd.disabled = true;
    if (exportReportTxt) exportReportTxt.disabled = true;

    if (typeof Upload !== 'undefined') Upload.init();

    loadSignals();
    loadHistory();
    updateAnalytics();
    loadOverview();

    refreshInterval = setInterval(tickRefresh, 15000);
});
