const ENTITIES = [
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

const STYLE = `
  :host {
    display: block;
    padding: 16px;
    background: var(--primary-background-color, #f5f5f5);
    min-height: 100%;
    box-sizing: border-box;
  }
  h1 {
    font-size: 1.5rem;
    font-weight: 500;
    color: var(--primary-text-color);
    margin: 0 0 16px 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .card {
    background: var(--card-background-color, white);
    border-radius: 8px;
    padding: 16px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.12));
    margin-bottom: 16px;
  }
  .card h2 {
    font-size: 1rem;
    font-weight: 500;
    margin: 0 0 12px 0;
    color: var(--primary-text-color);
  }
  .entity-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    font-size: 0.9rem;
  }
  .entity-row:last-child { border-bottom: none; }
  .entity-label { color: var(--primary-text-color); }
  .entity-value {
    font-weight: 500;
    color: var(--accent-color, #03a9f4);
  }
  .entity-value.online { color: #4CAF50; }
  .entity-value.offline { color: #f44336; }
  .entity-value.unavailable { color: var(--secondary-text-color, #888); font-style: italic; }
`;

function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

class NetworkQualityPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  set panel(_) {}

  connectedCallback() {
    this._render();
  }

  _stateDisplay(entityId) {
    if (!this._hass) return "—";
    const stateObj = this._hass.states[entityId];
    if (!stateObj) return "unavailable";
    const { state, attributes } = stateObj;
    const unit = attributes.unit_of_measurement || "";
    return unit ? `${state} ${unit}` : state;
  }

  _valueClass(entityId) {
    if (!this._hass) return "";
    const stateObj = this._hass.states[entityId];
    if (!stateObj || stateObj.state === "unavailable") return "unavailable";
    if (stateObj.state === "on") return "online";
    if (stateObj.state === "off") return "offline";
    return "";
  }

  _render() {
    const rows = ENTITIES.map(({ id, label }) => {
      const val = _escapeHtml(this._stateDisplay(id));
      const cls = _escapeHtml(this._valueClass(id));
      return `<div class="entity-row">
        <span class="entity-label">${_escapeHtml(label)}</span>
        <span class="entity-value ${cls}">${val}</span>
      </div>`;
    }).join("");

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <h1>
        <ha-icon icon="mdi:speedometer"></ha-icon>
        Network Quality
      </h1>
      <div class="card">
        <h2>KPI Overview</h2>
        ${rows}
      </div>
    `;
  }
}

customElements.define("network-quality-panel", NetworkQualityPanel);
