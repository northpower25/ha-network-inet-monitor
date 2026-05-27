const NETWORK_QUALITY_DASHBOARD_URL = "/lovelace/network-quality-overview";

class NetworkQualityPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
        }
        .wrapper {
          height: 100vh;
          box-sizing: border-box;
          padding: 12px;
          background: var(--primary-background-color);
        }
        iframe {
          border: 0;
          width: 100%;
          height: 100%;
          background: var(--card-background-color);
          border-radius: 12px;
        }
      </style>
      <div class="wrapper">
        <iframe src="${NETWORK_QUALITY_DASHBOARD_URL}" title="Network Quality Dashboard"></iframe>
      </div>
    `;
  }
}

customElements.define("network-quality-panel", NetworkQualityPanel);
