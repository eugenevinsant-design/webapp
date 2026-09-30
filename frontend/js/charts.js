// ============================================
// CHARTS.JS — canvas-графики для ECG Analyzer
// ============================================

const Charts = (() => {

    // --------------------------------------------------
    // ГРАФИК СИГНАЛА (линия)
    // --------------------------------------------------
    function drawSignal(canvasId, data, options = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;

        // Подгоняем canvas под размер контейнера
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const W = rect.width;
        const H = rect.height;

        // Очистка
        ctx.clearRect(0, 0, W, H);

        // Фон
        ctx.fillStyle = options.bg || '#ffffff';
        ctx.fillRect(0, 0, W, H);

        if (!data || data.length === 0) {
            ctx.fillStyle = '#9aa5b1';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Нет данных', W / 2, H / 2);
            return;
        }

        // Границы
        const pad = { top: 20, right: 16, bottom: 28, left: 46 };
        const plotW = W - pad.left - pad.right;
        const plotH = H - pad.top - pad.bottom;

        // Мин/макс
        let minV = Infinity, maxV = -Infinity;
        for (let i = 0; i < data.length; i++) {
            const v = data[i];
            if (v < minV) minV = v;
            if (v > maxV) maxV = v;
        }
        const range = (maxV - minV) || 1;
        const yPad = range * 0.1;
        minV -= yPad;
        maxV += yPad;
        const yRange = maxV - minV;

        // Сетка
        ctx.strokeStyle = '#eef1f4';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i <= 4; i++) {
            const y = pad.top + (plotH / 4) * i;
            ctx.moveTo(pad.left, y);
            ctx.lineTo(pad.left + plotW, y);
        }
        ctx.stroke();

        // Подписи Y
        ctx.fillStyle = '#8892a0';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        for (let i = 0; i <= 4; i++) {
            const val = maxV - (yRange / 4) * i;
            const y = pad.top + (plotH / 4) * i;
            ctx.fillText(val.toFixed(2), pad.left - 8, y);
        }

        // Линия сигнала (градиент)
        const step = plotW / (data.length - 1 || 1);

        const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
        gradient.addColorStop(0, options.color || '#0a8554');
        gradient.addColorStop(1, options.color || '#0a8554');

        ctx.strokeStyle = gradient;
        ctx.lineWidth = options.lineWidth || 1.6;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';

        ctx.beginPath();
        for (let i = 0; i < data.length; i++) {
            const x = pad.left + step * i;
            const y = pad.top + plotH - ((data[i] - minV) / yRange) * plotH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Заполнение под линией
        if (options.fill !== false) {
            ctx.lineTo(pad.left + plotW, pad.top + plotH);
            ctx.lineTo(pad.left, pad.top + plotH);
            ctx.closePath();
            const fillGrad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
            fillGrad.addColorStop(0, (options.color || '#0a8554') + '33');
            fillGrad.addColorStop(1, (options.color || '#0a8554') + '00');
            ctx.fillStyle = fillGrad;
            ctx.fill();
        }

        // Подписи X
        ctx.fillStyle = '#8892a0';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const totalSeconds = options.duration || (data.length / (options.fs || 500));
        for (let i = 0; i <= 5; i++) {
            const t = (totalSeconds / 5) * i;
            const x = pad.left + (plotW / 5) * i;
            ctx.fillText(t.toFixed(1) + 's', x, pad.top + plotH + 6);
        }

        // Подпись "канал"
        if (options.channelLabel) {
            ctx.fillStyle = '#0a8554';
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText(options.channelLabel, pad.left + 4, pad.top + 4);
        }
    }

    // --------------------------------------------------
    // МИНИ-СПАРКЛАЙН (для метрик)
    // --------------------------------------------------
    function drawSparkline(canvasId, values, color = '#0a8554') {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !values || values.length === 0) return;

        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const W = rect.width;
        const H = rect.height;

        ctx.clearRect(0, 0, W, H);

        const minV = Math.min(...values);
        const maxV = Math.max(...values);
        const range = (maxV - minV) || 1;
        const step = W / (values.length - 1 || 1);

        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        for (let i = 0; i < values.length; i++) {
            const x = step * i;
            const y = H - ((values[i] - minV) / range) * (H - 4) - 2;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
    }

    // --------------------------------------------------
    // КРУГОВОЙ ИНДИКАТОР (для quality score)
    // --------------------------------------------------
    function drawDonut(canvasId, percent, color = '#0a8554') {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);

        const W = rect.width;
        const H = rect.height;
        const cx = W / 2;
        const cy = H / 2;
        const r = Math.min(W, H) / 2 - 4;

        ctx.clearRect(0, 0, W, H);

        // Фон
        ctx.strokeStyle = '#eef1f4';
        ctx.lineWidth = 6;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();

        // Заполнение
        if (percent > 0) {
            ctx.strokeStyle = color;
            ctx.lineWidth = 6;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * percent / 100));
            ctx.stroke();
        }
    }

    return {
        drawSignal,
        drawSparkline,
        drawDonut,
    };
})();
