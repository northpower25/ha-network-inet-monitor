const NETWORK_QUALITY_DASHBOARD_URL = "/lovelace/network-quality-overview";

class NetworkQualityPanel extends HTMLElement {
  connectedCallback() {
    this._navigateToDashboard();
  }

  set hass(_) {
    this._navigateToDashboard();
  }

  _navigateToDashboard() {
    const dashboardPath = new URL(
      NETWORK_QUALITY_DASHBOARD_URL,
      window.location.origin,
    ).pathname;

    if (window.location.pathname === dashboardPath) {
      return;
    }

    window.history.replaceState(window.history.state, "", dashboardPath);
    window.dispatchEvent(
      new CustomEvent("location-changed", {
        detail: { replace: true },
      }),
    );
  }
}

customElements.define("network-quality-panel", NetworkQualityPanel);
