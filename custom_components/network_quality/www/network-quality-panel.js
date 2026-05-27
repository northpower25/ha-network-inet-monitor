const NETWORK_QUALITY_DASHBOARD_URL = "/lovelace/network-quality-overview";

class NetworkQualityPanel extends HTMLElement {
  connectedCallback() {
    this._redirectToDashboard();
  }

  _redirectToDashboard() {
    if (window.location.pathname === NETWORK_QUALITY_DASHBOARD_URL) {
      return;
    }

    window.history.replaceState(window.history.state, "", NETWORK_QUALITY_DASHBOARD_URL);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: true } }));
  }
}

customElements.define("network-quality-panel", NetworkQualityPanel);
