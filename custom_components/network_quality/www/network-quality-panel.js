const NETWORK_QUALITY_DASHBOARD_URL = "/lovelace/network-quality-overview";

class NetworkQualityPanel extends HTMLElement {
  connectedCallback() {
    this._redirectToDashboard();
  }

  set hass(_) {
    this._redirectToDashboard();
  }

  _redirectToDashboard() {
    const dashboardPath = new URL(
      NETWORK_QUALITY_DASHBOARD_URL,
      window.location.origin,
    ).pathname;

    if (window.location.pathname === dashboardPath) {
      return;
    }

    window.location.replace(NETWORK_QUALITY_DASHBOARD_URL);
  }
}

customElements.define("network-quality-panel", NetworkQualityPanel);
