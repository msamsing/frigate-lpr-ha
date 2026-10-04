const CARD_NAME = "frigate-lpr-card";

const CATEGORY = {
  own: { label: "Egen", color: "#3b82f6", icon: "mdi:home-garage" },
  known: { label: "Kendt", color: "#2e9d58", icon: "mdi:account-check" },
  taxi: { label: "Hyrevogn", color: "#7c3aed", icon: "mdi:taxi" },
  unknown: { label: "Ukendt", color: "#b7791f", icon: "mdi:help-circle-outline" },
  unwanted: { label: "Uønsket", color: "#d64545", icon: "mdi:alert-circle-outline" },
};

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

const formatDate = (value, timeOnly = false) => {
  if (!value) return "–";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "–";
  return new Intl.DateTimeFormat(undefined, timeOnly
    ? { hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
};

const clock = (minute) => minute == null ? "–" : `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
const categoryKey = (item) => {
  const explicit = item?.user_category || item?.category;
  if (["own", "known", "taxi", "unknown", "unwanted"].includes(explicit)) return explicit;
  if (item?.classification === "Hyrevogn") return "taxi";
  return "unknown";
};
const plateDisplay = (plate) => {
  const clean = String(plate || "");
  return clean.length > 2 ? `${clean.slice(0, 2)} ${clean.slice(2)}` : clean;
};

class FrigateLprCard extends HTMLElement {
  static getConfigElement() { return document.createElement("frigate-lpr-card-editor"); }
  static getStubConfig() { return { title: "Køretøjsregister", max_items: 50, show_summary: true, show_details: true }; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selectedPlate = null;
    this._mobileTab = "recent";
    this._search = "";
    this._filter = "all";
    this._sort = "last_seen";
    this._message = "";
    this._desktopView = "registry";
  }

  setConfig(config) {
    this._config = { ...FrigateLprCard.getStubConfig(), ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const signature = Object.values(hass.states || {})
      .filter((state) => state.attributes.frigate_lpr_view)
      .map((state) => `${state.entity_id}:${state.state}:${state.last_updated || state.last_changed || ""}`)
      .sort()
      .join("|");
    if (this.shadowRoot?.querySelector("dialog[open]")) {
      this._lprSignature = signature;
      return;
    }
    if (this.shadowRoot?.activeElement?.matches("input, textarea, select")) return;
    if (signature === this._lprSignature) return;
    this._lprSignature = signature;
    this._render();
  }

  getCardSize() { return 12; }

  _entity(view) {
    return Object.values(this._hass?.states || {}).find((state) => state.attributes.frigate_lpr_view === view);
  }

  _vehicles() {
    return Object.values(this._hass?.states || {})
      .filter((state) => state.attributes.frigate_lpr_view === "plate")
      .map((state) => ({ ...state.attributes, observations_count: state.attributes.stored_observations ?? Number(state.state) ?? 0 }));
  }

  _selected() {
    const vehicles = this._vehicles();
    return vehicles.find((item) => item.plate === this._selectedPlate)
      || vehicles.find((item) => item.plate === this._entity("selected_plate")?.attributes.plate)
      || vehicles[0] || null;
  }

  _filteredVehicles() {
    const query = this._search.trim().toLocaleLowerCase();
    const items = this._vehicles().filter((item) => {
      const vehicle = item.vehicle || {};
      const haystack = [item.plate, item.name, vehicle.make, vehicle.model, vehicle.color].join(" ").toLocaleLowerCase();
      const visibilityMatches = this._filter === "ignored" ? item.ignored : !item.ignored;
      const categoryMatches = ["all", "ignored"].includes(this._filter) || categoryKey(item) === this._filter;
      return (!query || haystack.includes(query)) && visibilityMatches && categoryMatches;
    });
    return items.sort((a, b) => {
      if (this._sort === "plate") return a.plate.localeCompare(b.plate);
      if (this._sort === "count") return (b.observations_count || 0) - (a.observations_count || 0);
      return String(b.last_seen || "").localeCompare(String(a.last_seen || ""));
    });
  }

  _badge(item) {
    const key = categoryKey(item);
    const category = CATEGORY[key];
    return `<span class="badge" style="--category:${category.color}"><ha-icon icon="${category.icon}"></ha-icon>${category.label}</span>`;
  }

  _vehicleList() {
    const vehicles = this._filteredVehicles().slice(0, Math.max(1, Number(this._config.max_items) || 50));
    return `<section class="vehicle-panel panel" aria-label="Køretøjer">
      <div class="panel-title"><div><small>KØRETØJER</small><h2>${this._vehicles().length} registrerede</h2></div><button class="icon-button new-case" title="Ny køretøjssag"><ha-icon icon="mdi:plus"></ha-icon></button></div>
      <label class="search"><ha-icon icon="mdi:magnify"></ha-icon><input id="vehicle-search" type="search" placeholder="Søg nummerplade, mærke eller model" value="${escapeHtml(this._search)}"></label>
      <div class="list-controls">
        <select id="category-filter" aria-label="Filtrer kategori"><option value="all">Alle kategorier</option>${Object.entries(CATEGORY).map(([key, value]) => `<option value="${key}" ${this._filter === key ? "selected" : ""}>${value.label}</option>`).join("")}<option value="ignored" ${this._filter === "ignored" ? "selected" : ""}>Ignorerede sager</option></select>
        <select id="vehicle-sort" aria-label="Sortér køretøjer"><option value="last_seen" ${this._sort === "last_seen" ? "selected" : ""}>Senest set</option><option value="count" ${this._sort === "count" ? "selected" : ""}>Flest passager</option><option value="plate" ${this._sort === "plate" ? "selected" : ""}>Nummerplade</option></select>
      </div>
      <div class="vehicle-list">${vehicles.length ? vehicles.map((item) => {
        const vehicle = item.vehicle || {};
        const selected = this._selected()?.plate === item.plate;
        return `<button class="vehicle-row ${selected ? "selected" : ""}" data-plate="${escapeHtml(item.plate)}">
          <span class="mini-plate">${escapeHtml(plateDisplay(item.plate))}</span>
          <span class="vehicle-copy"><strong>${escapeHtml([vehicle.make, vehicle.model].filter(Boolean).join(" ") || item.name || "Ukendt køretøj")}</strong><small>${escapeHtml(vehicle.color || "Farve ukendt")} · ${formatDate(item.last_seen)}</small></span>
          <span class="row-meta">${item.ignored ? `<span class="ignored-label" title="${item.auto_ignored_reason === "motorapi_unknown_vehicle" ? "MotorAPI fandt ikke et entydigt køretøj" : "Manuelt ignoreret"}">${item.auto_ignored_reason === "motorapi_unknown_vehicle" ? "Ignoreret · mulig fejlaflæsning" : "Ignoreret"}</span>` : this._badge(item)}<small>${item.observations_count || 0} passager</small></span>
        </button>`;
      }).join("") : '<div class="empty">Ingen køretøjer matcher søgningen</div>'}</div>
    </section>`;
  }

  _statCard(label, value) { return `<div class="stat"><small>${label}</small><strong>${escapeHtml(value)}</strong></div>`; }

  _timeChart(stats) {
    const counts = stats?.hour_counts || Array(24).fill(0);
    const max = Math.max(1, ...counts);
    const bars = counts.map((count, hour) => `<rect x="${hour * 10 + 2}" y="${54 - count / max * 46}" width="7" height="${Math.max(count ? 2 : 0, count / max * 46)}" rx="2" class="chart-bar"><title>${String(hour).padStart(2, "0")}:00 · ${count} passager</title></rect>`).join("");
    return `<div class="chart"><div class="chart-title"><strong>Tidspunkt for passager</strong><span>Hele historikken</span></div><svg viewBox="0 0 242 76" role="img" aria-label="Fordeling af passager over døgnets 24 timer">${bars}<line x1="2" y1="55" x2="239" y2="55" class="axis"/><text x="2" y="70">00</text><text x="118" y="70">12</text><text x="226" y="70">23</text></svg></div>`;
  }

  _dailyChart(stats) {
    const days = stats?.daily_counts || [];
    const max = Math.max(1, ...days.map((day) => day.count));
    return `<div class="chart compact"><div class="chart-title"><strong>Passager seneste uge</strong><span>${days.reduce((sum, day) => sum + day.count, 0)} i alt</span></div><div class="day-bars">${days.map((day) => `<div><span style="height:${Math.max(day.count ? 4 : 1, day.count / max * 52)}px" title="${escapeHtml(day.date)}: ${day.count}"></span><small>${new Intl.DateTimeFormat(undefined, { weekday: "narrow" }).format(new Date(`${day.date}T12:00:00`))}</small></div>`).join("")}</div></div>`;
  }

  _detail() {
    const item = this._selected();
    if (!item) return '<section class="detail-panel panel empty">Vælg eller opret et køretøj for at se detaljer</section>';
    const vehicle = item.vehicle || {};
    const stats = item.time_stats || {};
    const speed = item.speed_stats || {};
    const pattern = item.pattern || { primary: "For lidt data til et sikkert mønster", secondary: [], confidence: "Lav", evidence: [] };
    const category = categoryKey(item);
    const masterData = Object.entries(vehicle).sort(([a], [b]) => a.localeCompare(b));
    return `<section class="detail-panel panel" aria-label="Køretøjsdetaljer">
      <div class="detail-top"><div><small>VALGT KØRETØJ</small><div class="license-plate"><span>DK</span>${escapeHtml(plateDisplay(item.plate))}</div></div>${this._badge(item)}</div>
      <div class="identity"><div><h2>${escapeHtml([vehicle.make, vehicle.model].filter(Boolean).join(" ") || "Ukendt køretøj")}</h2><p>${escapeHtml([vehicle.variant, vehicle.model_year, vehicle.color].filter(Boolean).join(" · ") || item.name || "Ingen stamdata")}</p></div><button class="icon-button api-lookup" title="Hent stamdata" ${this._entity("selected_plate")?.attributes.motorapi_enabled ? "" : "disabled"}><ha-icon icon="mdi:database-sync-outline"></ha-icon></button></div>
      ${item.snapshot ? `<div class="snapshot-wrap"><button class="snapshot-button" type="button"><img data-snapshot alt="Seneste passage for ${escapeHtml(item.plate)}"><span><ha-icon icon="mdi:camera"></ha-icon>Seneste passage · ${formatDate(item.snapshot.captured_at)}${item.snapshot.camera ? ` · ${escapeHtml(item.snapshot.camera)}` : ""}</span></button><button class="delete-snapshot" type="button" title="Slet det gemte billede"><ha-icon icon="mdi:delete-outline"></ha-icon><span>Slet billede</span></button></div>` : ""}
      <form id="detail-form">
        <div class="category-editor" role="group" aria-label="Kategori">${Object.entries(CATEGORY).map(([key, value]) => `<label style="--category:${value.color}"><input type="radio" name="category" value="${key}" ${category === key ? "checked" : ""}><span><ha-icon icon="${value.icon}"></ha-icon>${value.label}</span></label>`).join("")}</div>
        <label class="notes-editor"><span>Bemærkning</span><textarea id="detail-notes" rows="2" placeholder="Tilføj en kort bemærkning…">${escapeHtml(item.notes || "")}</textarea></label>
        <label class="ignore-toggle"><input id="detail-ignored" type="checkbox" ${item.ignored ? "checked" : ""}><span><strong>Ignorér i oversigter</strong><small>Sagen og historikken bevares, men tæller ikke med i seneste passager eller trafikstatistik.</small></span></label>
        <label class="ignore-toggle"><input id="detail-notify" type="checkbox" ${item.notify_on_passage ? "checked" : ""}><span><strong>Notificér ved hver passage</strong><small>Sender besked til de enheder, der er valgt under integrationens notifikationsindstillinger.</small></span></label>
        <div class="detail-actions"><button type="submit" class="primary"><ha-icon icon="mdi:content-save-outline"></ha-icon>Gem ændringer</button><button type="button" class="edit-full"><ha-icon icon="mdi:pencil-outline"></ha-icon>Rediger stamdata</button></div>
        ${this._message ? `<p class="message">${escapeHtml(this._message)}</p>` : ""}
      </form>
      <div class="facts"><span><small>Mærke</small><strong>${escapeHtml(vehicle.make || "–")}</strong></span><span><small>Model</small><strong>${escapeHtml(vehicle.model || "–")}</strong></span><span><small>Farve</small><strong>${escapeHtml(vehicle.color || "–")}</strong></span><span><small>Årgang</small><strong>${escapeHtml(vehicle.model_year || "–")}</strong></span><span><small>Første gang set</small><strong>${formatDate(item.first_seen)}</strong></span><span><small>Senest set</small><strong>${formatDate(item.last_seen)}</strong></span></div>
      <div class="stats-grid">${this._statCard("Set totalt", item.observations_count || 0)}${this._statCard("Seneste 7 dage", stats.last_7_days ?? 0)}${this._statCard("Seneste 30 dage", stats.last_30_days ?? 0)}${this._statCard("Forskellige dage", item.different_days || 0)}${this._statCard("Typisk tidspunkt", clock(stats.typical_minute))}${this._statCard("Spredning", stats.spread_minutes == null ? "–" : `± ${stats.spread_minutes} min`)}${this._statCard("Gns. hastighed", speed.average_kmh == null ? "–" : `${speed.average_kmh} km/t`)}${this._statCard("Højeste hastighed", speed.maximum_kmh == null ? "–" : `${speed.maximum_kmh} km/t`)}${this._statCard("Hastighedsmålinger", speed.measured_passages ?? 0)}</div>
      <div class="time-range"><span><small>Tidligste passage</small><strong>${clock(stats.earliest_minute)}</strong></span><ha-icon icon="mdi:arrow-right"></ha-icon><span><small>Seneste passage</small><strong>${clock(stats.latest_minute)}</strong></span></div>
      <div class="charts">${this._timeChart(stats)}${this._dailyChart(stats)}</div>
      <div class="insight"><ha-icon icon="mdi:chart-timeline-variant-shimmer"></ha-icon><div><small>Automatisk mønsterbeskrivelse · ${escapeHtml(pattern.confidence)} sikkerhed</small><strong>${escapeHtml(pattern.primary)}</strong>${pattern.secondary?.length ? `<ul>${pattern.secondary.map((text) => `<li>${escapeHtml(text)}</li>`).join("")}</ul>` : ""}${pattern.evidence?.length ? `<details><summary>Sådan er konklusionen beregnet</summary>${pattern.evidence.map((text) => `<span>${escapeHtml(text)}</span>`).join("")}</details>` : ""}</div></div>
      <section class="passages"><div class="subheading"><strong>Seneste passager</strong><small>De seneste ${Math.min(50, item.observations?.length || 0)} kan rettes eller slettes</small></div>${(item.observations || []).slice().reverse().map((observation) => `<div class="passage-row"><span><strong>${formatDate(observation.timestamp)}${observation.speed_kmh == null ? "" : ` · ${escapeHtml(observation.speed_kmh)} km/t`}</strong><small>${escapeHtml(observation.camera || "Kamera ikke angivet")}${observation.score == null ? "" : ` · ${Math.round(observation.score * 100)} %`}</small></span><span class="passage-actions"><button type="button" data-edit-passage="${escapeHtml(observation.event_id)}" title="Rediger passage"><ha-icon icon="mdi:pencil-outline"></ha-icon></button><button type="button" data-delete-passage="${escapeHtml(observation.event_id)}" title="Slet passage"><ha-icon icon="mdi:delete-outline"></ha-icon></button></span></div>`).join("") || '<div class="empty">Ingen passager på sagen</div>'}</section>
      ${masterData.length ? `<details class="master-data"><summary>Alle lokalt gemte stamdata (${masterData.length})</summary><dl>${masterData.map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${escapeHtml(typeof value === "object" ? JSON.stringify(value) : value)}</dd></div>`).join("")}</dl></details>` : ""}
    </section>`;
  }

  _recent() {
    const items = this._entity("recent")?.attributes.items || [];
    return `<aside class="recent-panel panel" aria-label="Seneste passager"><div class="panel-title"><div><small>LIVE OVERSIGT</small><h2>Seneste passager</h2></div><ha-icon icon="mdi:history"></ha-icon></div><div class="recent-list">${items.length ? items.map((item) => {
      const vehicle = item.vehicle || {};
      return `<button class="recent-row" data-plate="${escapeHtml(item.plate)}"><time>${formatDate(item.timestamp, true)}</time><span><strong>${escapeHtml(plateDisplay(item.plate))}</strong><small>${escapeHtml([vehicle.make, vehicle.model].filter(Boolean).join(" ") || item.name || "Ukendt køretøj")}</small>${item.speed_kmh == null ? "" : `<small class="recent-speed"><ha-icon icon="mdi:speedometer"></ha-icon>${escapeHtml(item.speed_kmh)} km/t</small>`}</span>${this._badge(item)}</button>`;
    }).join("") : '<div class="empty">Ingen passager registreret endnu</div>'}</div></aside>`;
  }

  _fastestPassage(item, speedLimit) {
    const vehicleCase = this._vehicles().find((candidate) => candidate.plate === item.plate) || { plate: item.plate };
    const vehicle = vehicleCase.vehicle || {};
    const vehicleName = [vehicle.make, vehicle.model].filter(Boolean).join(" ") || vehicleCase.name || "Ukendt køretøj";
    return `<button data-plate="${escapeHtml(item.plate)}" title="Åbn køretøjssagen"><span class="fastest-copy"><strong>${escapeHtml(plateDisplay(item.plate))}</strong><small>${escapeHtml(vehicleName)}</small><small>${formatDate(item.timestamp)}</small></span>${this._badge(vehicleCase)}<b class="${item.speed_kmh > speedLimit ? "over-limit" : ""}">${escapeHtml(item.speed_kmh)} km/t</b><ha-icon icon="mdi:chevron-right"></ha-icon></button>`;
  }

  _traffic() {
    const stats = this._entity("traffic_stats")?.attributes || {};
    const hours = stats.hour_average || stats.hour_counts || Array(24).fill(0);
    const weekdays = stats.weekday_average || stats.weekday_counts || Array(7).fill(0);
    const categories = stats.categories || { known: 0, taxi: 0, unknown: 0, unwanted: 0 };
    const totalCategories = Math.max(1, categories.known + (categories.taxi || 0) + categories.unknown + categories.unwanted);
    const maxHour = Math.max(1, ...hours);
    const maxWeekday = Math.max(1, ...weekdays);
    const weekdayNames = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"];
    const busiestHour = stats.busiest_hour == null ? "–" : `${String(stats.busiest_hour).padStart(2, "0")}:00–${String((stats.busiest_hour + 1) % 24).padStart(2, "0")}:00`;
    const busiestDay = stats.busiest_weekday == null ? "–" : weekdayNames[stats.busiest_weekday];
    const speed = stats.speed || {};
    const speedLimit = Number(stats.speed_limit) || 50;
    const offenders = (speed.fastest_passages || []).filter((item) => item.speed_kmh > speedLimit);
    return `<section class="traffic-panel panel"><div class="traffic-head"><div><small>VEJENS TRAFIK</small><h2>Generel trafikstatistik</h2><p>Ignorerede køretøjer er ikke medregnet.</p></div><ha-icon icon="mdi:chart-box-outline"></ha-icon></div>
      <div class="traffic-kpis">${this._statCard("Passager i dag", stats.today ?? 0)}${this._statCard("Seneste 7 dage", stats.last_7_days ?? 0)}${this._statCard("Seneste 30 dage", stats.last_30_days ?? 0)}${this._statCard("Gns. pr. dag", stats.daily_average_30 ?? 0)}${this._statCard("Travleste time", busiestHour)}${this._statCard("Travleste ugedag", busiestDay)}</div>
      <div class="traffic-grid"><div class="traffic-chart wide"><div class="chart-title"><strong>Passager pr. målt time</strong><span>Normaliseret efter faktisk driftstid</span></div><svg viewBox="0 0 484 130" role="img" aria-label="Gennemsnitlig trafik fordelt på døgnets timer">${hours.map((count, hour) => `<rect x="${hour * 20 + 3}" y="${104 - count / maxHour * 88}" width="14" height="${Math.max(count ? 3 : 0, count / maxHour * 88)}" rx="2" class="chart-bar"><title>${hour}:00 · ${Number(count).toFixed(2)} passager pr. målt time</title></rect>`).join("")}<line x1="3" y1="105" x2="480" y2="105" class="axis"/><text x="3" y="122">00</text><text x="238" y="122">12</text><text x="460" y="122">23</text></svg></div>
        <div class="traffic-chart"><div class="chart-title"><strong>Ugedage</strong><span>Gns. pr. målt ugedag</span></div><div class="weekday-bars">${weekdays.map((count, day) => `<div><span style="height:${Math.max(count ? 4 : 1, count / maxWeekday * 100)}px" title="${weekdayNames[day]}: ${Number(count).toFixed(2)}"></span><small>${weekdayNames[day]}</small><b>${Number(count).toFixed(1)}</b></div>`).join("")}</div></div>
        <div class="traffic-chart"><div class="chart-title"><strong>Trafikkens kategorier</strong><span>Fordelt på passager</span></div><div class="category-shares">${[["Kendte inkl. egne", categories.known, "#2e9d58"], ["Hyrevogne", categories.taxi || 0, "#7c3aed"], ["Ukendte", categories.unknown, "#b7791f"], ["Uønskede", categories.unwanted, "#d64545"]].map(([label, count, color]) => `<div><span><i style="--share-color:${color}"></i>${label}</span><strong>${Math.round(count / totalCategories * 100)} %</strong><small>${count} passager</small><progress max="${totalCategories}" value="${count}" style="--share-color:${color}"></progress></div>`).join("")}</div></div>
      </div><section class="speed-panel"><div class="chart-title"><strong>Hastigheder</strong><span>${speed.measured_passages ?? 0} målte passager</span></div><div class="speed-kpis">${this._statCard("Gennemsnit", speed.average_kmh == null ? "–" : `${speed.average_kmh} km/t`)}${this._statCard("Højeste måling", speed.maximum_kmh == null ? "–" : `${speed.maximum_kmh} km/t`)}${this._statCard(`Over ${speedLimit} km/t`, speed.over_limit ?? offenders.length)}</div><div class="fastest-list"><strong>Højeste målte hastigheder</strong>${(speed.fastest_passages || []).length ? (speed.fastest_passages || []).map((item) => this._fastestPassage(item, speedLimit)).join("") : '<div class="empty">Ingen hastighedsmålinger endnu</div>'}</div><p class="speed-disclaimer"><ha-icon icon="mdi:information-outline"></ha-icon>Frigates hastighed er et kamerabaseret estimat og må ikke betragtes som en myndighedsgodkendt måling.</p></section><div class="traffic-note"><ha-icon icon="mdi:information-outline"></ha-icon><span><strong>${stats.unique_vehicles ?? 0} køretøjer indgår</strong><small>${stats.ignored_vehicles ?? 0} ignorerede køretøjssager er udeladt. Statistikken beskriver registrerede passager, ikke den samlede trafik som kameraet ikke har aflæst.</small></span></div></section>`;
  }

  _mobileNav() {
    return `<nav class="mobile-nav" aria-label="Kortvisning">${[["recent", "Seneste", "mdi:history"], ["vehicles", "Køretøjer", "mdi:car-multiple"], ["details", "Detaljer", "mdi:card-account-details-outline"], ["traffic", "Trafik", "mdi:chart-bar"]].map(([key, label, icon]) => `<button data-mobile-tab="${key}" class="${this._mobileTab === key ? "active" : ""}"><ha-icon icon="${icon}"></ha-icon>${label}</button>`).join("")}</nav>`;
  }

  _render() {
    if (!this.shadowRoot || !this._hass || !this._config) return;
    const unique = this._entity("unique_today")?.state ?? "0";
    const observations = this._entity("observations_today")?.state ?? "0";
    this.shadowRoot.innerHTML = `<style>${FrigateLprCard.styles}</style><ha-card><header><div><small>FRIGATE LPR</small><h1>${escapeHtml(this._config.title)}</h1></div><nav class="desktop-nav"><button data-desktop-view="registry" class="${this._desktopView === "registry" ? "active" : ""}"><ha-icon icon="mdi:car-multiple"></ha-icon>Køretøjer</button><button data-desktop-view="traffic" class="${this._desktopView === "traffic" ? "active" : ""}"><ha-icon icon="mdi:chart-bar"></ha-icon>Trafikstatistik</button></nav>${this._config.show_summary ? `<div class="headline-stats"><span><strong>${escapeHtml(unique)}</strong> unikke i dag</span><span><strong>${escapeHtml(observations)}</strong> passager i dag</span></div>` : ""}</header>${this._mobileNav()}<main data-mobile-active="${this._mobileTab}" data-desktop-active="${this._desktopView}">${this._vehicleList()}${this._config.show_details ? this._detail() : ""}${this._recent()}${this._traffic()}</main></ha-card>`;
    this._bind();
    this._loadSnapshot();
  }

  async _loadSnapshot() {
    const item = this._selected();
    const image = this.shadowRoot.querySelector("[data-snapshot]");
    if (!item?.snapshot || !image || !this._hass.fetchWithAuth) return;
    const key = `${item.plate}:${item.snapshot.captured_at}`;
    if (this._snapshotKey === key && this._snapshotUrl) {
      image.src = this._snapshotUrl;
      return;
    }
    try {
      const response = await this._hass.fetchWithAuth(`/api/frigate_lpr/snapshot/${encodeURIComponent(item.plate)}`);
      if (!response.ok) return;
      const blob = await response.blob();
      if (this._snapshotUrl) URL.revokeObjectURL(this._snapshotUrl);
      this._snapshotKey = key;
      this._snapshotUrl = URL.createObjectURL(blob);
      const current = this.shadowRoot.querySelector("[data-snapshot]");
      if (this._selected()?.plate === item.plate && current) current.src = this._snapshotUrl;
    } catch (_error) { /* Snapshot remains optional. */ }
  }

  async _selectPlate(plate) {
    this._selectedPlate = plate;
    const selector = this._entity("selected_plate");
    if (selector) await this._hass.callService("select", "select_option", { entity_id: selector.entity_id, option: plate });
    this._mobileTab = "details";
    this._desktopView = "registry";
    this._message = "";
    this._render();
  }

  _bind() {
    this.shadowRoot.querySelectorAll("[data-plate]").forEach((button) => button.addEventListener("click", () => this._selectPlate(button.dataset.plate)));
    this.shadowRoot.querySelectorAll("[data-mobile-tab]").forEach((button) => button.addEventListener("click", () => { this._mobileTab = button.dataset.mobileTab; this._render(); }));
    this.shadowRoot.querySelectorAll("[data-desktop-view]").forEach((button) => button.addEventListener("click", () => { this._desktopView = button.dataset.desktopView; this._render(); }));
    this.shadowRoot.getElementById("vehicle-search")?.addEventListener("input", (event) => {
      this._search = event.target.value;
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => {
        this._render();
        const input = this.shadowRoot.getElementById("vehicle-search");
        input?.focus();
        input?.setSelectionRange(input.value.length, input.value.length);
      }, 180);
    });
    this.shadowRoot.getElementById("category-filter")?.addEventListener("change", (event) => { this._filter = event.target.value; this._render(); });
    this.shadowRoot.getElementById("vehicle-sort")?.addEventListener("change", (event) => { this._sort = event.target.value; this._render(); });
    this.shadowRoot.querySelector(".new-case")?.addEventListener("click", () => this._openEditor(null));
    this.shadowRoot.querySelector(".edit-full")?.addEventListener("click", () => this._openEditor(this._selected()));
    this.shadowRoot.querySelector(".snapshot-button")?.addEventListener("click", () => {
      if (!this._snapshotUrl) return;
      const dialog = document.createElement("dialog");
      dialog.className = "snapshot-dialog";
      dialog.innerHTML = `<button class="icon-button" aria-label="Luk"><ha-icon icon="mdi:close"></ha-icon></button><img src="${escapeHtml(this._snapshotUrl)}" alt="Passagebillede">`;
      this.shadowRoot.append(dialog);
      dialog.querySelector("button").addEventListener("click", () => dialog.close());
      dialog.addEventListener("close", () => dialog.remove());
      dialog.showModal();
    });
    this.shadowRoot.querySelector(".delete-snapshot")?.addEventListener("click", async () => {
      const item = this._selected();
      if (!item || !window.confirm("Slet det gemte billede? Et nyt billede gemmes først ved køretøjets næste passage.")) return;
      try {
        await this._hass.callService("frigate_lpr", "remove_snapshot", { plate: item.plate });
        if (this._snapshotUrl) URL.revokeObjectURL(this._snapshotUrl);
        this._snapshotUrl = null;
        this._snapshotKey = null;
        this._message = "Billedet er slettet. Et nyt gemmes ved næste passage.";
      } catch (_error) { this._message = "Billedet kunne ikke slettes."; }
      this._render();
    });
    this.shadowRoot.getElementById("detail-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const item = this._selected();
      const category = new FormData(event.target).get("category");
      try {
        await this._hass.callService("frigate_lpr", "set_plate", { plate: item.plate, name: item.name || "", category, notes: this.shadowRoot.getElementById("detail-notes").value, ignored: this.shadowRoot.getElementById("detail-ignored").checked, notify_on_passage: this.shadowRoot.getElementById("detail-notify").checked });
        this._message = "Ændringerne er gemt lokalt på sagen.";
      } catch (_error) { this._message = "Ændringerne kunne ikke gemmes."; }
      this._render();
    });
    this.shadowRoot.querySelector(".api-lookup")?.addEventListener("click", async () => {
      const item = this._selected();
      this._message = "Henter stamdata…"; this._render();
      try {
        await this._hass.callService("frigate_lpr", "lookup_vehicle", { plate: item.plate });
        this._message = "Opslaget er afsluttet. Eventuelle fundne stamdata er gemt lokalt.";
      } catch (_error) { this._message = "Opslaget mislykkedes. Kontrollér MotorAPI-indstillingerne."; }
      this._render();
    });
    this.shadowRoot.querySelectorAll("[data-edit-passage]").forEach((button) => button.addEventListener("click", () => {
      const observation = (this._selected()?.observations || []).find((item) => item.event_id === button.dataset.editPassage);
      if (observation) this._openPassageEditor(this._selected().plate, observation);
    }));
    this.shadowRoot.querySelectorAll("[data-delete-passage]").forEach((button) => button.addEventListener("click", async () => {
      if (!window.confirm("Slet denne passage permanent? Køretøjets statistik genberegnes.")) return;
      try {
        await this._hass.callService("frigate_lpr", "remove_observation", { plate: this._selected().plate, event_id: button.dataset.deletePassage });
        this._message = "Passagen er slettet, og statistikken er genberegnet.";
      } catch (_error) { this._message = "Passagen kunne ikke slettes."; }
      this._render();
    }));
  }

  _openPassageEditor(plate, observation) {
    const date = new Date(observation.timestamp);
    const pad = (value) => String(value).padStart(2, "0");
    const localValue = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    const dialog = document.createElement("dialog");
    dialog.className = "passage-dialog";
    dialog.innerHTML = `<form method="dialog"><div class="dialog-head"><div><small>PASSAGE</small><h2>Rediger ${escapeHtml(plate)}</h2></div><button value="cancel" class="icon-button"><ha-icon icon="mdi:close"></ha-icon></button></div><div class="editor-grid"><label><span>Tidspunkt</span><input name="timestamp" type="datetime-local" value="${localValue}" required></label><label><span>Kamera</span><input name="camera" value="${escapeHtml(observation.camera || "")}"></label><label><span>LPR-score (0–1)</span><input name="score" type="number" min="0" max="1" step="0.01" value="${observation.score ?? ""}"></label><label><span>Hastighed (km/t)</span><input name="speed_kmh" type="number" min="0" max="300" step="0.1" value="${observation.speed_kmh ?? ""}"></label></div><div class="dialog-actions"><button value="cancel">Annuller</button><button value="save" class="primary">Gem passage</button></div></form>`;
    this.shadowRoot.append(dialog);
    dialog.showModal();
    dialog.addEventListener("close", async () => {
      if (dialog.returnValue === "save") {
        const data = Object.fromEntries(new FormData(dialog.querySelector("form")).entries());
        data.plate = plate;
        data.event_id = observation.event_id;
        data.timestamp = new Date(data.timestamp).toISOString();
        if (data.score === "") delete data.score; else data.score = Number(data.score);
        if (data.speed_kmh === "") delete data.speed_kmh; else data.speed_kmh = Number(data.speed_kmh);
        try { await this._hass.callService("frigate_lpr", "update_observation", data); this._message = "Passagen er rettet, og statistikken er genberegnet."; }
        catch (_error) { this._message = "Passagen kunne ikke gemmes."; }
      }
      dialog.remove();
      this._render();
    });
  }

  _openEditor(item) {
    const vehicle = item?.vehicle || {};
    const values = { plate: item?.plate || "", name: item?.name || "", category: categoryKey(item), notes: item?.notes || "", make: vehicle.make || "", model: vehicle.model || "", variant: vehicle.variant || "", model_type: vehicle.model_type || "", model_year: vehicle.model_year || "", color: vehicle.color || "", chassis_type: vehicle.chassis_type || "", fuel_type: vehicle.fuel_type || "", vehicle_type: vehicle.type || "", ignored: item?.ignored || false, notify_on_passage: item?.notify_on_passage || false };
    const field = (key, label, type = "text") => `<label><span>${label}</span><input name="${key}" type="${type}" value="${escapeHtml(values[key])}"></label>`;
    const dialog = document.createElement("dialog");
    dialog.className = "case-dialog";
    dialog.innerHTML = `<form method="dialog" id="case-editor"><div class="dialog-head"><div><small>KØRETØJSSAG</small><h2>${item ? `Rediger ${escapeHtml(item.plate)}` : "Nyt køretøj"}</h2></div><button value="cancel" class="icon-button"><ha-icon icon="mdi:close"></ha-icon></button></div><div class="editor-grid">${field("plate", "Nummerplade")}${field("name", "Navn / relation")}<label><span>Kategori</span><select name="category">${Object.entries(CATEGORY).map(([key, value]) => `<option value="${key}" ${values.category === key ? "selected" : ""}>${value.label}</option>`).join("")}</select></label>${field("make", "Mærke")}${field("model", "Model")}${field("variant", "Variant")}${field("model_type", "Modeltype")}${field("model_year", "Årgang", "number")}${field("color", "Farve")}${field("chassis_type", "Karrosseri")}${field("fuel_type", "Drivmiddel")}${field("vehicle_type", "Køretøjstype")}<label class="wide"><span>Bemærkning</span><textarea name="notes" rows="3">${escapeHtml(values.notes)}</textarea></label><label class="wide checkbox-field"><input name="ignored" type="checkbox" ${values.ignored ? "checked" : ""}><span>Ignorér i oversigter og trafikstatistik</span></label><label class="wide checkbox-field"><input name="notify_on_passage" type="checkbox" ${values.notify_on_passage ? "checked" : ""}><span>Notificér ved hver passage</span></label></div><div class="dialog-actions"><button value="cancel">Annuller</button><button value="save" class="primary">Gem køretøjssag</button></div></form>`;
    this.shadowRoot.append(dialog); dialog.showModal();
    dialog.addEventListener("close", async () => {
      if (dialog.returnValue === "save") {
        const data = Object.fromEntries(new FormData(dialog.querySelector("form")).entries());
        data.ignored = data.ignored === "on";
        data.notify_on_passage = data.notify_on_passage === "on";
        if (!data.plate.trim()) { dialog.remove(); this._message = "Nummerpladen skal udfyldes."; this._render(); return; }
        if (data.model_year) data.model_year = Number(data.model_year); else delete data.model_year;
        try { await this._hass.callService("frigate_lpr", "set_plate", data); this._selectedPlate = data.plate.toUpperCase().replace(/[^A-Z0-9]/g, ""); this._message = "Køretøjssagen er gemt."; }
        catch (_error) { this._message = "Køretøjssagen kunne ikke gemmes."; }
      }
      dialog.remove(); this._render();
    });
  }

  static styles = `
    :host{display:block;container-type:inline-size;--muted:var(--secondary-text-color);--surface:var(--ha-card-background,var(--card-background-color));font-family:var(--paper-font-body1_-_font-family,Arial,sans-serif)}*{box-sizing:border-box}ha-card{overflow:hidden;background:var(--surface);color:var(--primary-text-color);border-radius:var(--ha-card-border-radius,14px)}
    header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 22px;border-bottom:1px solid var(--divider-color)}header small,.panel-title small,.detail-top small,.dialog-head small,.traffic-head small{font-size:10px;font-weight:800;letter-spacing:.13em;color:var(--muted)}h1,h2,p{margin:0}h1{font-size:23px;margin-top:3px}h2{font-size:17px}.desktop-nav{display:flex;gap:5px;padding:4px;border-radius:10px;background:var(--secondary-background-color)}.desktop-nav button{display:flex;align-items:center;gap:5px;min-height:36px;padding:6px 10px;border:0;border-radius:8px;background:transparent;color:var(--muted);cursor:pointer}.desktop-nav button.active{background:var(--surface);color:var(--primary-color);font-weight:800}.desktop-nav ha-icon{--mdc-icon-size:17px}.headline-stats{display:flex;gap:10px}.headline-stats span{padding:8px 11px;border-radius:9px;background:var(--secondary-background-color);font-size:12px}.headline-stats strong{font-size:16px;margin-right:3px}
    main{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(390px,1.5fr) minmax(250px,.85fr);min-height:650px}.panel{min-width:0;padding:18px}.panel+.panel{border-left:1px solid var(--divider-color)}.panel-title,.detail-top,.identity,.dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.icon-button{display:grid;place-items:center;width:40px;height:40px;padding:0;border:1px solid var(--divider-color);border-radius:10px;background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer}.icon-button:disabled{opacity:.45;cursor:not-allowed}
    .search{display:flex;align-items:center;gap:8px;margin:14px 0 9px;padding:0 10px;border:1px solid var(--divider-color);border-radius:10px;background:var(--secondary-background-color)}.search ha-icon{color:var(--muted)}.search input{width:100%;height:42px;border:0;outline:0;background:transparent;color:var(--primary-text-color);font:inherit}.list-controls{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:10px}select,input,textarea{font:inherit}.list-controls select{min-width:0;padding:8px;border:1px solid var(--divider-color);border-radius:8px;background:var(--surface);color:var(--primary-text-color)}
    .vehicle-list,.recent-list{display:grid}.vehicle-row,.recent-row{display:flex;align-items:center;gap:10px;width:100%;min-height:66px;padding:10px 7px;border:0;border-bottom:1px solid var(--divider-color);background:transparent;color:var(--primary-text-color);text-align:left;cursor:pointer}.vehicle-row:hover,.recent-row:hover{background:var(--secondary-background-color)}.vehicle-row.selected{margin:2px 0;padding-left:10px;border:1px solid var(--primary-color);border-radius:10px;background:color-mix(in srgb,var(--primary-color) 8%,transparent)}.mini-plate{flex:0 0 auto;padding:5px 7px;border:1px solid #777;border-radius:4px;background:#f7f7f3;color:#111;font-size:11px;font-weight:800;letter-spacing:.05em}.vehicle-copy{min-width:0;flex:1}.vehicle-copy strong,.vehicle-copy small,.row-meta small,.recent-row span strong,.recent-row span small{display:block}.vehicle-copy strong,.vehicle-copy small,.recent-row span small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.vehicle-copy small,.row-meta small,.recent-row span small{margin-top:4px;color:var(--muted);font-size:11px}.row-meta{text-align:right}.ignored-label{display:inline-block;padding:4px 7px;border-radius:99px;background:var(--secondary-background-color);color:var(--muted);font-size:10px;font-weight:800}.badge{display:inline-flex;align-items:center;gap:4px;padding:4px 7px;border-radius:99px;background:color-mix(in srgb,var(--category) 14%,transparent);color:var(--category);font-size:10px;font-weight:800;white-space:nowrap}.badge ha-icon{--mdc-icon-size:13px}
    .detail-panel{overflow:hidden}.license-plate{display:flex;align-items:center;gap:10px;width:max-content;margin-top:8px;padding:8px 14px 8px 8px;border:2px solid #777;border-radius:7px;background:#f8f8f2;color:#111;font-size:24px;font-weight:800;letter-spacing:.09em;box-shadow:inset 0 0 0 2px #fff}.license-plate span{display:grid;place-items:center;align-self:stretch;padding:0 5px;background:#1769aa;color:#fff;font-size:9px;letter-spacing:0}.identity{margin:15px 0}.identity p{margin-top:4px;color:var(--muted);font-size:12px}.category-editor{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.category-editor input{position:absolute;opacity:0;pointer-events:none}.category-editor span{display:flex;align-items:center;justify-content:center;gap:4px;min-height:42px;padding:7px;border:1px solid var(--divider-color);border-radius:9px;color:var(--muted);font-size:11px;cursor:pointer}.category-editor ha-icon{--mdc-icon-size:15px}.category-editor input:checked+span{border-color:var(--category);background:color-mix(in srgb,var(--category) 13%,transparent);color:var(--category);font-weight:800}.notes-editor{display:grid;gap:5px;margin-top:11px}.notes-editor>span,.editor-grid label>span{font-size:11px;color:var(--muted)}.notes-editor textarea,.editor-grid input,.editor-grid select,.editor-grid textarea{width:100%;padding:10px;border:1px solid var(--divider-color);border-radius:9px;background:var(--surface);color:var(--primary-text-color);resize:vertical}.ignore-toggle{display:flex;align-items:flex-start;gap:9px;margin-top:10px;padding:9px;border:1px solid var(--divider-color);border-radius:9px}.ignore-toggle input{width:18px;height:18px}.ignore-toggle strong,.ignore-toggle small{display:block}.ignore-toggle small{margin-top:3px;color:var(--muted);font-size:10px}.detail-actions,.dialog-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:9px}.detail-actions button,.dialog-actions button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:40px;padding:7px 11px;border:1px solid var(--divider-color);border-radius:9px;background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer}.detail-actions .primary,.dialog-actions .primary{border-color:var(--primary-color);background:var(--primary-color);color:var(--text-primary-color,#fff)}.message{margin-top:8px;color:var(--primary-color);font-size:12px;text-align:right}
    .snapshot-wrap{position:relative;margin:0 0 12px}.snapshot-button{position:relative;display:block;width:100%;max-height:220px;padding:0;overflow:hidden;border:1px solid var(--divider-color);border-radius:11px;background:var(--secondary-background-color);cursor:zoom-in}.snapshot-button img{display:block;width:100%;min-height:120px;max-height:220px;object-fit:cover}.snapshot-button span{position:absolute;left:8px;bottom:8px;display:flex;align-items:center;gap:5px;max-width:calc(100% - 16px);padding:6px 8px;border-radius:7px;background:rgba(0,0,0,.72);color:#fff;font-size:10px}.snapshot-button ha-icon{--mdc-icon-size:14px}.delete-snapshot{position:absolute;z-index:2;top:8px;right:8px;display:flex;align-items:center;gap:5px;min-height:36px;padding:6px 9px;border:0;border-radius:8px;background:rgba(145,25,25,.88);color:#fff;cursor:pointer}.delete-snapshot ha-icon{--mdc-icon-size:16px}.delete-snapshot span{font-size:11px;font-weight:700}.facts{display:grid;grid-template-columns:repeat(3,1fr);margin:16px 0;border:1px solid var(--divider-color);border-radius:11px;overflow:hidden}.facts span{min-width:0;padding:10px;border-right:1px solid var(--divider-color);border-bottom:1px solid var(--divider-color)}.facts span:nth-child(3n){border-right:0}.facts span:nth-last-child(-n+3){border-bottom:0}.facts small,.facts strong,.stat small,.stat strong,.time-range small,.time-range strong,.insight small,.insight strong{display:block}.facts small,.stat small,.time-range small,.insight small{color:var(--muted);font-size:10px}.facts strong{margin-top:4px;overflow-wrap:anywhere;font-size:12px}.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.stat{padding:10px;border-radius:9px;background:var(--secondary-background-color)}.stat strong{margin-top:5px;font-size:17px}.time-range{display:flex;align-items:center;justify-content:center;gap:18px;margin:11px 0;padding:9px;border:1px solid var(--divider-color);border-radius:9px;text-align:center}.time-range ha-icon{color:var(--muted)}
    .charts{display:grid;grid-template-columns:1.5fr 1fr;gap:8px}.chart{min-width:0;padding:10px;border:1px solid var(--divider-color);border-radius:10px}.chart-title{display:flex;justify-content:space-between;gap:8px;font-size:11px}.chart-title span{color:var(--muted)}.chart svg{display:block;width:100%;height:auto;margin-top:5px}.chart text{fill:var(--muted);font-size:8px}.chart-bar{fill:var(--primary-color)}.axis{stroke:var(--divider-color)}.day-bars{display:flex;align-items:end;justify-content:space-around;height:68px;margin-top:8px}.day-bars div{display:grid;align-items:end;justify-items:center;height:100%;width:12%}.day-bars span{display:block;width:9px;min-height:1px;border-radius:3px 3px 0 0;background:var(--primary-color)}.day-bars small{margin-top:3px;color:var(--muted);font-size:9px}.insight{display:flex;align-items:flex-start;gap:9px;margin:10px 0;padding:11px;border-radius:10px;background:color-mix(in srgb,var(--primary-color) 9%,var(--secondary-background-color))}.insight>ha-icon{flex:0 0 auto;color:var(--primary-color)}.insight>div{min-width:0}.insight strong{margin-top:3px;font-size:12px}.insight ul{margin:7px 0 0;padding-left:18px;font-size:11px}.insight details{margin-top:8px;font-size:10px}.insight summary{cursor:pointer;color:var(--muted)}.insight details span{margin-top:4px}.master-data{padding:10px;border:1px solid var(--divider-color);border-radius:10px}.master-data summary{cursor:pointer;font-size:12px;font-weight:700}.master-data dl{margin:8px 0 0}.master-data dl div{display:grid;grid-template-columns:1fr 1.5fr;gap:9px;padding:5px 0;border-top:1px solid var(--divider-color);font-size:11px}.master-data dt{text-transform:capitalize;color:var(--muted)}.master-data dd{margin:0;overflow-wrap:anywhere;text-align:right}
    .passages{margin:12px 0;border:1px solid var(--divider-color);border-radius:10px;overflow:hidden}.subheading{display:flex;justify-content:space-between;gap:8px;padding:10px;background:var(--secondary-background-color)}.subheading small{color:var(--muted)}.passage-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 10px;border-top:1px solid var(--divider-color)}.passage-row>span:first-child{min-width:0}.passage-row strong,.passage-row small{display:block}.passage-row small{margin-top:3px;color:var(--muted);font-size:10px}.passage-actions{display:flex;gap:5px}.passage-actions button{display:grid;place-items:center;width:36px;height:36px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer}.passage-actions button:last-child{color:#d64545}.passage-actions ha-icon{--mdc-icon-size:17px}
    .traffic-panel{display:none;grid-column:1/-1;padding:22px!important}.traffic-head{display:flex;align-items:flex-start;justify-content:space-between}.traffic-head p{margin-top:5px;color:var(--muted);font-size:12px}.traffic-head>ha-icon{--mdc-icon-size:34px;color:var(--primary-color)}.traffic-kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin:18px 0}.traffic-grid{display:grid;grid-template-columns:1.5fr 1fr;gap:12px}.traffic-chart{min-width:0;padding:14px;border:1px solid var(--divider-color);border-radius:12px}.traffic-chart.wide{grid-column:1/-1}.traffic-chart svg{display:block;width:100%;max-height:240px;margin-top:8px}.traffic-chart text{fill:var(--muted);font-size:10px}.weekday-bars{display:flex;align-items:end;justify-content:space-around;height:150px;margin-top:12px}.weekday-bars div{display:grid;align-items:end;justify-items:center;width:12%;height:100%}.weekday-bars span{display:block;width:min(24px,80%);min-height:1px;border-radius:4px 4px 0 0;background:var(--primary-color)}.weekday-bars small{margin-top:5px;color:var(--muted)}.weekday-bars b{font-size:10px}.category-shares{display:grid;gap:13px;margin-top:14px}.category-shares>div{display:grid;grid-template-columns:1fr auto;gap:3px 8px}.category-shares span{display:flex;align-items:center;gap:6px;font-size:12px}.category-shares i{width:9px;height:9px;border-radius:50%;background:var(--share-color)}.category-shares small{color:var(--muted);font-size:10px}.category-shares progress{grid-column:1/-1;width:100%;height:7px;border:0;border-radius:10px;overflow:hidden}.category-shares progress::-webkit-progress-bar{background:var(--secondary-background-color)}.category-shares progress::-webkit-progress-value{background:var(--share-color)}.category-shares progress::-moz-progress-bar{background:var(--share-color)}.speed-panel{margin-top:12px;padding:14px;border:1px solid var(--divider-color);border-radius:12px}.speed-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.fastest-list{display:grid}.fastest-list>strong{margin-bottom:5px;font-size:12px}.fastest-list button{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto;align-items:center;gap:10px;min-height:58px;padding:8px 5px;border:0;border-top:1px solid var(--divider-color);background:transparent;color:var(--primary-text-color);text-align:left;cursor:pointer}.fastest-list button:hover{background:var(--secondary-background-color)}.fastest-copy,.fastest-copy strong,.fastest-copy small{display:block;min-width:0}.fastest-copy strong,.fastest-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fastest-list small{margin-top:2px;color:var(--muted);font-size:10px}.fastest-list b{font-variant-numeric:tabular-nums;white-space:nowrap}.fastest-list b.over-limit{color:#d64545}.fastest-list button>ha-icon{--mdc-icon-size:18px;color:var(--muted)}.speed-disclaimer{display:flex;align-items:center;gap:7px;margin-top:10px!important;color:var(--muted);font-size:10px}.speed-disclaimer ha-icon{--mdc-icon-size:16px}.traffic-note{display:flex;align-items:center;gap:9px;margin-top:12px;padding:11px;border-radius:10px;background:var(--secondary-background-color)}.traffic-note ha-icon{color:var(--primary-color)}.traffic-note strong,.traffic-note small{display:block}.traffic-note small{margin-top:3px;color:var(--muted)}main[data-desktop-active=traffic]>.vehicle-panel,main[data-desktop-active=traffic]>.detail-panel,main[data-desktop-active=traffic]>.recent-panel{display:none}main[data-desktop-active=traffic]>.traffic-panel{display:block}
    .recent-panel{background:color-mix(in srgb,var(--secondary-background-color) 55%,var(--surface))}.recent-panel>.panel-title>ha-icon{color:var(--muted)}.recent-list{margin-top:10px}.recent-row time{flex:0 0 48px;font-size:12px;font-weight:800;font-variant-numeric:tabular-nums}.recent-row>span{min-width:0;flex:1}.recent-row>span strong{font-size:13px;letter-spacing:.04em}.recent-row>span .recent-speed{display:flex;align-items:center;gap:3px;margin-top:3px;color:var(--muted);font-size:9px;font-weight:600}.recent-speed ha-icon{--mdc-icon-size:11px}.recent-row .badge{max-width:72px}.empty{padding:30px 12px;text-align:center;color:var(--muted)}.mobile-nav{display:none}
    dialog.case-dialog,dialog.passage-dialog{width:min(680px,calc(100% - 28px));max-height:calc(100% - 28px);padding:0;border:1px solid var(--divider-color);border-radius:14px;background:var(--surface);color:var(--primary-text-color);box-shadow:0 18px 55px rgba(0,0,0,.35)}dialog::backdrop{background:rgba(0,0,0,.45)}.case-dialog form,.passage-dialog form{padding:18px}.editor-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}.editor-grid label{display:grid;gap:5px}.editor-grid .wide{grid-column:1/-1}.checkbox-field{display:flex!important;grid-template-columns:auto 1fr!important;align-items:center}.checkbox-field input{width:18px}.snapshot-dialog{width:min(920px,calc(100% - 24px));padding:8px;border:0;border-radius:12px;background:#111}.snapshot-dialog .icon-button{position:absolute;z-index:1;top:16px;right:16px;background:rgba(0,0,0,.7);color:#fff}.snapshot-dialog img{display:block;width:100%;max-height:calc(100vh - 40px);object-fit:contain;border-radius:8px}
    @container (max-width: 900px){main{grid-template-columns:minmax(235px,.8fr) minmax(390px,1.2fr)}.recent-panel{grid-column:1/-1;border-left:0!important;border-top:1px solid var(--divider-color)}.recent-list{grid-template-columns:repeat(2,1fr);gap:0 12px}.traffic-kpis{grid-template-columns:repeat(3,1fr)}}
    @container (max-width: 620px){header{padding:16px}.desktop-nav{display:none}.headline-stats{gap:5px}.headline-stats span{padding:6px 7px;font-size:10px}.headline-stats strong{font-size:13px}.mobile-nav{display:grid;grid-template-columns:repeat(4,1fr);padding:6px;border-bottom:1px solid var(--divider-color)}.mobile-nav button{display:flex;align-items:center;justify-content:center;gap:4px;min-height:46px;padding:4px;border:0;border-radius:9px;background:transparent;color:var(--muted);font-size:11px}.mobile-nav button.active{background:var(--secondary-background-color);color:var(--primary-color);font-weight:800}.mobile-nav ha-icon{--mdc-icon-size:17px}main{display:block;min-height:0}main>.panel,main[data-desktop-active=traffic]>.panel{display:none;border:0;padding:14px}main[data-mobile-active=recent]>.recent-panel,main[data-mobile-active=vehicles]>.vehicle-panel,main[data-mobile-active=details]>.detail-panel,main[data-mobile-active=traffic]>.traffic-panel{display:block}.recent-list{grid-template-columns:1fr}.vehicle-row,.recent-row{min-height:70px}.category-editor{grid-template-columns:repeat(2,1fr)}.facts{grid-template-columns:repeat(2,1fr)}.facts span,.facts span:nth-child(3n){border-right:1px solid var(--divider-color);border-bottom:1px solid var(--divider-color)}.facts span:nth-child(2n){border-right:0}.facts span:nth-last-child(-n+2){border-bottom:0}.charts,.traffic-grid{grid-template-columns:1fr}.traffic-chart.wide{grid-column:auto}.traffic-kpis{grid-template-columns:repeat(2,1fr)}.stats-grid{grid-template-columns:repeat(2,1fr)}.detail-actions{display:grid;grid-template-columns:1fr 1fr}.editor-grid{grid-template-columns:1fr}.license-plate{font-size:21px}.subheading{display:grid}.dialog-actions{position:sticky;bottom:0;padding-top:8px;background:var(--surface)}}
    @container (max-width: 390px){header{align-items:flex-start}.headline-stats{display:grid}.list-controls{grid-template-columns:1fr}.row-meta .badge{padding:4px}.category-editor span{font-size:10px}.stats-grid{grid-template-columns:1fr 1fr}.detail-actions{grid-template-columns:1fr}}
  `;
}

class FrigateLprCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); }
  set hass(hass) { this._hass = hass; }
  setConfig(config) { this._config = { ...FrigateLprCard.getStubConfig(), ...config }; this._render(); }
  _changed(patch) { this._config = { ...this._config, ...patch }; this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true })); }
  _render() {
    if (!this._config) return;
    this.shadowRoot.innerHTML = `<style>.form{display:grid;gap:18px;padding:8px 0}.field{display:grid;gap:7px}.field>span{font-weight:500}input{box-sizing:border-box;width:100%;font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:12px}label.toggle{display:flex;align-items:center;gap:10px;cursor:pointer}input[type=checkbox]{width:18px;height:18px}small{color:var(--secondary-text-color)}</style><div class="form"><label class="field"><span>Titel</span><input id="title" value="${escapeHtml(this._config.title)}"></label><label class="field"><span>Maksimalt antal køretøjer</span><input id="max_items" type="number" min="1" max="200" value="${Number(this._config.max_items) || 50}"><small>Listen kan fortsat søges og filtreres.</small></label><label class="toggle"><input id="show_summary" type="checkbox" ${this._config.show_summary ? "checked" : ""}><span>Vis dagens nøgletal</span></label><label class="toggle"><input id="show_details" type="checkbox" ${this._config.show_details ? "checked" : ""}><span>Vis detalje- og statistikvisning</span></label></div>`;
    this.shadowRoot.getElementById("title").addEventListener("input", (event) => this._changed({ title: event.target.value }));
    this.shadowRoot.getElementById("max_items").addEventListener("change", (event) => this._changed({ max_items: Math.max(1, Math.min(200, Number(event.target.value) || 50)) }));
    this.shadowRoot.getElementById("show_summary").addEventListener("change", (event) => this._changed({ show_summary: event.target.checked }));
    this.shadowRoot.getElementById("show_details").addEventListener("change", (event) => this._changed({ show_details: event.target.checked }));
  }
}

if (!customElements.get(CARD_NAME)) customElements.define(CARD_NAME, FrigateLprCard);
if (!customElements.get("frigate-lpr-card-editor")) customElements.define("frigate-lpr-card-editor", FrigateLprCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_NAME)) window.customCards.push({ type: CARD_NAME, name: "Frigate LPR Registry", description: "Responsivt køretøjsregister til private parkeringsarealer og boligforeninger.", preview: true, configurable: true, documentationURL: "https://github.com/msamsing/frigate-lpr-ha#dashboard" });
