// ============================================
// UPLOAD.JS — drag-and-drop и загрузка CSV/TXT
// ============================================

const Upload = (() => {

    const API_BASE = '/api';
    let dropzone, fileInput, fsInput, nameInput, uploadBtn, listEl;

    // --------------------------------------------------
    // ИНИЦИАЛИЗАЦИЯ
    // --------------------------------------------------
    function init() {
        dropzone = document.getElementById('dropzone');
        fileInput = document.getElementById('fileInput');
        fsInput = document.getElementById('uploadFs');
        nameInput = document.getElementById('uploadName');
        uploadBtn = document.getElementById('uploadBtn');
        listEl = document.getElementById('uploadedList');

        if (!dropzone) return;

        // Клик по dropzone → открывает выбор файла
        dropzone.addEventListener('click', () => fileInput.click());

        // Выбор файла
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                setSelectedFile(e.target.files[0]);
            }
        });

        // Drag and drop
        ['dragenter', 'dragover'].forEach(evt => {
            dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add('dropzone-active');
            });
        });

        ['dragleave', 'drop'].forEach(evt => {
            dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove('dropzone-active');
            });
        });

        dropzone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                setSelectedFile(files[0]);
            }
        });

        // Кнопка загрузки
        if (uploadBtn) {
            uploadBtn.addEventListener('click', () => {
                if (fileInput.files.length === 0) {
                    Toast.show('Сначала выберите файл', 'error');
                    return;
                }
                doUpload(fileInput.files[0]);
            });
        }

        // Кнопка «Обновить список загруженных»
        const refreshBtn = document.getElementById('refreshUploadsBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', loadUploaded);
        }

        loadUploaded();
    }

    // --------------------------------------------------
    // ВЫБОР ФАЙЛА
    // --------------------------------------------------
    let selectedFile = null;

    function setSelectedFile(file) {
        const allowedExt = ['.csv', '.txt', '.hea', '.mat'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();

        if (!allowedExt.includes(ext)) {
            Toast.show(`Формат "${ext}" не поддерживается. Используйте: ${allowedExt.join(', ')}`, 'error');
            return;
        }

        const maxMB = 300;
        const sizeMB = file.size / 1024 / 1024;
        if (sizeMB > maxMB) {
            Toast.show(`Файл слишком большой (${sizeMB.toFixed(1)} МБ). Максимум — ${maxMB} МБ`, 'error');
            return;
        }

        if (sizeMB > 50) {
            Toast.show(`Файл ${sizeMB.toFixed(1)} МБ — обработка может занять время`, 'info');
        }

        selectedFile = file;

        const labelEl = document.getElementById('dropzoneFilename');
        if (labelEl) {
            labelEl.textContent = `${file.name} (${sizeMB.toFixed(2)} МБ)`;
        }

        const hintEl = document.getElementById('dropzoneHint');
        if (hintEl) {
            hintEl.textContent = 'Нажмите «Загрузить» или перетащите другой файл';
        }

        if (uploadBtn) uploadBtn.disabled = false;
    }

    // --------------------------------------------------
    // ЗАГРУЗКА НА СЕРВЕР
    // --------------------------------------------------
    async function doUpload(file) {
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);
        if (fsInput && fsInput.value) formData.append('fs', fsInput.value);
        if (nameInput && nameInput.value) formData.append('name', nameInput.value);

        const progressWrap = document.getElementById('uploadProgress');
        const progressBar = document.getElementById('uploadProgressBar');
        const progressText = document.getElementById('uploadProgressText');

        if (progressWrap) progressWrap.style.display = 'block';
        if (progressBar) progressBar.style.width = '0%';
        if (progressText) progressText.textContent = 'Загрузка...';

        uploadBtn.disabled = true;

        try {
            const xhr = new XMLHttpRequest();

            const result = await new Promise((resolve, reject) => {
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const pct = Math.round(e.loaded / e.total * 100);
                        if (progressBar) progressBar.style.width = pct + '%';
                        if (progressText) progressText.textContent = `Загрузка ${pct}%`;
                    }
                });

                xhr.addEventListener('load', () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        try { resolve(JSON.parse(xhr.responseText)); }
                        catch { resolve({ status: 'ok' }); }
                    } else {
                        let msg = `HTTP ${xhr.status}`;
                        try {
                            const err = JSON.parse(xhr.responseText);
                            msg = err.detail || msg;
                        } catch {}
                        reject(new Error(msg));
                    }
                });

                xhr.addEventListener('error', () => reject(new Error('Сеть недоступна')));
                xhr.addEventListener('abort', () => reject(new Error('Отменено')));

                xhr.open('POST', `${API_BASE}/upload`);
                xhr.send(formData);
            });

            if (progressText) progressText.textContent = 'Обработка сигнала...';
            if (progressBar) progressBar.style.width = '100%';

            const sigName = result.signal?.name || file.name;
            const nSig = result.signal?.n_sig || '?';
            const fs = result.signal?.fs || '?';

            Toast.show(`✅ «${sigName}» загружен (${nSig} кан., ${fs} Гц)`, 'success');

            // Сброс формы
            fileInput.value = '';
            if (nameInput) nameInput.value = '';
            if (fsInput) fsInput.value = '';
            selectedFile = null;
            const labelEl = document.getElementById('dropzoneFilename');
            if (labelEl) labelEl.textContent = '';
            const hintEl = document.getElementById('dropzoneHint');
            if (hintEl) hintEl.textContent = 'Перетащите файл сюда или нажмите для выбора';

            // Обновление списков
            loadUploaded();
            if (window.loadSignals) window.loadSignals();

            // Скрываем прогресс через 2 сек
            setTimeout(() => {
                if (progressWrap) progressWrap.style.display = 'none';
            }, 2000);

        } catch (err) {
            console.error('Upload error:', err);
            Toast.show(`❌ Ошибка загрузки: ${err.message}`, 'error');
            if (progressText) progressText.textContent = 'Ошибка';
            if (progressWrap) progressWrap.style.display = 'none';
        } finally {
            if (uploadBtn) uploadBtn.disabled = false;
        }
    }

    // --------------------------------------------------
    // СПИСОК ЗАГРУЖЕННЫХ
    // --------------------------------------------------
    async function loadUploaded() {
        if (!listEl) return;

        try {
            const r = await fetch(`${API_BASE}/upload/list`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const items = await r.json();

            if (!items || items.length === 0) {
                listEl.innerHTML = `
                    <div class="empty-state">
                        <span class="empty-icon">📂</span>
                        <p>Пока ничего не загружено</p>
                        <small>Перетащите CSV/TXT файл в зону выше</small>
                    </div>
                `;
                return;
            }

            listEl.innerHTML = items.map(item => {
                const id = item.upload_id || '—';
                const name = item.name || item.file_name;
                const channels = item.channels ? item.channels.join(', ') : '—';
                const size = item.size_mb != null ? item.size_mb.toFixed(2) : '0.00';

                return `
                    <div class="uploaded-item">
                        <div class="uploaded-icon">📄</div>
                        <div class="uploaded-info">
                            <div class="uploaded-name">${escapeHtml(name)}</div>
                            <div class="uploaded-meta">
                                <span>${item.n_sig} кан.</span>
                                <span>${item.fs} Гц</span>
                                <span>${item.sig_len} точек</span>
                                <span>${size} МБ</span>
                            </div>
                            <div class="uploaded-channels">${escapeHtml(channels)}</div>
                        </div>
                        <button class="btn-icon" title="Удалить"
                                onclick="Upload.remove('${id}')">🗑️</button>
                    </div>
                `;
            }).join('');
        } catch (e) {
            console.error('loadUploaded error:', e);
            listEl.innerHTML = `<div class="empty-state"><p>Ошибка загрузки списка</p></div>`;
        }
    }

    // --------------------------------------------------
    // УДАЛЕНИЕ
    // --------------------------------------------------
    async function remove(uploadId) {
        if (!confirm(`Удалить загруженный файл ${uploadId}?`)) return;

        try {
            const r = await fetch(`${API_BASE}/upload/${uploadId}`, { method: 'DELETE' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            Toast.show('🗑️ Файл удалён', 'success');
            loadUploaded();
            if (window.loadSignals) window.loadSignals();
        } catch (e) {
            Toast.show(`❌ Не удалось удалить: ${e.message}`, 'error');
        }
    }

    // --------------------------------------------------
    // ЭКРАНИРОВАНИЕ
    // --------------------------------------------------
    function escapeHtml(s) {
        return String(s ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    return { init, loadUploaded, remove };
})();
