const KPI_ENTITIES = [
  { id: "sensor.network_quality_internet_download", label: "Download" },
  { id: "sensor.network_quality_internet_upload", label: "Upload" },
  { id: "sensor.network_quality_ping_public", label: "Ping" },
  { id: "sensor.network_quality_packet_loss", label: "Packet Loss" },
  { id: "sensor.network_quality_jitter", label: "Jitter" },
  { id: "sensor.network_quality_availability", label: "Availability" },
  { id: "sensor.network_quality_quality_score", label: "Quality Score" },
  { id: "sensor.network_quality_quality_class", label: "Quality Class" },
  { id: "binary_sensor.network_quality_internet_online", label: "Internet Online" },
];

const METRIC_META = {
  score: { label: "Quality Score", unit: "%", better: "higher" },
  download: { label: "Download", unit: "Mbit/s", better: "higher" },
  upload: { label: "Upload", unit: "Mbit/s", better: "higher" },
  ping: { label: "Ping", unit: "ms", better: "lower" },
  jitter: { label: "Jitter", unit: "ms", better: "lower" },
  packet_loss: { label: "Packet Loss", unit: "%", better: "lower" },
  availability: { label: "Availability", unit: "%", better: "higher" },
  contract_ratio: { label: "Contract Ratio", unit: "%", better: "higher" },
};

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "analytics", label: "Analytics" },
  { key: "services", label: "Services" },
];

const DEFAULT_INTERVAL = "day";

const STYLE = `
  :host {
    display: block;
    color: var(--primary-text-color);
    background: var(--primary-background-color);
    min-height: 100%;
    box-sizing: border-box;
  }
  * { box-sizing: border-box; }
  .page {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .hero {
    background: linear-gradient(135deg, rgba(3,169,244,.14), rgba(33,150,243,.06));
    border-radius: 16px;
    padding: 20px;
    display: flex;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.12));
  }
  .hero h1 {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 1.5rem;
  }
  .hero p { margin: 6px 0 0; color: var(--secondary-text-color); }
  .hero-badges {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .badge {
    border-radius: 999px;
    padding: 8px 12px;
    background: var(--card-background-color);
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.08));
    font-size: .9rem;
  }
  .tabs {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .tab {
    border: none;
    border-radius: 999px;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    padding: 10px 16px;
    cursor: pointer;
    font: inherit;
  }
  .tab.active {
    background: var(--accent-color);
    color: var(--text-primary-color, #fff);
  }
  .card {
    background: var(--card-background-color);
    border-radius: 16px;
    padding: 16px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.12));
  }
  .section-title {
    margin: 0 0 12px;
    font-size: 1.1rem;
  }
  .controls {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    align-items: end;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .field label {
    color: var(--secondary-text-color);
    font-size: .85rem;
  }
  .field input,
  .field select,
  .action-button {
    border: 1px solid var(--divider-color);
    border-radius: 10px;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    padding: 10px 12px;
    font: inherit;
  }
  .action-button {
    cursor: pointer;
    background: var(--accent-color);
    color: var(--text-primary-color, #fff);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
  }
  .metric-card {
    border: 1px solid var(--divider-color);
    border-radius: 14px;
    padding: 14px;
    background: rgba(127,127,127,.05);
  }
  .metric-card h3,
  .chart-card h3,
  .summary-card h3,
  .service-card h3 {
    margin: 0 0 8px;
    font-size: 1rem;
  }
  .metric-main {
    font-size: 1.5rem;
    font-weight: 600;
  }
  .metric-sub,
  .muted {
    color: var(--secondary-text-color);
    font-size: .9rem;
  }
  .delta.good { color: #2e7d32; }
  .delta.bad { color: #c62828; }
  .delta.neutral { color: var(--secondary-text-color); }
  .entity-row,
  .service-row,
  .summary-row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .entity-row:last-child,
  .service-row:last-child,
  .summary-row:last-child {
    border-bottom: none;
  }
  .status-online { color: #2e7d32; }
  .status-offline { color: #c62828; }
  .status-warning { color: #ef6c00; }
  .charts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 12px;
  }
  .chart-card {
    border: 1px solid var(--divider-color);
    border-radius: 14px;
    padding: 14px;
  }
  .chart-svg {
    width: 100%;
    height: 180px;
    overflow: visible;
  }
  .chart-legend {
    display: flex;
    gap: 16px;
    font-size: .85rem;
    color: var(--secondary-text-color);
    margin-top: 8px;
  }
  .legend-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
  }
  .summary-list {
    margin: 0;
    padding-left: 18px;
  }
  .service-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
  }
  .service-card {
    border: 1px solid var(--divider-color);
    border-radius: 14px;
    padding: 14px;
  }
  .empty,
  .error {
    border-radius: 14px;
    padding: 14px;
  }
  .empty { background: rgba(127,127,127,.08); }
  .error { background: rgba(244,67,54,.14); }
`;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  const numeric = Number(value);
  return Math.abs(numeric) >= 100 ? numeric.toFixed(0) : numeric.toFixed(2).replace(/\.00$/, "");
}

function formatValue(metric, value) {
  const meta = METRIC_META[metric] || { unit: "" };
  const unit = meta.unit ? ` ${meta.unit}` : "";
  return `${formatNumber(value)}${unit}`;
}

function formatDelta(metric, current, baseline) {
  if (current === null || current === undefined || baseline === null || baseline === undefined) {
    return { text: "No baseline", className: "neutral" };
  }
  const diff = Number(current) - Number(baseline);
  const better = METRIC_META[metric]?.better;
  const positiveIsGood = better === "higher";
  const className = diff === 0
    ? "neutral"
    : (diff > 0) === positiveIsGood
      ? "good"
      : "bad";
  const prefix = diff > 0 ? "+" : "";
  return { text: `${prefix}${formatNumber(diff)}`, className };
}

function formatDateInput(date) {
  return date.toISOString().slice(0, 10);
}

class NetworkQualityPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._data = null;
    this._activeTab = "overview";
    this._loading = false;
    this._error = "";
    this._filters = this._buildDefaultFilters();
    this._lastFetchKey = "";
  }

  set hass(hass) {
    this._hass = hass;
    this._ensureData();
    this._render();
  }

  set panel(_) {}

  setConfig(config) {
    this._config = config || {};
    if (config?.entry_id) {
      this._filters.entry_id = config.entry_id;
    }
    this._ensureData(true);
    this._render();
  }

  connectedCallback() {
    this._ensureData();
    this._render();
  }

  getCardSize() {
    return 8;
  }

  _buildDefaultFilters() {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 30);
    return {
      start: formatDateInput(start),
      end: formatDateInput(end),
      interval: DEFAULT_INTERVAL,
      entry_id: undefined,
    };
  }

  async _ensureData(force = false) {
    if (!this._hass) return;
    const fetchKey = JSON.stringify(this._filters);
    if (!force && (this._loading || (this._data && this._lastFetchKey === fetchKey))) {
      return;
    }
    this._loading = true;
    this._error = "";
    this._render();
    try {
      this._data = await this._hass.callWS({
        type: "network_quality/dashboard_data",
        start: this._filters.start,
        end: this._filters.end,
        interval: this._filters.interval,
        entry_id: this._filters.entry_id,
      });
      this._lastFetchKey = fetchKey;
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  _onTabClick(event) {
    const tab = event.currentTarget?.dataset?.tab;
    if (!tab) return;
    this._activeTab = tab;
    this._render();
  }

  _onRefreshClick() {
    const start = this.shadowRoot.getElementById("range-start")?.value || this._filters.start;
    const end = this.shadowRoot.getElementById("range-end")?.value || this._filters.end;
    const interval = this.shadowRoot.getElementById("range-interval")?.value || this._filters.interval;
    this._filters = { ...this._filters, start, end, interval };
    this._ensureData(true);
  }

  _bindEvents() {
    this.shadowRoot.querySelectorAll(".tab").forEach((button) => {
      button.addEventListener("click", (event) => this._onTabClick(event));
    });
    this.shadowRoot.getElementById("refresh-analytics")?.addEventListener("click", () => this._onRefreshClick());
  }

  _stateDisplay(entityId) {
    if (!this._hass) return "—";
    const stateObj = this._hass.states[entityId];
    if (!stateObj) return "unavailable";
    const { state, attributes } = stateObj;
    const unit = attributes.unit_of_measurement || "";
    return unit ? `${state} ${unit}` : state;
  }

  _overviewMetrics() {
    const current = this._data?.current || {};
    const baseline = this._data?.baseline_current || {};
    return ["score", "download", "upload", "ping"].map((metric) => {
      const delta = formatDelta(metric, current[metric], baseline[metric]);
      return `
        <div class="metric-card">
          <h3>${escapeHtml(METRIC_META[metric].label)}</h3>
          <div class="metric-main">${escapeHtml(formatValue(metric, current[metric]))}</div>
          <div class="metric-sub">Baseline: ${escapeHtml(formatValue(metric, baseline[metric]))}</div>
          <div class="delta ${escapeHtml(delta.className)}">${escapeHtml(delta.text)}</div>
        </div>
      `;
    }).join("");
  }

  _kpiRows() {
    return KPI_ENTITIES.map(({ id, label }) => `
      <div class="entity-row">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(this._stateDisplay(id))}</strong>
      </div>
    `).join("");
  }

  _summarySection() {
    const summary = this._data?.summary || {};
    const patterns = summary.recurring_patterns || [];
    return `
      <div class="card">
        <h2 class="section-title">ML Summary</h2>
        <div class="summary-row"><span>Detected outages</span><strong>${escapeHtml(formatNumber(summary.outages || 0))}</strong></div>
        <div class="summary-row"><span>Drastic quality drops</span><strong>${escapeHtml(formatNumber(summary.drastic_quality_drops || 0))}</strong></div>
        <div class="summary-row"><span>Samples in selected range</span><strong>${escapeHtml(formatNumber(summary.samples || 0))}</strong></div>
        <div class="muted" style="margin-top: 12px;">Recurring patterns</div>
        ${patterns.length
          ? `<ul class="summary-list">${patterns.map((pattern) => `<li>${escapeHtml(pattern)}</li>`).join("")}</ul>`
          : `<div class="muted">No recurring degradations detected yet.</div>`}
      </div>
    `;
  }

  _chart(metric) {
    const meta = METRIC_META[metric];
    const buckets = this._data?.buckets || [];
    if (!buckets.length) {
      return `
        <div class="chart-card">
          <h3>${escapeHtml(meta.label)}</h3>
          <div class="empty">No historical data available for this range.</div>
        </div>
      `;
    }

    const points = buckets.map((bucket) => Number(bucket.metrics?.[metric] ?? 0));
    const baselinePoints = buckets.map((bucket) => Number(bucket.baseline?.[metric] ?? bucket.metrics?.[metric] ?? 0));
    const maxValue = Math.max(...points, ...baselinePoints, 1);
    const minValue = Math.min(...points, ...baselinePoints, 0);
    const spread = Math.max(maxValue - minValue, 1);
    const width = 320;
    const height = 180;
    const toPoint = (value, index) => {
      const x = buckets.length === 1 ? width / 2 : (index / (buckets.length - 1)) * width;
      const y = height - (((value - minValue) / spread) * (height - 16) + 8);
      return `${x},${y}`;
    };
    const series = points.map(toPoint).join(" ");
    const baselineSeries = baselinePoints.map(toPoint).join(" ");
    const markers = buckets.map((bucket, index) => {
      if (!bucket.anomaly?.drastic_drop && !bucket.anomaly?.outage) return "";
      const [x, y] = toPoint(points[index], index).split(",");
      const color = bucket.anomaly?.outage ? "#c62828" : "#ef6c00";
      return `<circle cx="${x}" cy="${y}" r="4" fill="${color}"></circle>`;
    }).join("");

    return `
      <div class="chart-card">
        <h3>${escapeHtml(meta.label)}</h3>
        <div class="muted">Current ${escapeHtml(formatValue(metric, this._data?.current?.[metric]))} · Baseline ${escapeHtml(formatValue(metric, this._data?.baseline_current?.[metric]))}</div>
        <svg viewBox="0 0 320 180" class="chart-svg" role="img" aria-label="${escapeHtml(meta.label)} history chart">
          <polyline fill="none" stroke="rgba(3,169,244,.35)" stroke-width="2" stroke-dasharray="5 4" points="${baselineSeries}"></polyline>
          <polyline fill="none" stroke="var(--accent-color)" stroke-width="3" points="${series}"></polyline>
          ${markers}
        </svg>
        <div class="chart-legend">
          <span><span class="legend-dot" style="background: var(--accent-color);"></span>Measured</span>
          <span><span class="legend-dot" style="background: rgba(3,169,244,.35);"></span>ML baseline</span>
          <span><span class="legend-dot" style="background: #ef6c00;"></span>Anomaly marker</span>
        </div>
      </div>
    `;
  }

  _servicesSection() {
    const services = this._data?.services || [];
    if (!services.length) {
      return `<div class="empty">No monitored services available for the selected period.</div>`;
    }
    return `
      <div class="service-grid">
        ${services.map((service) => `
          <div class="service-card">
            <h3>${escapeHtml(service.name)}</h3>
            <div class="metric-main ${service.current_reachable ? "status-online" : "status-offline"}">
              ${service.current_reachable ? "Reachable" : "Unavailable"}
            </div>
            <div class="service-row"><span>Availability</span><strong>${escapeHtml(formatNumber(service.availability_ratio))}%</strong></div>
            <div class="service-row"><span>Detected outages</span><strong>${escapeHtml(formatNumber(service.outages))}</strong></div>
            <div class="service-row"><span>Samples</span><strong>${escapeHtml(formatNumber(service.samples))}</strong></div>
            <div class="muted" style="margin-top: 10px;">${escapeHtml(service.current_detail || "No detail available")}</div>
          </div>
        `).join("")}
      </div>
    `;
  }

  _renderContent() {
    if (this._error) {
      return `<div class="error">${escapeHtml(this._error)}</div>`;
    }
    if (this._loading && !this._data) {
      return `<div class="empty">Loading analytics…</div>`;
    }
    if (!this._data) {
      return `<div class="empty">No dashboard data available.</div>`;
    }

    if (this._activeTab === "analytics") {
      return `
        <div class="card">
          <h2 class="section-title">Trend charts</h2>
          <div class="charts">
            ${this._chart("score")}
            ${this._chart("download")}
            ${this._chart("upload")}
            ${this._chart("ping")}
          </div>
        </div>
        ${this._summarySection()}
      `;
    }

    if (this._activeTab === "services") {
      return `
        <div class="card">
          <h2 class="section-title">Monitored services</h2>
          ${this._servicesSection()}
        </div>
        ${this._summarySection()}
      `;
    }

    return `
      <div class="grid">${this._overviewMetrics()}</div>
      <div class="grid">
        <div class="card">
          <h2 class="section-title">Live KPIs</h2>
          ${this._kpiRows()}
        </div>
        ${this._summarySection()}
      </div>
      <div class="card">
        <h2 class="section-title">Latest comparison</h2>
        <div class="charts">
          ${this._chart("score")}
          ${this._chart("download")}
        </div>
      </div>
    `;
  }

  _render() {
    const coverage = this._data?.coverage || {};
    const current = this._data?.current || {};
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="page">
        <div class="hero">
          <div>
            <h1><ha-icon icon="mdi:speedometer"></ha-icon>Network Quality</h1>
            <p>Historical analytics, ML-style baselines, outage detection and monitored service status.</p>
          </div>
          <div class="hero-badges">
            <div class="badge">Current score: <strong>${escapeHtml(formatValue("score", current.score))}</strong></div>
            <div class="badge">Range samples: <strong>${escapeHtml(formatNumber(coverage.range_samples || 0))}</strong></div>
            <div class="badge">Interval: <strong>${escapeHtml(this._filters.interval)}</strong></div>
          </div>
        </div>

        <div class="card">
          <div class="controls">
            <div class="field">
              <label for="range-start">From</label>
              <input id="range-start" type="date" value="${escapeHtml(this._filters.start)}">
            </div>
            <div class="field">
              <label for="range-end">To</label>
              <input id="range-end" type="date" value="${escapeHtml(this._filters.end)}">
            </div>
            <div class="field">
              <label for="range-interval">Period</label>
              <select id="range-interval">
                ${["hour", "day", "week", "month", "quarter"].map((value) => `<option value="${value}" ${this._filters.interval === value ? "selected" : ""}>${value}</option>`).join("")}
              </select>
            </div>
            <button class="action-button" id="refresh-analytics">${this._loading ? "Loading…" : "Apply"}</button>
          </div>
        </div>

        <div class="tabs">
          ${TABS.map((tab) => `<button class="tab ${this._activeTab === tab.key ? "active" : ""}" data-tab="${tab.key}">${escapeHtml(tab.label)}</button>`).join("")}
        </div>

        ${this._renderContent()}
      </div>
    `;
    this._bindEvents();
  }
}

customElements.define("network-quality-panel", NetworkQualityPanel);
window.customCards = window.customCards || [];
if (!window.customCards.find((card) => card.type === "network-quality-panel")) {
  window.customCards.push({
    type: "network-quality-panel",
    name: "Network Quality Panel",
    description: "Analytics dashboard for network quality and monitored services.",
  });
}
