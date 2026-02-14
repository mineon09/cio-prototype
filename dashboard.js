let currentTicker = null;
let allData = {};
let scoreChart = null;
let trendChart = null;
let compareMode = false;

// ===== Data Loading =====
async function loadData() {
    try {
        const response = await fetch('data/results.json');
        if (!response.ok) throw new Error('Data not found');
        allData = await response.json();

        renderTickerList();

        const tickers = Object.keys(allData);
        if (tickers.length > 0) {
            displayTicker(tickers[tickers.length - 1]);
        }
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        document.getElementById('display-ticker').textContent = '分析データがありません';
        document.getElementById('display-name').textContent = 'main.py を実行して分析を行ってください。';
    }
}

// ===== Helper: Get latest entry from data (supports both old/new format) =====
function getLatest(tickerData) {
    if (tickerData.history && tickerData.history.length > 0) {
        const latest = tickerData.history[tickerData.history.length - 1];
        return {
            ...latest,
            name: tickerData.name,
            sector: tickerData.sector,
            currency: tickerData.currency,
        };
    }
    // Old format fallback
    return tickerData;
}

// ===== Sidebar =====
function renderTickerList() {
    const list = document.getElementById('ticker-list');
    list.innerHTML = '';

    const tickers = Object.keys(allData).reverse();
    tickers.forEach(ticker => {
        const raw = allData[ticker];
        const d = getLatest(raw);
        const item = document.createElement('li');
        item.className = `ticker-item ${ticker === currentTicker ? 'active' : ''}`;
        const signalClass = `t-signal-${(d.signal || 'watch').toLowerCase()}`;
        const histCount = raw.history ? raw.history.length : 0;
        item.innerHTML = `
            <div class="t-left">
                <span class="t-code">${ticker}</span>
                <span class="t-name">${d.name || ticker}${histCount > 1 ? ` (${histCount}件)` : ''}</span>
            </div>
            <span class="t-signal ${signalClass}">${d.signal || 'WATCH'}</span>
        `;
        item.onclick = () => displayTicker(ticker);
        list.appendChild(item);
    });
}

// ===== Score Color =====
function scoreColor(score) {
    if (score >= 7) return '#22c55e';
    if (score >= 4) return '#eab308';
    return '#ef4444';
}

function totalScoreColor(score) {
    if (score >= 7) return 'var(--signal-buy)';
    if (score >= 4) return 'var(--accent-primary)';
    return 'var(--signal-sell)';
}

// ===== Single Ticker View =====
function displayTicker(ticker) {
    currentTicker = ticker;
    const raw = allData[ticker];
    const data = getLatest(raw);

    document.getElementById('display-ticker').textContent = ticker;
    document.getElementById('display-name').textContent = (data.name || ticker) + ' (' + (data.sector || '不明') + ')';
    document.getElementById('display-date').textContent = data.date || '';

    // Total Score
    const totalEl = document.getElementById('display-total-score');
    totalEl.textContent = (data.total_score || 0).toFixed(1);
    totalEl.style.color = totalScoreColor(data.total_score || 0);

    // Signal Badge
    const signalElem = document.getElementById('display-signal');
    signalElem.textContent = data.signal || 'WATCH';
    signalElem.className = 'signal-badge signal-' + (data.signal || 'watch').toLowerCase();

    // Score cards with color bars
    const scores = data.scores || {};
    const axes = ['fundamental', 'valuation', 'technical', 'qualitative'];
    axes.forEach(axis => {
        const score = scores[axis] || 0;
        const color = scoreColor(score);
        document.getElementById(`score-${axis}`).textContent = score.toFixed(1);
        document.getElementById(`score-${axis}`).style.color = color;
        const bar = document.getElementById(`bar-${axis}`);
        bar.style.width = `${score * 10}%`;
        bar.style.background = color;
    });

    // Key Metrics
    renderMetrics(data);

    // Report
    document.getElementById('display-report').innerHTML = formatReport(data.report);

    // Radar Chart
    renderChart(scores);

    // Trend Chart (if history exists)
    renderTrendChart(raw);

    // Active highlight in sidebar
    document.querySelectorAll('.ticker-item').forEach(item => {
        item.classList.toggle('active', item.querySelector('.t-code').textContent === ticker);
    });
}

// ===== Key Metrics =====
function renderMetrics(data) {
    const grid = document.getElementById('metrics-grid');
    const m = data.metrics || {};
    const t = data.technical_data || {};

    const items = [
        { label: 'ROE', value: m.roe != null ? m.roe + '%' : '-' },
        { label: 'PER', value: m.per != null ? parseFloat(m.per).toFixed(1) + 'x' : '-' },
        { label: 'PBR', value: m.pbr != null ? parseFloat(m.pbr).toFixed(2) + 'x' : '-' },
        { label: '営業利益率', value: m.op_margin != null ? m.op_margin + '%' : '-' },
        { label: 'RSI', value: t.rsi != null ? parseFloat(t.rsi).toFixed(1) : '-' },
        { label: '株価', value: t.current_price != null ? (data.currency === 'JPY' ? '¥' : '$') + parseFloat(t.current_price).toLocaleString() : '-' },
    ];

    grid.innerHTML = items.map(i => `
        <div class="metric-item">
            <span class="metric-label">${i.label}</span>
            <span class="metric-value">${i.value}</span>
        </div>
    `).join('');
}

// ===== Report Formatting =====
function formatReport(text) {
    if (!text) return '<p style="color:var(--text-muted)">レポートがありません</p>';
    return text
        .replace(/---/g, '<hr class="separator">')
        .replace(/━+\s*(.*?)\s*━+/g, '<h2>$1</h2>')
        .replace(/#{3,}\s?(.*)/g, '<h3>$1</h3>')
        .replace(/#{2}\s?(.*)/g, '<h2>$1</h2>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
}

// ===== Radar Chart =====
function renderChart(scores) {
    const ctx = document.getElementById('scoreChart').getContext('2d');

    const config = {
        type: 'radar',
        data: {
            labels: ['地力', '割安度', 'タイミング', '定性'],
            datasets: [{
                data: [scores.fundamental || 0, scores.valuation || 0, scores.technical || 0, scores.qualitative || 0],
                fill: true,
                backgroundColor: 'rgba(56, 189, 248, 0.15)',
                borderColor: '#38bdf8',
                borderWidth: 2,
                pointBackgroundColor: [
                    scoreColor(scores.fundamental || 0),
                    scoreColor(scores.valuation || 0),
                    scoreColor(scores.technical || 0),
                    scoreColor(scores.qualitative || 0),
                ],
                pointBorderColor: 'transparent',
                pointRadius: 6,
                pointHoverRadius: 8,
            }]
        },
        options: {
            responsive: true,
            scales: {
                r: {
                    angleLines: { color: 'rgba(255,255,255,0.08)' },
                    grid: { color: 'rgba(255,255,255,0.08)' },
                    pointLabels: { color: '#94a3b8', font: { size: 12, weight: 600 } },
                    ticks: { display: false },
                    suggestedMin: 0,
                    suggestedMax: 10,
                }
            },
            plugins: { legend: { display: false } },
        }
    };

    if (scoreChart) scoreChart.destroy();
    scoreChart = new Chart(ctx, config);
}

// ===== Trend Chart (Time-Series) =====
function renderTrendChart(raw) {
    const container = document.getElementById('trend-section');
    if (!raw.history || raw.history.length < 2) {
        if (container) container.style.display = 'none';
        return;
    }
    if (container) container.style.display = 'block';

    const ctx = document.getElementById('trendChart');
    if (!ctx) return;

    const history = raw.history;
    const labels = history.map(h => h.date ? h.date.split(' ')[0] : '');
    const totalScores = history.map(h => h.total_score || 0);
    const fundScores = history.map(h => (h.scores || {}).fundamental || 0);
    const valuScores = history.map(h => (h.scores || {}).valuation || 0);
    const techScores = history.map(h => (h.scores || {}).technical || 0);
    const qualScores = history.map(h => (h.scores || {}).qualitative || 0);

    const config = {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '総合スコア',
                    data: totalScores,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56,189,248,0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: '地力',
                    data: fundScores,
                    borderColor: 'rgba(34,197,94,0.6)',
                    borderWidth: 1.5,
                    borderDash: [4, 2],
                    pointRadius: 3,
                    tension: 0.3,
                },
                {
                    label: '割安度',
                    data: valuScores,
                    borderColor: 'rgba(234,179,8,0.6)',
                    borderWidth: 1.5,
                    borderDash: [4, 2],
                    pointRadius: 3,
                    tension: 0.3,
                },
                {
                    label: 'タイミング',
                    data: techScores,
                    borderColor: 'rgba(129,140,248,0.6)',
                    borderWidth: 1.5,
                    borderDash: [4, 2],
                    pointRadius: 3,
                    tension: 0.3,
                },
                {
                    label: '定性',
                    data: qualScores,
                    borderColor: 'rgba(239,68,68,0.6)',
                    borderWidth: 1.5,
                    borderDash: [4, 2],
                    pointRadius: 3,
                    tension: 0.3,
                },
            ]
        },
        options: {
            responsive: true,
            scales: {
                x: {
                    ticks: { color: '#94a3b8', font: { size: 10 } },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                },
                y: {
                    min: 0,
                    max: 10,
                    ticks: { color: '#94a3b8', stepSize: 2 },
                    grid: { color: 'rgba(255,255,255,0.08)' },
                }
            },
            plugins: {
                legend: {
                    labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12 },
                    position: 'bottom',
                },
            },
        }
    };

    if (trendChart) trendChart.destroy();
    trendChart = new Chart(ctx.getContext('2d'), config);
}

// ===== Compare Mode =====
function toggleCompare() {
    compareMode = !compareMode;
    const btn = document.getElementById('btn-compare');
    btn.classList.toggle('active', compareMode);

    document.getElementById('single-view').style.display = compareMode ? 'none' : 'block';
    document.getElementById('compare-view').style.display = compareMode ? 'block' : 'none';

    if (compareMode) renderCompareTable();
}

function renderCompareTable() {
    const table = document.getElementById('compare-table');
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');

    thead.innerHTML = `<tr>
        <th>銘柄</th><th>セクター</th>
        <th>地力</th><th>割安</th><th>技術</th><th>定性</th>
        <th>総合</th><th>判定</th><th>履歴</th><th>分析日</th>
    </tr>`;

    const tickers = Object.keys(allData);
    tbody.innerHTML = tickers.map(ticker => {
        const raw = allData[ticker];
        const d = getLatest(raw);
        const s = d.scores || {};
        const signalClass = `t-signal-${(d.signal || 'watch').toLowerCase()}`;
        const histCount = raw.history ? raw.history.length : 1;
        // 行全体をクリック可能にし、ホバー時にカーソルを表示
        return `<tr onclick="if(compareMode) toggleCompare(); displayTicker('${ticker}');" style="cursor:pointer; transition: background-color 0.2s;">
            <td><strong>${ticker}</strong><br><span style="font-size:0.7rem;color:var(--text-muted)">${d.name || ticker}</span></td>
            <td style="font-size:0.75rem">${d.sector || '-'}</td>
            <td class="score-cell" style="color:${scoreColor(s.fundamental || 0)}">${(s.fundamental || 0).toFixed(1)}</td>
            <td class="score-cell" style="color:${scoreColor(s.valuation || 0)}">${(s.valuation || 0).toFixed(1)}</td>
            <td class="score-cell" style="color:${scoreColor(s.technical || 0)}">${(s.technical || 0).toFixed(1)}</td>
            <td class="score-cell" style="color:${scoreColor(s.qualitative || 0)}">${(s.qualitative || 0).toFixed(1)}</td>
            <td class="score-cell" style="color:${totalScoreColor(d.total_score || 0)};font-size:1.1rem">${(d.total_score || 0).toFixed(1)}</td>
            <td><span class="t-signal ${signalClass}">${d.signal || 'WATCH'}</span></td>
            <td style="text-align:center;font-size:0.8rem">${histCount}件</td>
            <td style="font-size:0.7rem;color:var(--text-muted)">${d.date || ''}</td>
        </tr>`;
    }).join('');
}

// ===== Init =====
window.onload = loadData;
