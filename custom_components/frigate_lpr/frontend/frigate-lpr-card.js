const CARD_NAME = "frigate-lpr-card";

const VIEWS = {
  overview: { label: "Overblik", icon: "⌂" },
  recent: { label: "Seneste", icon: "◷" },
  own: { label: "Egne", icon: "●" },
  known_local: { label: "Kendte", icon: "●" },
  frequent_class: { label: "Hyppige", icon: "●" },
  rare: { label: "Sjældne", icon: "●" },
  one_time: { label: "Engangs", icon: "●" },
};

const CLASS_INFO = {
  Egen: { color: "#2e9d58", background: "rgba(46,157,88,.13)" },
  "Kendt lokal": { color: "#3788d8", background: "rgba(55,136,216,.13)" },
  Hyppig: { color: "#e78a24", background: "rgba(231,138,36,.14)" },
  Sjælden: { color: "#89919a", background: "rgba(137,145,154,.14)" },
  Engangsbesøgende: { color: "#9a63d5", background: "rgba(154,99,213,.14)" },
};

const VIEW_CLASS = {
  own: "Egen",
  known_local: "Kendt lokal",
  frequent_class: "Hyppig",
  rare: "Sjælden",
  one_time: "Engangsbesøgende",
};

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatDate = (value) => {
  if (!value) return "–";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "–"
    : new Intl.DateTimeFormat(undefined, {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      }).format(date);
};

class FrigateLprCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("frigate-lpr-card-editor");
  }

  static getStubConfig() {
    return {
      title: "Nummerpladeregister",
      default_view: "overview",
      max_items: 10,
      show_summary: true,
      show_details: true,
    };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._activeView = null;
    this._selectedPlate = null;
  }

  setConfig(config) {
    this._config = { ...FrigateLprCard.getStubConfig(), ...config };
    if (!VIEWS[this._config.default_view]) this._config.default_view = "overview";
    this._activeView ??= this._config.default_view;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return this._config?.show_details ? 10 : 7;
  }

  _entity(view) {
    return Object.values(this._hass?.states || {}).find(
      (state) => state.attributes.frigate_lpr_view === view,
    );
  }

  _items(view) {
    return this._entity(view)?.attributes.items || [];
  }

  _plateDetails() {
    const selected = this._entity("selected_plate");
    if (!selected) return null;
    if (!this._selectedPlate || selected.attributes.plate === this._selectedPlate) {
      return selected.attributes;
    }
    const sensor = Object.values(this._hass.states).find(
      (state) => state.attributes.frigate_lpr_view === "plate"
        && state.attributes.plate === this._selectedPlate,
    );
    if (!sensor) return null;
    return {
      ...sensor.attributes,
      observations_count: sensor.attributes.stored_observations ?? sensor.state,
    };
  }

  _classification(item, view) {
    return item.classification || VIEW_CLASS[view] || "Sjælden";
  }

  _plateRows(items, view) {
    const max = Math.max(1, Number(this._config.max_items) || 10);
    if (!items.length) return '<div class="empty">Ingen nummerplader i denne visning endnu</div>';
    return items.slice(0, max).map((item) => {
      const classification = this._classification(item, view);
      const info = CLASS_INFO[classification] || CLASS_INFO.Sjælden;
      const meta = view === "recent"
        ? `${formatDate(item.timestamp)}${item.score == null ? "" : ` · ${Math.round(item.score * 100)} %`}`
        : `${item.count ?? 1} observation${(item.count ?? 1) === 1 ? "" : "er"}${item.days ? ` · ${item.days} dage` : ""}`;
      return `<button class="plate-row" data-plate="${escapeHtml(item.plate)}">
        <span class="dot" style="--dot:${info.color}"></span>
        <span class="plate-main"><strong>${escapeHtml(item.plate)}</strong>
          <small>${escapeHtml(item.name || classification)} · ${escapeHtml(meta)}</small></span>
        <ha-icon icon="mdi:chevron-right"></ha-icon>
      </button>`;
    }).join("");
  }

  _overview() {
    return `<div class="category-grid">${Object.entries(VIEW_CLASS).map(([view, label]) => {
      const items = this._items(view);
      const info = CLASS_INFO[label];
      return `<button class="category" data-view="${view}" style="--accent:${info.color};--tint:${info.background}">
        <span class="category-icon"><ha-icon icon="${view === "own" ? "mdi:home-garage" : view === "known_local" ? "mdi:map-marker-account" : view === "frequent_class" ? "mdi:repeat" : view === "one_time" ? "mdi:star-four-points" : "mdi:car-outline"}"></ha-icon></span>
        <span><strong>${escapeHtml(label)}</strong><small>${items.length} plader</small></span>
      </button>`;
    }).join("")}</div>
    <section><div class="section-title"><span>Seneste registreringer</span><button data-view="recent">Vis alle</button></div>
    ${this._plateRows(this._items("recent"), "recent")}</section>`;
  }

  _details() {
    if (!this._config.show_details) return "";
    const details = this._plateDetails();
    if (!details?.plate) return '<div class="details empty">Klik på en nummerplade for at se detaljer</div>';
    const info = CLASS_INFO[details.classification] || CLASS_INFO.Sjælden;
    const observations = (details.observations || []).slice(-5).reverse();
    return `<section class="details" style="--accent:${info.color};--tint:${info.background}">
      <div class="detail-head"><div><span class="badge">${escapeHtml(details.classification)}</span>
        <h2>${escapeHtml(details.plate)}</h2><p>${escapeHtml(details.name || "Ikke navngivet")}</p></div>
        <ha-icon icon="mdi:card-account-details-outline"></ha-icon></div>
      <div class="detail-grid">
        <span><small>Observationer</small><strong>${escapeHtml(details.observations_count ?? details.stored_observations ?? 0)}</strong></span>
        <span><small>Forskellige dage</small><strong>${escapeHtml(details.different_days ?? 0)}</strong></span>
        <span><small>Gns. interval</small><strong>${details.average_interval_hours == null ? "–" : `${escapeHtml(details.average_interval_hours)} t`}</strong></span>
      </div>
      <dl><div><dt>Første observation</dt><dd>${formatDate(details.first_seen)}</dd></div>
        <div><dt>Seneste observation</dt><dd>${formatDate(details.last_seen)}</dd></div></dl>
      ${observations.length ? `<div class="history"><strong>Seneste historik</strong>${observations.map((item) =>
        `<div><span>${formatDate(item.timestamp)}</span><small>${escapeHtml(item.camera || "Alle kameraer")}${item.score == null ? "" : ` · ${Math.round(item.score * 100)} %`}</small></div>`).join("")}</div>` : ""}
    </section>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config || !this._hass) return;
    const unique = this._entity("unique_today")?.state ?? "0";
    const observations = this._entity("observations_today")?.state ?? "0";
    const total = this._entity("total_unique")?.state ?? "0";
    const view = this._activeView || "overview";
    const body = view === "overview"
      ? this._overview()
      : `<section><div class="section-title"><span>${escapeHtml(VIEWS[view].label)}</span></div>${this._plateRows(this._items(view), view)}</section>`;

    this.shadowRoot.innerHTML = `<style>${FrigateLprCard.styles}</style><ha-card>
      <header><div><span class="eyebrow">FRIGATE LPR</span><h1>${escapeHtml(this._config.title)}</h1></div>
        <ha-icon icon="mdi:car-search"></ha-icon></header>
      ${this._config.show_summary ? `<div class="summary">
        <div><strong>${escapeHtml(unique)}</strong><span>Unikke i dag</span></div>
        <div><strong>${escapeHtml(observations)}</strong><span>Observationer</span></div>
        <div><strong>${escapeHtml(total)}</strong><span>I alt</span></div></div>` : ""}
      <nav>${Object.entries(VIEWS).map(([key, item]) =>
        `<button data-view="${key}" class="${key === view ? "active" : ""}">${item.icon} ${escapeHtml(item.label)}</button>`).join("")}</nav>
      <main>${body}${this._details()}</main>
    </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => {
      this._activeView = button.dataset.view;
      this._render();
    }));
    this.shadowRoot.querySelectorAll("[data-plate]").forEach((button) => button.addEventListener("click", async () => {
      this._selectedPlate = button.dataset.plate;
      const selector = this._entity("selected_plate");
      if (selector) {
        await this._hass.callService("select", "select_option", {
          entity_id: selector.entity_id,
          option: this._selectedPlate,
        });
      }
      this._render();
    }));
  }

  static styles = `
    :host{display:block;--muted:var(--secondary-text-color);font-family:var(--paper-font-body1_-_font-family,Arial,sans-serif)}
    ha-card{overflow:hidden;background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color)}
    header{display:flex;align-items:center;justify-content:space-between;padding:22px 22px 14px;background:linear-gradient(135deg,rgba(35,115,170,.15),transparent 62%)}
    header h1{font-size:24px;line-height:1.15;margin:4px 0 0} header>ha-icon{--mdc-icon-size:36px;color:var(--primary-color)}
    .eyebrow{font-size:11px;font-weight:800;letter-spacing:.16em;color:var(--primary-color)}
    .summary{display:grid;grid-template-columns:repeat(3,1fr);margin:0 18px 16px;border:1px solid var(--divider-color);border-radius:14px;overflow:hidden}
    .summary div{padding:14px 10px;text-align:center}.summary div+div{border-left:1px solid var(--divider-color)}
    .summary strong{display:block;font-size:24px}.summary span{display:block;color:var(--muted);font-size:11px;margin-top:3px}
    nav{display:flex;gap:7px;overflow-x:auto;padding:0 18px 14px;scrollbar-width:none}nav::-webkit-scrollbar{display:none}
    nav button,.section-title button{border:0;border-radius:99px;padding:8px 12px;white-space:nowrap;background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer}
    nav button.active{background:var(--primary-color);color:var(--text-primary-color,#fff)}
    main{padding:0 18px 20px}section{margin-top:5px}.section-title{display:flex;justify-content:space-between;align-items:center;font-weight:700;margin:12px 2px 8px}
    .section-title button{padding:6px 10px;color:var(--primary-color);background:transparent}
    .category-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:2px 0 18px}
    .category{display:flex;align-items:center;gap:10px;border:1px solid color-mix(in srgb,var(--accent) 30%,var(--divider-color));background:var(--tint);color:var(--primary-text-color);border-radius:14px;padding:13px;text-align:left;cursor:pointer}
    .category:last-child{grid-column:1/-1}.category-icon{display:grid;place-items:center;color:var(--accent);background:var(--ha-card-background);border-radius:10px;width:38px;height:38px}
    .category strong,.category small{display:block}.category small{color:var(--muted);margin-top:3px}
    .plate-row{width:100%;display:flex;align-items:center;gap:11px;padding:12px 4px;border:0;border-bottom:1px solid var(--divider-color);background:transparent;color:var(--primary-text-color);text-align:left;cursor:pointer}
    .plate-row:last-child{border-bottom:0}.dot{width:9px;height:9px;border-radius:50%;background:var(--dot);box-shadow:0 0 0 4px color-mix(in srgb,var(--dot) 15%,transparent)}
    .plate-main{flex:1;min-width:0}.plate-main strong{font-size:16px;letter-spacing:.04em}.plate-main small{display:block;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}
    .plate-row ha-icon{color:var(--muted)}.empty{padding:24px;text-align:center;color:var(--muted)}
    .details{margin-top:20px;padding:17px;border:1px solid color-mix(in srgb,var(--accent) 30%,var(--divider-color));border-radius:16px;background:linear-gradient(145deg,var(--tint),transparent 55%)}
    .detail-head{display:flex;justify-content:space-between}.detail-head h2{font-size:28px;margin:8px 0 2px;letter-spacing:.05em}.detail-head p{margin:0;color:var(--muted)}.detail-head>ha-icon{--mdc-icon-size:38px;color:var(--accent)}
    .badge{display:inline-block;padding:4px 8px;border-radius:99px;background:var(--tint);color:var(--accent);font-size:11px;font-weight:800}
    .detail-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:16px 0}.detail-grid span{padding:10px;background:var(--ha-card-background);border-radius:10px}.detail-grid small,.detail-grid strong{display:block}.detail-grid small{color:var(--muted);font-size:10px}.detail-grid strong{font-size:17px;margin-top:3px}
    dl{margin:0}dl div{display:flex;justify-content:space-between;gap:10px;padding:7px 0}dt{color:var(--muted)}dd{margin:0;text-align:right}.history{border-top:1px solid var(--divider-color);margin-top:10px;padding-top:12px}.history>div{display:flex;justify-content:space-between;gap:10px;padding-top:7px}.history small{color:var(--muted);text-align:right}
    @media(max-width:420px){header{padding:18px 16px 12px}main{padding:0 13px 16px}.summary,nav{margin-left:13px;margin-right:13px;padding-left:0;padding-right:0}.category-grid{grid-template-columns:1fr}.category:last-child{grid-column:auto}.detail-grid{grid-template-columns:1fr}.summary strong{font-size:20px}}
  `;
}

class FrigateLprCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
  }

  setConfig(config) {
    this._config = { ...FrigateLprCard.getStubConfig(), ...config };
    this._render();
  }

  _changed(patch) {
    this._config = { ...this._config, ...patch };
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  }

  _render() {
    if (!this._config) return;
    this.shadowRoot.innerHTML = `<style>
      .form{display:grid;gap:18px;padding:8px 0}.field{display:grid;gap:7px}.field>span{font-weight:500}
      input,select{box-sizing:border-box;width:100%;font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:12px}
      label.toggle{display:flex;align-items:center;gap:10px;cursor:pointer}input[type=checkbox]{width:18px;height:18px}
      small{color:var(--secondary-text-color)}
    </style><div class="form">
      <label class="field"><span>Titel</span><input id="title" value="${escapeHtml(this._config.title)}"></label>
      <label class="field"><span>Startvisning</span><select id="default_view">${Object.entries(VIEWS).map(([key,item]) => `<option value="${key}" ${this._config.default_view === key ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}</select></label>
      <label class="field"><span>Maksimalt antal plader</span><input id="max_items" type="number" min="1" max="50" value="${Number(this._config.max_items) || 10}"><small>Gælder for hver liste i kortet.</small></label>
      <label class="toggle"><input id="show_summary" type="checkbox" ${this._config.show_summary ? "checked" : ""}><span>Vis nøgletal</span></label>
      <label class="toggle"><input id="show_details" type="checkbox" ${this._config.show_details ? "checked" : ""}><span>Vis detaljer og historik ved klik</span></label>
    </div>`;
    this.shadowRoot.getElementById("title").addEventListener("input", (event) => this._changed({ title: event.target.value }));
    this.shadowRoot.getElementById("default_view").addEventListener("change", (event) => this._changed({ default_view: event.target.value }));
    this.shadowRoot.getElementById("max_items").addEventListener("change", (event) => this._changed({ max_items: Math.max(1, Math.min(50, Number(event.target.value) || 10)) }));
    this.shadowRoot.getElementById("show_summary").addEventListener("change", (event) => this._changed({ show_summary: event.target.checked }));
    this.shadowRoot.getElementById("show_details").addEventListener("change", (event) => this._changed({ show_details: event.target.checked }));
  }
}

if (!customElements.get(CARD_NAME)) customElements.define(CARD_NAME, FrigateLprCard);
if (!customElements.get("frigate-lpr-card-editor")) customElements.define("frigate-lpr-card-editor", FrigateLprCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_NAME)) {
  window.customCards.push({
    type: CARD_NAME,
    name: "Frigate LPR Registry",
    description: "Grafisk overblik over observerede nummerplader og deres klassifikation.",
    preview: true,
    configurable: true,
    documentationURL: "https://github.com/msamsing/frigate-lpr-ha#dashboard",
  });
}
