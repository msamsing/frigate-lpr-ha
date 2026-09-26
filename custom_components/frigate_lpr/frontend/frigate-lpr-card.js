class FrigateLprCard extends HTMLElement {
  static getStubConfig() {
    return { title: "Nummerpladeregister" };
  }

  setConfig(config) {
    this.config = { title: config.title || "Nummerpladeregister" };
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._selectedPlate = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 8;
  }

  _entity(view) {
    if (!this._hass) return null;
    return Object.values(this._hass.states).find(
      (state) => state.attributes.frigate_lpr_view === view
    );
  }

  _plateEntities() {
    if (!this._hass) return [];
    return Object.values(this._hass.states)
      .filter((state) => state.attributes.frigate_lpr_view === "plate")
      .sort((a, b) =>
        String(b.attributes.last_seen || "").localeCompare(
          String(a.attributes.last_seen || "")
        )
      );
  }

  _items(view) {
    return this._entity(view)?.attributes?.items || [];
  }

  _summaryValue(key) {
    const state = this._entity(key);
    return state?.state || "0";
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _date(value) {
    if (!value) return "–";
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? "–"
      : new Intl.DateTimeFormat(this._hass?.locale?.language || undefined, {
          dateStyle: "short",
          timeStyle: "short",
        }).format(date);
  }

  _duration(seconds) {
    if (seconds == null) return "–";
    if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)} timer`;
    return `${(seconds / 86400).toFixed(1)} dage`;
  }

  _render() {
    if (!this.shadowRoot || !this.config) return;
    if (!this._hass) {
      this.shadowRoot.innerHTML = `<ha-card><div class="loading">Indlæser…</div></ha-card>`;
      return;
    }
    const plates = this._plateEntities();
    const selected = plates.find(
      (state) => state.attributes.plate === this._selectedPlate
    );
    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card>
        <div class="header">
          ${selected ? `<button class="back" aria-label="Tilbage">←</button>` : ""}
          <div><h1>${this._escape(selected?.attributes?.plate || this.config.title)}</h1>
          <p>${selected ? this._escape(selected.attributes.name || selected.attributes.classification) : "Frigate LPR"}</p></div>
        </div>
        ${selected ? this._renderDetail(selected) : this._renderOverview(plates)}
      </ha-card>`;
    this.shadowRoot.querySelector(".back")?.addEventListener("click", () => {
      this._selectedPlate = null;
      this._render();
    });
    this.shadowRoot.querySelectorAll("[data-plate]").forEach((row) => {
      row.addEventListener("click", () => {
        this._selectedPlate = row.dataset.plate;
        this._render();
      });
    });
  }

  _renderOverview(plates) {
    const recent = this._items("recent");
    const frequent = this._items("frequent");
    const oneTime = this._items("one_time");
    const known = this._items("known");
    const maxCount = Math.max(1, ...frequent.map((item) => Number(item.count || 0)));
    return `<div class="content">
      <div class="metrics">
        ${this._metric("Unikke i dag", this._summaryValue("unique_today"), "mdi:car-multiple")}
        ${this._metric("Observationer", this._summaryValue("observations_today"), "mdi:counter")}
        ${this._metric("Unikke i alt", this._summaryValue("total_unique"), "mdi:database")}
      </div>
      ${this._section("Seneste", recent.slice(0, 8).map((item) => this._row(item.plate, this._date(item.timestamp), item.plate)).join(""))}
      ${this._section("Hyppigste", frequent.slice(0, 6).map((item) => `
        <button class="frequency" data-plate="${this._escape(item.plate)}">
          <span><b>${this._escape(item.plate)}</b>${item.name ? `<small>${this._escape(item.name)}</small>` : ""}</span>
          <span class="bar"><i style="width:${Math.max(4, Number(item.count || 0) / maxCount * 100)}%"></i></span>
          <strong>${Number(item.count || 0)}</strong>
        </button>`).join(""))}
      <div class="columns">
        ${this._section("Nye / engangsbesøgende", oneTime.slice(0, 6).map((item) => this._row(item.plate, this._date(item.last_seen), item.plate)).join(""))}
        ${this._section("Kendte", known.slice(0, 6).map((item) => this._row(item.plate, item.name || (item.category === "own" ? "Egen" : "Kendt lokal"), item.plate)).join(""))}
      </div>
      ${plates.length ? "" : `<div class="empty">Ingen nummerplader registreret endnu.</div>`}
    </div>`;
  }

  _renderDetail(state) {
    const a = state.attributes;
    const observations = [...(a.observations || [])].reverse();
    const intervals = a.intervals_seconds || [];
    return `<div class="content detail">
      <div class="badge">${this._escape(a.classification || "Ukendt")}</div>
      <div class="detail-grid">
        ${this._fact("Første observation", this._date(a.first_seen))}
        ${this._fact("Seneste observation", this._date(a.last_seen))}
        ${this._fact("Observationer", state.state)}
        ${this._fact("Forskellige dage", a.different_days ?? 0)}
        ${this._fact("Gns. interval", a.average_interval_hours == null ? "–" : `${a.average_interval_hours} timer`)}
        ${this._fact("Navn", a.name || "–")}
      </div>
      <h2>Historik</h2>
      <div class="history">${observations.map((item, index) => `
        <div><span class="dot"></span><b>${this._date(item.timestamp)}</b>
        <small>${this._escape(item.camera || "")}${item.score == null ? "" : ` · ${Math.round(item.score * 100)}%`}</small>
        ${index < intervals.length ? `<em>${this._duration(intervals[intervals.length - 1 - index])} siden forrige</em>` : ""}</div>`).join("") || `<div class="empty">Ingen observationer.</div>`}</div>
    </div>`;
  }

  _metric(label, value, icon) {
    return `<div class="metric"><ha-icon icon="${icon}"></ha-icon><strong>${this._escape(value)}</strong><span>${label}</span></div>`;
  }

  _section(title, content) {
    return `<section><h2>${title}</h2>${content || `<div class="empty">Ingen</div>`}</section>`;
  }

  _row(plate, secondary, target) {
    return `<button class="row" data-plate="${this._escape(target)}"><b>${this._escape(plate)}</b><span>${this._escape(secondary)}</span><ha-icon icon="mdi:chevron-right"></ha-icon></button>`;
  }

  _fact(label, value) {
    return `<div class="fact"><span>${label}</span><b>${this._escape(value)}</b></div>`;
  }

  _styles() {
    return `
      :host { --lpr-accent: var(--primary-color, #03a9f4); display:block; }
      ha-card { overflow:hidden; }
      .header { display:flex; align-items:center; gap:12px; padding:22px 22px 14px; background:linear-gradient(135deg, color-mix(in srgb, var(--lpr-accent) 18%, var(--card-background-color)), var(--card-background-color)); }
      h1 { margin:0; font-size:24px; line-height:1.2; } .header p { margin:4px 0 0; color:var(--secondary-text-color); }
      .back { border:0; background:var(--secondary-background-color); color:var(--primary-text-color); border-radius:50%; width:38px; height:38px; font-size:22px; cursor:pointer; }
      .content { padding:8px 18px 20px; } .metrics { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:8px 0 20px; }
      .metric { background:var(--secondary-background-color); border-radius:14px; padding:14px; display:grid; grid-template-columns:auto 1fr; gap:2px 9px; align-items:center; }
      .metric ha-icon { grid-row:1/3; color:var(--lpr-accent); } .metric strong { font-size:22px; } .metric span { color:var(--secondary-text-color); font-size:12px; }
      h2 { font-size:15px; margin:20px 2px 8px; } section { min-width:0; }
      .row,.frequency { width:100%; border:0; border-bottom:1px solid var(--divider-color); background:transparent; color:var(--primary-text-color); min-height:48px; padding:8px 4px; display:flex; align-items:center; gap:10px; text-align:left; cursor:pointer; }
      .row b { flex:1; letter-spacing:.06em; } .row span { color:var(--secondary-text-color); font-size:12px; } .row ha-icon { color:var(--secondary-text-color); }
      .columns { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
      .frequency>span:first-child { width:108px; display:flex; flex-direction:column; } small { color:var(--secondary-text-color); font-weight:normal; }
      .bar { height:7px; flex:1; border-radius:5px; background:var(--secondary-background-color); overflow:hidden; } .bar i { display:block; height:100%; background:var(--lpr-accent); border-radius:5px; }
      .frequency strong { width:30px; text-align:right; }.empty { color:var(--secondary-text-color); padding:16px 4px; }
      .badge { display:inline-block; margin:8px 0 14px; padding:6px 11px; border-radius:14px; background:color-mix(in srgb, var(--lpr-accent) 18%, transparent); color:var(--lpr-accent); font-weight:bold; }
      .detail-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }.fact { padding:12px; border-radius:12px; background:var(--secondary-background-color); display:flex; flex-direction:column; gap:4px; }.fact span { font-size:12px; color:var(--secondary-text-color); }
      .history { margin-left:8px; border-left:2px solid var(--divider-color); }.history>div { position:relative; padding:0 0 18px 20px; display:grid; grid-template-columns:1fr auto; gap:3px 12px; }.dot { position:absolute; left:-6px; top:5px; width:10px; height:10px; background:var(--lpr-accent); border-radius:50%; }.history small { grid-column:1; }.history em { grid-column:2; grid-row:1/3; align-self:center; font-size:11px; color:var(--secondary-text-color); font-style:normal; }
      .loading { padding:24px; }
      @media (max-width:600px) { .metrics { grid-template-columns:1fr; }.columns,.detail-grid { grid-template-columns:1fr; }.metric { grid-template-columns:auto auto 1fr; }.metric ha-icon { grid-row:auto; }.metric span { text-align:right; }.history em { display:none; } }
    `;
  }
}

if (!customElements.get("frigate-lpr-card")) {
  customElements.define("frigate-lpr-card", FrigateLprCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "frigate-lpr-card",
    name: "Frigate LPR Registry",
    description: "Overblik og historik for registrerede nummerplader.",
    preview: true,
  });
}
