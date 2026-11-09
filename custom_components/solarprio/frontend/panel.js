/* solarprio sidebar panel: drag-and-drop priorities. No build step, no dependencies. */

const T = {
  en: {
    title: "Solar routing",
    routing: "Routing",
    available: "Available",
    routed: "Routed",
    hint: "Drag the handle (or use the arrows) to set the order. The top device is served first.",
    empty: "No device yet. Use “Add a device” above.",
    add: "Add a device",
    edit: "Edit",
    remove: "Delete",
    settingsBtn: "Settings",
    addTitle: "Add a device",
    editTitle: "Edit a device",
    settingsTitle: "Measurement and safety settings",
    chooseType: "What do you want to add?",
    save: "Save",
    cancel: "Cancel",
    confirmRemove: "Delete “{name}”? Its load is switched off.",
    required: "Required",
    saveFailed: "Not saved",
    loadFailed: "Could not open the form.",
    saved: "Saved. Loads are switched off for a moment while the new settings are applied.",
    removed: "Deleted.",
    invalid: "Invalid value",
    advanced: "Advanced settings",
    presetsTitle: "Ready-made",
    profileStatus: { simulated: "tested in simulation only", from_docs: "from documentation, untested", untested: "untested" },
    otherTypes: "Other types",
    staleHint: "A sensor that only reports when its value changes can look old. If this one is fine, set the delay to 0 in Settings.",
    warnings: {
      offpeak_numeric: "Saved, but the off-peak entity you picked reports a number (an energy index?). A tariff period reads like HC.. or HP..: check it in Developer tools > States.",
    },
    modes: {
      solar: "solar", offpeak: "off-peak", sanitary: "sanitary minimum", offpeak_limited: "off-peak, limited by the subscription",
      sanitary_limited: "sanitary minimum, limited by the subscription", hot: "water hot", sensor_fault: "temperature unknown: stopped",
    },
    opt: { export: "Grid power (one sensor)", production: "Production and consumption", off: "Switch the loads off",
           hold: "Keep the current state", watts: "Watts", percent: "Percent" },
    on: "on",
    off: "off",
    max: "max",
    soc: "SoC",
    unplugged: "unplugged",
    offpeak: { heating: "off-peak: running", done: "off-peak: finished", waiting: "off-peak: waiting" },
    disabled: "Disabled",
    error: "Could not save, order restored.",
    notConfigured: "solarprio is not set up.",
    up: "Move up",
    down: "Move down",
    drag: "Drag to reorder",
    enable: "Enable",
    status: {
      starting: "Starting",
      routing: "Routing",
      disabled: "Routing off",
      measurement_lost_off: "Measurement lost: loads off",
      measurement_lost_hold: "Measurement lost: holding",
    },
  },
  fr: {
    title: "Routage solaire",
    routing: "Routage",
    available: "Disponible",
    routed: "Routé",
    hint: "Glissez la poignée (ou utilisez les flèches) pour définir l'ordre. L'appareil du haut est servi en premier.",
    empty: "Aucun appareil. Utilisez « Ajouter un appareil » ci-dessus.",
    add: "Ajouter un appareil",
    edit: "Modifier",
    remove: "Supprimer",
    settingsBtn: "Réglages",
    addTitle: "Ajouter un appareil",
    editTitle: "Modifier un appareil",
    settingsTitle: "Réglages de la mesure et de la sécurité",
    chooseType: "Que voulez-vous ajouter ?",
    save: "Enregistrer",
    cancel: "Annuler",
    confirmRemove: "Supprimer « {name} » ? Sa charge est éteinte.",
    required: "Obligatoire",
    saveFailed: "Non enregistré",
    loadFailed: "Impossible d'ouvrir le formulaire.",
    saved: "Enregistré. Les charges sont éteintes un instant, le temps d'appliquer les nouveaux réglages.",
    removed: "Supprimé.",
    invalid: "Valeur invalide",
    advanced: "Réglages avancés",
    presetsTitle: "Modèles prêts à l'emploi",
    profileStatus: { simulated: "testé en simulation seulement", from_docs: "d'après la documentation, non testé", untested: "non testé" },
    otherTypes: "Autres types",
    staleHint: "Un capteur qui ne publie que lorsque sa valeur change peut sembler vieux. Si celui-ci est en bon état, mettez le délai à 0 dans Réglages.",
    warnings: {
      offpeak_numeric: "Enregistré, mais l'entité d'heures creuses choisie donne un nombre (un index d'énergie ?). Une période tarifaire se lit HC.. ou HP.. : vérifiez dans Outils de développement > États.",
    },
    modes: {
      solar: "solaire", offpeak: "heures creuses", sanitary: "minimum sanitaire", offpeak_limited: "heures creuses, limité par l'abonnement",
      sanitary_limited: "minimum sanitaire, limité par l'abonnement", hot: "eau chaude", sensor_fault: "température inconnue : arrêt",
    },
    opt: { export: "Puissance réseau (un capteur)", production: "Production et consommation", off: "Éteindre les charges",
           hold: "Garder l'état actuel", watts: "Watts", percent: "Pourcentage" },
    on: "marche",
    off: "arrêt",
    max: "max",
    soc: "Niveau",
    unplugged: "débranché",
    offpeak: { heating: "heures creuses : en cours", done: "heures creuses : terminé", waiting: "heures creuses : en attente" },
    disabled: "Désactivé",
    error: "Enregistrement impossible, ordre restauré.",
    notConfigured: "solarprio n'est pas configuré.",
    up: "Monter",
    down: "Descendre",
    drag: "Glisser pour réordonner",
    enable: "Activer",
    status: {
      starting: "Démarrage",
      routing: "Routage actif",
      disabled: "Routage arrêté",
      measurement_lost_off: "Mesure perdue : appareils éteints",
      measurement_lost_hold: "Mesure perdue : état conservé",
    },
  },
};

const STYLE = `
  :host { display: block; background: var(--primary-background-color); color: var(--primary-text-color); min-height: 100%;
          font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, sans-serif)); }
  .wrap { max-width: 760px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  header { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
  h1 { font-size: 22px; font-weight: 400; margin: 0; flex: 1; }
  ha-card { display: block; margin-bottom: 16px; }
  .card-content { padding: 16px; }
  .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: center; align-items: start; }
  .summary .label { font-size: 12px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .04em; }
  .summary .value { font-size: 24px; margin-top: 4px; }
  .summary ha-switch { margin-top: 8px; }
  .status { font-size: 14px; color: var(--secondary-text-color); margin-top: 12px; text-align: center; }
  .status.bad { color: var(--error-color, #db4437); }
  .status .detail { display: block; font-size: 12px; margin-top: 4px; word-break: break-all; }
  .status .hint2 { display: block; font-size: 12px; margin-top: 4px; font-style: italic; }
  .hint { color: var(--secondary-text-color); font-size: 14px; margin: 0 0 12px; }
  ul { list-style: none; margin: 0; padding: 0; position: relative; }
  li.row { display: flex; align-items: center; gap: 8px; padding: 8px 12px; margin-bottom: 8px;
           background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #ddd);
           border-radius: var(--ha-card-border-radius, 12px); transition: transform .15s ease, box-shadow .15s ease; }
  li.row.dragging { transition: none; z-index: 2; box-shadow: 0 6px 16px rgba(0,0,0,.3); position: relative; }
  li.row.off { opacity: .55; }
  .handle { cursor: grab; touch-action: none; padding: 8px 4px; border: 0; background: none; color: var(--secondary-text-color); display: flex; }
  .handle:active { cursor: grabbing; }
  .handle:focus-visible { outline: 2px solid var(--primary-color); border-radius: 4px; }
  .rank { min-width: 28px; height: 28px; border-radius: 50%; background: var(--primary-color); color: var(--text-primary-color, #fff);
          display: flex; align-items: center; justify-content: center; font-weight: 500; font-size: 14px; }
  .info { flex: 1; min-width: 0; }
  .name { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar { height: 6px; border-radius: 3px; background: var(--divider-color, #ddd); margin-top: 6px; overflow: hidden; }
  .bar > div { height: 100%; background: var(--primary-color); transition: width .3s ease; }
  .power { font-size: 13px; min-width: 76px; text-align: right; color: var(--secondary-text-color); }
  .arrows { display: flex; flex-direction: column; }
  .arrows ha-icon-button { --mdc-icon-button-size: 24px; --mdc-icon-size: 20px; }
  li.row > ha-icon-button { --mdc-icon-button-size: 40px; --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .empty { text-align: center; color: var(--secondary-text-color); padding: 24px 8px; }
  ha-dialog { --mdc-dialog-min-width: min(560px, 92vw); --mdc-dialog-max-width: 600px; }
  .choices { display: flex; flex-direction: column; gap: 8px; }
  .choices ha-button { width: 100%; }
  .dialog-hint { color: var(--secondary-text-color); font-size: 14px; margin: 0 0 12px; }
  .dialog-title { margin: 16px 0 8px; font-size: 14px; font-weight: 500; color: var(--secondary-text-color); }
  ha-alert { display: block; margin-bottom: 12px; }
  ha-alert[hidden] { display: none; }
  @media (max-width: 520px) { .power { display: none; } .summary .value { font-size: 20px; } header { flex-wrap: wrap; } }
`;

const GRIP =
  '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 3h2v2H9V3m4 0h2v2h-2V3M9 7h2v2H9V7m4 0h2v2h-2V7m-4 4h2v2H9v-2m4 0h2v2h-2v-2m-4 4h2v2H9v-2m4 0h2v2h-2v-2m-4 4h2v2H9v-2m4 0h2v2h-2v-2Z"/></svg>';

const CHEVRON_UP = "M7.41,15.41L12,10.83L16.59,15.41L18,14L12,8L6,14L7.41,15.41Z";
const CHEVRON_DOWN = "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z";
const MDI_PENCIL = "M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z";
const MDI_DELETE = "M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z";
const PENCIL =
  '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M20.71 7.04c.39-.39.39-1.04 0-1.41l-2.34-2.34c-.37-.39-1.02-.39-1.41 0l-1.84 1.83 3.75 3.75M3 17.25V21h3.75L17.81 9.93l-3.75-3.75L3 17.25Z"/></svg>';
const TRASH =
  '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 4h-3.5l-1-1h-5l-1 1H5v2h14M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12Z"/></svg>';

const fmtW = (w) => (w == null ? "-" : `${Math.round(w)} W`);

class SolarPrioPanel extends HTMLElement {
  constructor() {
    super();
    this._state = null;
    this._key = null;
    this._notConfigured = false;
    this._busy = false; // saving or dragging: do not overwrite local order with a poll
    this._dialogEl = null; // the open add/edit/settings dialog; kept when the list is rebuilt
    this._misses = 0; // consecutive "not configured" answers (the entry reloads for a second after a save)
    this._timer = null;
    this._drag = null;
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._refresh();
  }

  set narrow(_) {}
  set panel(_) {}
  set route(_) {}

  connectedCallback() {
    this._render();
    this._timer = setInterval(() => this._refresh(), 3000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  get _lang() {
    return (this._hass && this._hass.language) || "en";
  }

  get _t() {
    const lang = (this._hass && (this._hass.language || "en")).slice(0, 2);
    return T[lang] || T.en;
  }

  async _call(msg) {
    return this._hass.callWS(msg);
  }

  async _refresh() {
    if (!this._hass || this._busy) return;
    try {
      this._state = await this._call({ type: "solarprio/state" });
      this._notConfigured = false;
      this._misses = 0;
    } catch (err) {
      if (!(err && err.code === "not_configured")) return;
      // right after a save the entry reloads and answers "not configured" for a moment: wait before saying so
      if (++this._misses < 4 && this._state) return;
      this._notConfigured = true;
    }
    if (!this._busy) this._render();
  }

  _toast(message, ok = false) {
    // Home Assistant's own notification bar
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message, duration: ok ? 6000 : 10000 }, bubbles: true, composed: true }),
    );
  }

  // ---- actions -------------------------------------------------------

  async _commitOrder(ids) {
    const previous = this._state;
    this._state = {
      ...previous,
      devices: ids.map((id, i) => ({ ...previous.devices.find((d) => d.id === id), priority: i + 1 })),
    };
    this._busy = true;
    this._render();
    let failed = false;
    try {
      this._state = await this._call({ type: "solarprio/reorder", ids });
    } catch (_) {
      this._state = previous;
      failed = true;
    } finally {
      this._busy = false;
      this._render();
    }
    if (failed) this._toast(this._t.error);
  }

  _move(index, delta) {
    const ids = this._state.devices.map((d) => d.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    this._commitOrder(ids).then(() => {
      const handle = this.shadowRoot.querySelector(`li[data-id="${CSS.escape(ids[target])}"] .${delta < 0 ? "up" : "down"}`);
      if (handle && !handle.disabled) handle.focus();
    });
  }

  async _setEnabled(deviceId, enabled) {
    this._busy = true;
    let failed = false;
    try {
      this._state = await this._call({ type: "solarprio/set_device_enabled", device_id: deviceId, enabled });
    } catch (_) {
      failed = true;
    } finally {
      this._busy = false;
      this._render();
    }
    if (failed) this._toast(this._t.error);
  }

  async _setRouting(enabled) {
    this._busy = true;
    let failed = false;
    try {
      this._state = await this._call({ type: "solarprio/set_routing", enabled });
    } catch (_) {
      failed = true;
    } finally {
      this._busy = false;
      this._render();
    }
    if (failed) this._toast(this._t.error);
  }

  // ---- drag and drop (pointer events: mouse and touch) ----------------

  _onHandleDown(ev, index) {
    if (ev.button !== undefined && ev.button !== 0) return;
    const list = this.shadowRoot.querySelector("ul");
    const rows = [...list.querySelectorAll("li.row")];
    const row = rows[index];
    const rects = rows.map((r) => r.getBoundingClientRect());
    ev.currentTarget.setPointerCapture(ev.pointerId);
    row.classList.add("dragging");
    this._busy = true;
    this._drag = { index, target: index, startY: ev.clientY, rows, rects, height: rects[index].height + 8 };
    ev.preventDefault();
  }

  _onHandleMove(ev) {
    const d = this._drag;
    if (!d) return;
    const dy = ev.clientY - d.startY;
    d.rows[d.index].style.transform = `translateY(${dy}px)`;
    const center = d.rects[d.index].top + d.rects[d.index].height / 2 + dy;
    let target = d.index;
    d.rects.forEach((rect, i) => {
      const mid = rect.top + rect.height / 2;
      if (i < d.index && center < mid) target = Math.min(target, i);
      if (i > d.index && center > mid) target = Math.max(target, i);
    });
    d.target = target;
    d.rows.forEach((row, i) => {
      if (i === d.index) return;
      let shift = 0;
      if (target > d.index && i > d.index && i <= target) shift = -d.height;
      if (target < d.index && i < d.index && i >= target) shift = d.height;
      row.style.transform = shift ? `translateY(${shift}px)` : "";
    });
  }

  _onHandleUp(ev) {
    const d = this._drag;
    if (!d) return;
    this._drag = null;
    d.rows.forEach((r) => {
      r.style.transform = "";
      r.classList.remove("dragging");
    });
    this._busy = false;
    if (d.target !== d.index) {
      const ids = this._state.devices.map((x) => x.id);
      const [moved] = ids.splice(d.index, 1);
      ids.splice(d.target, 0, moved);
      this._commitOrder(ids);
    } else {
      this._render();
    }
  }

  // ---- rendering ------------------------------------------------------

  _render() {
    const t = this._t;
    const s = this._state;
    const key = JSON.stringify([
      t.title,
      this._notConfigured,
      s && s.devices.map((d) => [d.id, d.name, d.entity_id, d.power_w]),
    ]);
    if (key === this._key && this.shadowRoot.querySelector(".wrap")) {
      this._patch();
      return;
    }
    this._key = key;
    this._build();
  }

  _build() {
    const t = this._t;
    const s = this._state;
    const root = this.shadowRoot;
    let body;

    if (this._notConfigured) {
      body = `<ha-card><div class="empty">${t.notConfigured}</div></ha-card>`;
    } else if (!s) {
      body = "";
    } else {
      const rows = s.devices
        .map(
          (d, i) => `
          <li class="row" data-id="${esc(d.id)}" data-index="${i}">
            <button class="handle" data-index="${i}" aria-label="${t.drag}" title="${t.drag}">${GRIP}</button>
            <div class="rank">${i + 1}</div>
            <div class="info">
              <div class="name">${esc(d.name)}</div>
              <div class="sub"></div>
              <div class="bar"><div></div></div>
            </div>
            <div class="power"></div>
            <div class="arrows">
              <ha-icon-button class="up" data-index="${i}" data-path="${CHEVRON_UP}" label="${t.up}" title="${t.up}" ${i === 0 ? "disabled" : ""}></ha-icon-button>
              <ha-icon-button class="down" data-index="${i}" data-path="${CHEVRON_DOWN}" label="${t.down}" title="${t.down}" ${i === s.devices.length - 1 ? "disabled" : ""}></ha-icon-button>
            </div>
            <ha-icon-button class="edit" data-index="${i}" data-path="${MDI_PENCIL}" label="${t.edit} ${esc(d.name)}" title="${t.edit}"></ha-icon-button>
            <ha-icon-button class="remove" data-index="${i}" data-path="${MDI_DELETE}" label="${t.remove} ${esc(d.name)}" title="${t.remove}"></ha-icon-button>
            <ha-switch class="dev-enabled" data-id="${esc(d.id)}" aria-label="${t.enable} ${esc(d.name)}"></ha-switch>
          </li>`,
        )
        .join("");
      body = `
        <ha-card><div class="card-content">
          <div class="summary">
            <div><div class="label">${t.available}</div><div class="value" id="available"></div></div>
            <div><div class="label">${t.routed}</div><div class="value" id="routed"></div></div>
            <div><div class="label">${t.routing}</div><ha-switch id="routing" aria-label="${t.routing}"></ha-switch></div>
          </div>
          <div class="status" id="status"></div>
        </div></ha-card>
        <p class="hint">${t.hint}</p>
        ${s.devices.length ? `<ul>${rows}</ul>` : `<ha-card><div class="empty">${t.empty}</div></ha-card>`}`;
    }

    const actions =
      s && !this._notConfigured
        ? `<ha-button appearance="outlined" id="btn-settings">${t.settingsBtn}</ha-button><ha-button appearance="filled" id="btn-add">${t.add}</ha-button>`
        : "";
    root.innerHTML = `<style>${STYLE}</style><div class="wrap"><header><h1>${t.title}</h1>${actions}</header>${body}</div>`;
    root.querySelectorAll("ha-icon-button[data-path]").forEach((b) => (b.path = b.dataset.path));
    if (this._dialogEl) root.appendChild(this._dialogEl); // a dialog stays open when the list behind it is rebuilt
    this._bind();
    this._patch();
  }

  /** Update values in place: no DOM replacement, so hover, focus and drags are never disturbed. */
  _patch() {
    const s = this._state;
    const root = this.shadowRoot;
    if (!s || this._notConfigured) return;
    const t = this._t;
    const set = (el, text) => {
      if (el && el.textContent !== text) el.textContent = text;
    };
    set(root.getElementById("available"), fmtW(s.available_w));
    set(root.getElementById("routed"), fmtW(s.routed_w));
    const status = root.getElementById("status");
    const label = t.status[s.status] || s.status;
    if (status.firstChild && status.firstChild.nodeType === 3) {
      if (status.firstChild.textContent !== label) status.firstChild.textContent = label;
    } else {
      status.insertBefore(document.createTextNode(label), status.firstChild);
    }
    status.classList.toggle("bad", s.status.startsWith("measurement_lost"));
    let detail = status.querySelector(".detail");
    if (s.detail) {
      if (!detail) {
        detail = document.createElement("span");
        detail.className = "detail";
        status.appendChild(detail);
      }
      if (detail.textContent !== s.detail) detail.textContent = s.detail;
    } else if (detail) {
      detail.remove();
    }
    let hint = status.querySelector(".hint2");
    if (s.detail && s.detail.includes("has not reported for")) {
      if (!hint) {
        hint = document.createElement("span");
        hint.className = "hint2";
        status.appendChild(hint);
      }
      if (hint.textContent !== t.staleHint) hint.textContent = t.staleHint;
    } else if (hint) {
      hint.remove();
    }
    const routing = root.getElementById("routing");
    if (routing.checked !== s.routing_enabled) routing.checked = s.routing_enabled;

    // rows are in the same order as s.devices (guaranteed by the structure key)
    root.querySelectorAll("li.row").forEach((row, i) => {
      const d = s.devices[i];
      const on = d.cmd_w > 0;
      row.classList.toggle("off", !d.enabled);
      const parts = [d.entity_id, d.enabled ? (on ? t.on : t.off) : t.disabled];
      if (d.connected === false) parts.push(t.unplugged);
      if (d.temperature_c != null) parts.push(`${Number(d.temperature_c).toFixed(1)} °C`);
      if (d.mode && t.modes[d.mode]) parts.push(t.modes[d.mode]);
      if (d.offpeak) parts.push(t.offpeak[d.offpeak]);
      if (d.current_a > 0) parts.push(`${d.current_a} A`);
      if (d.soc != null) parts.push(`${t.soc} ${Math.round(d.soc)} %`);
      parts.push(`${t.max} ${fmtW(d.power_w)}`);
      set(row.querySelector(".sub"), parts.join(" · "));
      const pct = Math.max(0, Math.min(100, (d.cmd_w / d.power_w) * 100));
      row.querySelector(".bar > div").style.width = `${pct}%`;
      set(row.querySelector(".power"), fmtW(d.cmd_w));
      const box = row.querySelector(".dev-enabled");
      if (box.checked !== d.enabled) box.checked = d.enabled;
    });
  }

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll(".handle").forEach((h) => {
      const index = Number(h.dataset.index);
      h.addEventListener("pointerdown", (e) => this._onHandleDown(e, index));
      h.addEventListener("pointermove", (e) => this._onHandleMove(e));
      h.addEventListener("pointerup", (e) => this._onHandleUp(e));
      h.addEventListener("pointercancel", (e) => this._onHandleUp(e));
      h.addEventListener("keydown", (e) => {
        if (e.key === "ArrowUp") { e.preventDefault(); this._move(index, -1); }
        if (e.key === "ArrowDown") { e.preventDefault(); this._move(index, 1); }
      });
    });
    root.querySelectorAll(".up").forEach((b) => b.addEventListener("click", () => !b.disabled && this._move(Number(b.dataset.index), -1)));
    root.querySelectorAll(".down").forEach((b) => b.addEventListener("click", () => !b.disabled && this._move(Number(b.dataset.index), 1)));
    root.querySelectorAll(".dev-enabled").forEach((c) => c.addEventListener("change", () => this._setEnabled(c.dataset.id, c.checked)));
    const routing = root.getElementById("routing");
    if (routing) routing.addEventListener("change", () => this._setRouting(routing.checked));
    const add = root.getElementById("btn-add");
    if (add) add.addEventListener("click", () => this._openAdd());
    const settings = root.getElementById("btn-settings");
    if (settings) settings.addEventListener("click", () => this._openSettings());
    root.querySelectorAll(".edit").forEach((b) =>
      b.addEventListener("click", () => {
        const d = this._state.devices[Number(b.dataset.index)];
        this._openForm(d.kind, d.id);
      }),
    );
    root.querySelectorAll(".remove").forEach((b) =>
      b.addEventListener("click", () => this._confirmRemove(this._state.devices[Number(b.dataset.index)])),
    );
  }

  // ---- dialogs: add, edit, remove, settings (Home Assistant's own components) --------

  _openDialog(title) {
    this._closeDialog(false);
    const dlg = document.createElement("ha-dialog");
    dlg.heading = title;
    dlg.scrimClickAction = ""; // a click outside must not lose what was typed
    dlg.open = true;
    dlg.addEventListener("closed", (ev) => {
      if (ev.target !== dlg || this._dialogEl !== dlg) return; // Escape or the close button
      this._dialogEl = null;
      dlg.remove();
      if (this._returnFocus && this._returnFocus.isConnected) this._returnFocus.focus();
    });
    this._returnFocus = this.shadowRoot.activeElement;
    this._dialogEl = dlg;
    this.shadowRoot.appendChild(dlg);
    return dlg;
  }

  _closeDialog(restoreFocus = true) {
    const dlg = this._dialogEl;
    this._dialogEl = null;
    if (dlg) {
      dlg.open = false;
      dlg.remove();
    }
    if (restoreFocus && this._returnFocus && this._returnFocus.isConnected) this._returnFocus.focus();
  }

  _button(text, { slot, appearance, variant, onClick }) {
    const b = document.createElement("ha-button");
    if (slot) b.slot = slot;
    if (appearance) b.setAttribute("appearance", appearance);
    if (variant) b.setAttribute("variant", variant);
    b.textContent = text;
    b.addEventListener("click", onClick);
    return b;
  }

  _afterChange(message) {
    this._toast(message, true);
    [1500, 4000].forEach((ms) => setTimeout(() => this._refresh(), ms)); // the entry reloads: look again shortly
  }

  async _openAdd() {
    const t = this._t;
    let form;
    try {
      form = await this._call({ type: "solarprio/device_form", kind: "on_off", language: this._lang });
    } catch (_) {
      this._toast(t.loadFailed);
      return;
    }
    const dlg = this._openDialog(t.addTitle);
    const box = document.createElement("div");
    const hint = document.createElement("p");
    hint.className = "dialog-hint";
    hint.textContent = t.chooseType;
    box.appendChild(hint);
    const group = (title, items) => {
      if (!items.length) return;
      if (title) {
        const h = document.createElement("div");
        h.className = "dialog-title";
        h.textContent = title;
        box.appendChild(h);
      }
      const list = document.createElement("div");
      list.className = "choices";
      items.forEach((b) => list.appendChild(b));
      box.appendChild(list);
    };
    const presets = (form.presets || []).map((p) => {
      // a brand model says honestly how far it was checked
      const status = p.status === "verified" || p.brand === "Generic" ? "" : ` · ${t.profileStatus[p.status] || p.status}`;
      const b = this._button(p.label + status, { appearance: "filled", onClick: () => this._openForm(p.kind, null, p.id) });
      if (p.notes) b.title = p.notes;
      return b;
    });
    const kinds = Object.entries(form.kinds).map(([k, label]) =>
      this._button(label, { appearance: "outlined", onClick: () => this._openForm(k, null) }),
    );
    group(presets.length ? t.presetsTitle : "", presets);
    group(presets.length ? t.otherTypes : "", kinds);
    dlg.appendChild(box);
    dlg.appendChild(this._button(t.cancel, { slot: "secondaryAction", appearance: "plain", onClick: () => this._closeDialog() }));
  }

  async _openForm(kind, deviceId, preset = null) {
    const t = this._t;
    let form;
    try {
      form = await this._call({ type: "solarprio/device_form", kind, device_id: deviceId || undefined, preset: preset || undefined, language: this._lang });
    } catch (_) {
      this._toast(t.loadFailed);
      return;
    }
    this._formDialog({
      title: `${deviceId ? t.editTitle : t.addTitle} · ${form.kinds[kind] || kind}`,
      fields: form.fields,
      values: deviceId || preset ? form.values : {}, // a model brings its values; a plain addition starts from the defaults
      save: (values) => this._call({ type: "solarprio/device_save", kind, device_id: deviceId || undefined, values }),
      done: t.saved,
    });
  }

  async _openSettings() {
    const t = this._t;
    let form;
    try {
      form = await this._call({ type: "solarprio/settings_form", language: this._lang });
    } catch (_) {
      this._toast(t.loadFailed);
      return;
    }
    this._formDialog({
      title: t.settingsTitle,
      fields: form.fields,
      values: form.values,
      save: (values) => this._call({ type: "solarprio/settings_save", values }),
      done: t.saved,
    });
  }

  _confirmRemove(device) {
    const t = this._t;
    const dlg = this._openDialog(t.remove);
    const p = document.createElement("p");
    p.textContent = t.confirmRemove.replace("{name}", device.name);
    dlg.appendChild(p);
    dlg.appendChild(this._button(t.cancel, { slot: "secondaryAction", appearance: "plain", onClick: () => this._closeDialog() }));
    dlg.appendChild(
      this._button(t.remove, {
        slot: "primaryAction",
        appearance: "filled",
        variant: "danger",
        onClick: async () => {
          try {
            await this._call({ type: "solarprio/device_remove", device_id: device.id });
          } catch (_) {
            this._toast(t.error);
            return;
          }
          this._closeDialog(false);
          this._afterChange(t.removed);
        },
      }),
    );
  }

  /** A form built from the field definitions of the server, drawn by Home Assistant's own form (ha-form). */
  _formDialog({ title, fields, values, save, done }) {
    const t = this._t;
    const dlg = this._openDialog(title);
    const selectorFor = (f) => {
      if (f.type === "entity") return { entity: { domain: f.domains } };
      if (f.type === "number") {
        const n = { step: "any", mode: "box" };
        if (f.min != null) n.min = f.min;
        if (f.max != null) n.max = f.max;
        if (f.unit) n.unit_of_measurement = f.unit;
        return { number: n };
      }
      if (f.type === "select") return { select: { mode: "dropdown", options: f.options.map((o) => ({ value: o, label: t.opt[o] || o })) } };
      if (f.type === "boolean") return { boolean: {} };
      return { text: {} };
    };
    const needed = (f) => f.required && (f.default === null || f.default === undefined || f.default === "");
    let current = {};
    fields.forEach((f) => {
      const v = values[f.name] ?? f.default;
      if (v !== undefined && v !== null && v !== "") current[f.name] = v;
    });
    let errors = {};
    let openAdvanced = false;
    const visible = (f, d) => !f.show_if || String(d[f.show_if[0]]) === f.show_if[1];
    const schemaFor = (d) => {
      const item = (f) => ({ name: f.name, required: needed(f), selector: selectorFor(f) });
      const schema = fields.filter((f) => !f.advanced && visible(f, d)).map(item);
      const advanced = fields.filter((f) => f.advanced && visible(f, d)).map(item);
      if (advanced.length) {
        const group = { type: "expandable", name: "advanced", title: t.advanced, flatten: true, schema: advanced };
        if (openAdvanced) group.expanded = true;
        schema.push(group);
      }
      return schema;
    };
    const shapeOf = (d) => fields.filter((f) => visible(f, d)).map((f) => f.name).join(",");

    const alert = document.createElement("ha-alert");
    alert.setAttribute("alert-type", "error");
    alert.hidden = true;
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.data = current;
    form.schema = schemaFor(current);
    form.computeLabel = (s) => (fields.find((f) => f.name === s.name) || {}).label || s.name;
    form.computeHelper = (s) => (fields.find((f) => f.name === s.name) || {}).description || "";
    form.computeError = (error) => error; // the form passes the message of the field, then its schema
    let shape = shapeOf(current);
    form.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      current = ev.detail.value || {};
      form.data = current;
      if (shapeOf(current) !== shape) {
        shape = shapeOf(current);
        form.schema = schemaFor(current);
      }
    });
    dlg.appendChild(alert);
    dlg.appendChild(form);
    dlg.appendChild(this._button(t.cancel, { slot: "secondaryAction", appearance: "plain", onClick: () => this._closeDialog() }));
    const saveBtn = this._button(t.save, { slot: "primaryAction", appearance: "filled", onClick: () => submit() });
    dlg.appendChild(saveBtn);

    const fail = (field, message) => {
      errors[field] = message;
      const f = fields.find((x) => x.name === field);
      if (f && f.advanced) openAdvanced = true;
    };
    const submit = async () => {
      errors = {};
      alert.hidden = true;
      const out = {};
      fields.forEach((f) => {
        if (!visible(f, current)) return;
        const v = current[f.name];
        const empty = v === undefined || v === null || v === "" || (typeof v === "number" && Number.isNaN(v));
        if (empty) {
          if (needed(f)) fail(f.name, t.required);
          return;
        }
        out[f.name] = typeof v === "string" ? v.trim() : v;
      });
      form.error = { ...errors };
      if (openAdvanced) form.schema = schemaFor(current);
      if (Object.keys(errors).length) return;
      saveBtn.disabled = true;
      this._busy = true;
      let result;
      try {
        result = await save(out);
      } catch (err) {
        const field = err && err.code === "invalid_settings" && fields.find((f) => f.name === err.message);
        // always in the alert at the top: a field inside the folded advanced section could not show its own message
        alert.textContent = field
          ? `${t.saveFailed}: ${t.invalid} · ${field.label}`
          : `${t.saveFailed}: ${(err && err.message) || (err && err.code) || ""}`;
        alert.hidden = false;
        if (field && field.advanced) {
          openAdvanced = true;
          form.schema = schemaFor(current);
        }
        saveBtn.disabled = false;
        return;
      } finally {
        this._busy = false;
      }
      this._closeDialog(false);
      this._afterChange(done);
      ((result && result.warnings) || []).forEach((w) => t.warnings[w] && this._toast(t.warnings[w]));
    };
  }
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// the module can be evaluated twice in one page (an update while the page is open): defining the element again would throw
if (!customElements.get("solarprio-panel")) customElements.define("solarprio-panel", SolarPrioPanel);
