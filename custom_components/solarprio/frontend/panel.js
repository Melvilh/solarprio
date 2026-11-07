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
  :host { display: block; background: var(--primary-background-color); color: var(--primary-text-color);
          min-height: 100%; font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .wrap { max-width: 760px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  h1 { font-size: 22px; font-weight: 400; margin: 0; flex: 1; }
  .card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.2)); padding: 16px; margin-bottom: 16px; }
  .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: center; }
  .summary .label { font-size: 12px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .04em; }
  .summary .value { font-size: 24px; margin-top: 4px; }
  .status { font-size: 14px; color: var(--secondary-text-color); margin-top: 12px; text-align: center; }
  .status.bad { color: var(--error-color, #db4437); }
  .hint { color: var(--secondary-text-color); font-size: 14px; margin: 0 0 12px; }
  ul { list-style: none; margin: 0; padding: 0; position: relative; }
  li.row { display: flex; align-items: center; gap: 12px; padding: 12px; margin-bottom: 8px;
           background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #ddd);
           border-radius: 10px; transition: transform .15s ease, box-shadow .15s ease; }
  li.row.dragging { transition: none; z-index: 2; box-shadow: 0 6px 16px rgba(0,0,0,.3); position: relative; }
  li.row.off { opacity: .55; }
  .handle { cursor: grab; touch-action: none; padding: 8px 4px; border: 0; background: none; color: var(--secondary-text-color); display: flex; }
  .handle:active { cursor: grabbing; }
  .rank { min-width: 28px; height: 28px; border-radius: 50%; background: var(--primary-color); color: var(--text-primary-color, #fff);
          display: flex; align-items: center; justify-content: center; font-weight: 500; font-size: 14px; }
  .info { flex: 1; min-width: 0; }
  .name { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar { height: 6px; border-radius: 3px; background: var(--divider-color, #ddd); margin-top: 6px; overflow: hidden; }
  .bar > div { height: 100%; background: var(--primary-color); transition: width .3s ease; }
  .power { font-size: 13px; min-width: 76px; text-align: right; color: var(--secondary-text-color); }
  .arrows { display: flex; flex-direction: column; }
  button.icon { border: 0; background: none; color: var(--secondary-text-color); cursor: pointer; padding: 2px 6px; font-size: 14px; line-height: 1; }
  button.icon:disabled { opacity: .25; cursor: default; }
  button.icon:focus-visible, .handle:focus-visible { outline: 2px solid var(--primary-color); border-radius: 4px; }
  label.switch { position: relative; width: 38px; height: 22px; flex: none; }
  label.switch input { opacity: 0; width: 100%; height: 100%; margin: 0; position: absolute; cursor: pointer; z-index: 1; }
  label.switch span { position: absolute; inset: 0; border-radius: 11px; background: var(--disabled-text-color, #bbb); transition: background .2s; }
  label.switch span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: transform .2s; }
  label.switch input:checked + span { background: var(--primary-color); }
  label.switch input:checked + span::after { transform: translateX(16px); }
  label.switch input:focus-visible + span { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); background: var(--error-color, #db4437);
           color: #fff; padding: 10px 16px; border-radius: 8px; font-size: 14px; }
  .empty { text-align: center; color: var(--secondary-text-color); padding: 24px 8px; }
  .status .detail { display: block; font-size: 12px; margin-top: 4px; word-break: break-all; }
  .toast.ok { background: var(--success-color, #2e7d32); }
  header .btn { white-space: nowrap; }
  button.btn { border: 1px solid var(--divider-color, #bbb); background: var(--card-background-color, #fff); color: var(--primary-text-color);
               border-radius: 8px; padding: 8px 14px; font-size: 14px; cursor: pointer; font-family: inherit; }
  button.btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button.btn.danger { background: var(--error-color, #db4437); color: #fff; border-color: var(--error-color, #db4437); }
  button.btn:disabled { opacity: .5; cursor: default; }
  button.btn:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  button.icon svg { display: block; }
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: flex-start; justify-content: center;
             padding: 24px 12px; overflow: auto; z-index: 10; }
  .dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 12px; padding: 20px;
            width: 100%; max-width: 560px; box-sizing: border-box; box-shadow: 0 8px 32px rgba(0,0,0,.4); }
  .dialog h2 { margin: 0 0 12px; font-size: 20px; font-weight: 400; }
  .dialog button.kind { display: block; width: 100%; text-align: left; margin-bottom: 8px; padding: 12px 14px; }
  .field { margin-bottom: 14px; }
  .field[hidden] { display: none; }
  .field .lab { display: block; font-size: 13px; color: var(--secondary-text-color); margin-bottom: 4px; }
  .field input[type=text], .field input[type=number], .field select {
    width: 100%; box-sizing: border-box; padding: 9px 10px; font-size: 15px; font-family: inherit; color: var(--primary-text-color);
    background: var(--secondary-background-color, #f5f5f5); border: 1px solid var(--divider-color, #bbb); border-radius: 6px; }
  .field input:focus-visible, .field select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
  .field .help { font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .field .unit { font-size: 12px; color: var(--secondary-text-color); margin-left: 6px; }
  .field.invalid input, .field.invalid select { border-color: var(--error-color, #db4437); }
  .field .err { color: var(--error-color, #db4437); font-size: 12px; margin-top: 4px; }
  .form-error { color: var(--error-color, #db4437); font-size: 14px; min-height: 18px; margin: 4px 0 8px; word-break: break-word; }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
  @media (max-width: 520px) { .power { display: none; } .summary .value { font-size: 20px; } header { flex-wrap: wrap; } }
`;

const GRIP =
  '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 3h2v2H9V3m4 0h2v2h-2V3M9 7h2v2H9V7m4 0h2v2h-2V7m-4 4h2v2H9v-2m4 0h2v2h-2v-2m-4 4h2v2H9v-2m4 0h2v2h-2v-2m-4 4h2v2H9v-2m4 0h2v2h-2v-2Z"/></svg>';

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
    const el = document.createElement("div");
    el.className = ok ? "toast ok" : "toast";
    el.setAttribute("role", "alert");
    el.textContent = message;
    this.shadowRoot.appendChild(el);
    setTimeout(() => el.remove(), ok ? 6000 : 4000);
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
      body = `<div class="card empty">${t.notConfigured}</div>`;
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
              <button class="icon up" data-index="${i}" aria-label="${t.up}" title="${t.up}" ${i === 0 ? "disabled" : ""}>▲</button>
              <button class="icon down" data-index="${i}" aria-label="${t.down}" title="${t.down}" ${i === s.devices.length - 1 ? "disabled" : ""}>▼</button>
            </div>
            <button class="icon edit" data-index="${i}" aria-label="${t.edit} ${esc(d.name)}" title="${t.edit}">${PENCIL}</button>
            <button class="icon remove" data-index="${i}" aria-label="${t.remove} ${esc(d.name)}" title="${t.remove}">${TRASH}</button>
            <label class="switch"><input type="checkbox" class="dev-enabled" data-id="${esc(d.id)}" aria-label="${t.enable} ${esc(d.name)}"><span></span></label>
          </li>`,
        )
        .join("");
      body = `
        <div class="card">
          <div class="summary">
            <div><div class="label">${t.available}</div><div class="value" id="available"></div></div>
            <div><div class="label">${t.routed}</div><div class="value" id="routed"></div></div>
            <div><div class="label">${t.routing}</div>
              <label class="switch" style="display:inline-block;margin-top:10px"><input type="checkbox" id="routing" aria-label="${t.routing}"><span></span></label></div>
          </div>
          <div class="status" id="status"></div>
        </div>
        <p class="hint">${t.hint}</p>
        ${s.devices.length ? `<ul>${rows}</ul>` : `<div class="card empty">${t.empty}</div>`}`;
    }

    const actions =
      s && !this._notConfigured
        ? `<button class="btn" id="btn-settings">${t.settingsBtn}</button><button class="btn primary" id="btn-add">${t.add}</button>`
        : "";
    root.innerHTML = `<style>${STYLE}</style><div class="wrap"><header><h1>${t.title}</h1>${actions}</header>${body}</div>`;
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
    const routing = root.getElementById("routing");
    if (routing.checked !== s.routing_enabled) routing.checked = s.routing_enabled;

    // rows are in the same order as s.devices (guaranteed by the structure key)
    root.querySelectorAll("li.row").forEach((row, i) => {
      const d = s.devices[i];
      const on = d.cmd_w > 0;
      row.classList.toggle("off", !d.enabled);
      const parts = [d.entity_id, d.enabled ? (on ? t.on : t.off) : t.disabled];
      if (d.connected === false) parts.push(t.unplugged);
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
    root.querySelectorAll("button.up").forEach((b) => b.addEventListener("click", () => this._move(Number(b.dataset.index), -1)));
    root.querySelectorAll("button.down").forEach((b) => b.addEventListener("click", () => this._move(Number(b.dataset.index), 1)));
    root.querySelectorAll(".dev-enabled").forEach((c) => c.addEventListener("change", () => this._setEnabled(c.dataset.id, c.checked)));
    const routing = root.getElementById("routing");
    if (routing) routing.addEventListener("change", () => this._setRouting(routing.checked));
    const add = root.getElementById("btn-add");
    if (add) add.addEventListener("click", () => this._openAdd());
    const settings = root.getElementById("btn-settings");
    if (settings) settings.addEventListener("click", () => this._openSettings());
    root.querySelectorAll("button.edit").forEach((b) =>
      b.addEventListener("click", () => {
        const d = this._state.devices[Number(b.dataset.index)];
        this._openForm(d.kind, d.id);
      }),
    );
    root.querySelectorAll("button.remove").forEach((b) =>
      b.addEventListener("click", () => this._confirmRemove(this._state.devices[Number(b.dataset.index)])),
    );
  }

  // ---- dialogs: add, edit, remove, settings -----------------------------

  _openDialog(title, bodyHtml) {
    this._closeDialog(false);
    const el = document.createElement("div");
    el.className = "overlay";
    el.innerHTML = `<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-title"><h2 id="dlg-title">${esc(title)}</h2>${bodyHtml}</div>`;
    el.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        this._closeDialog();
      }
    });
    this._returnFocus = this.shadowRoot.activeElement;
    this._dialogEl = el;
    this.shadowRoot.appendChild(el);
    return el;
  }

  _closeDialog(restoreFocus = true) {
    if (this._dialogEl) this._dialogEl.remove();
    this._dialogEl = null;
    if (restoreFocus && this._returnFocus && this._returnFocus.isConnected) this._returnFocus.focus();
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
    const kinds = Object.entries(form.kinds)
      .map(([k, label]) => `<button class="btn kind" data-kind="${esc(k)}">${esc(label)}</button>`)
      .join("");
    const el = this._openDialog(t.addTitle, `<p class="hint">${t.chooseType}</p>${kinds}<div class="actions"><button class="btn cancel">${t.cancel}</button></div>`);
    el.querySelectorAll(".kind").forEach((b) => b.addEventListener("click", () => this._openForm(b.dataset.kind, null)));
    el.querySelector(".cancel").addEventListener("click", () => this._closeDialog());
    el.querySelector(".kind").focus();
  }

  async _openForm(kind, deviceId) {
    const t = this._t;
    let form;
    try {
      form = await this._call({ type: "solarprio/device_form", kind, device_id: deviceId || undefined, language: this._lang });
    } catch (_) {
      this._toast(t.loadFailed);
      return;
    }
    this._formDialog({
      title: `${deviceId ? t.editTitle : t.addTitle} · ${form.kinds[kind] || kind}`,
      fields: form.fields,
      values: deviceId ? form.values : {},
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
    const el = this._openDialog(
      t.remove,
      `<p>${esc(t.confirmRemove.replace("{name}", device.name))}</p><div class="actions"><button class="btn cancel">${t.cancel}</button><button class="btn danger ok">${t.remove}</button></div>`,
    );
    el.querySelector(".cancel").addEventListener("click", () => this._closeDialog());
    el.querySelector(".ok").addEventListener("click", async () => {
      try {
        await this._call({ type: "solarprio/device_remove", device_id: device.id });
      } catch (_) {
        this._toast(t.error);
        return;
      }
      this._closeDialog(false);
      this._afterChange(t.removed);
    });
    el.querySelector(".cancel").focus();
  }

  /** A form generated from the field definitions of the server (the same ones as Home Assistant's own form). */
  _formDialog({ title, fields, values, save, done }) {
    const t = this._t;
    const entities = Object.keys((this._hass && this._hass.states) || {});
    const control = (f, v) => {
      const id = `f-${f.name}`;
      if (f.type === "select") {
        const options = f.options
          .map((o) => `<option value="${esc(o)}" ${String(v) === o ? "selected" : ""}>${esc(t.opt[o] || o)}</option>`)
          .join("");
        return `<select id="${id}">${options}</select>`;
      }
      if (f.type === "boolean") {
        return `<label class="switch" style="display:inline-block"><input type="checkbox" id="${id}" ${v ? "checked" : ""}><span></span></label>`;
      }
      if (f.type === "number") {
        const attrs = `${f.min != null ? ` min="${f.min}"` : ""}${f.max != null ? ` max="${f.max}"` : ""}`;
        return `<input type="number" step="any" id="${id}"${attrs} value="${esc(v ?? "")}">${f.unit ? `<span class="unit">${esc(f.unit)}</span>` : ""}`;
      }
      if (f.type === "entity") {
        const prefix = f.domains.map((d) => `${d}.`);
        const list = entities
          .filter((e) => prefix.some((p) => e.startsWith(p)))
          .sort()
          .map((e) => {
            const st = this._hass.states[e];
            const name = (st && st.attributes && st.attributes.friendly_name) || "";
            return `<option value="${esc(e)}" label="${esc(name)}"></option>`;
          })
          .join("");
        return `<input type="text" id="${id}" list="dl-${f.name}" autocomplete="off" spellcheck="false" placeholder="${esc(f.domains[0])}.…" value="${esc(v ?? "")}"><datalist id="dl-${f.name}">${list}</datalist>`;
      }
      return `<input type="text" id="${id}" autocomplete="off" value="${esc(v ?? "")}">`;
    };
    const rows = fields
      .map((f) => {
        const v = values[f.name] ?? f.default ?? "";
        const show = f.show_if ? ` data-show-name="${esc(f.show_if[0])}" data-show-value="${esc(f.show_if[1])}"` : "";
        return `<div class="field" data-field="${esc(f.name)}"${show}>
          <label class="lab" for="f-${esc(f.name)}">${esc(f.label)}${f.required ? " *" : ""}</label>
          ${control(f, v)}
          ${f.description ? `<div class="help">${esc(f.description)}</div>` : ""}
          <div class="err" role="alert"></div>
        </div>`;
      })
      .join("");
    const el = this._openDialog(
      title,
      `<form novalidate>${rows}<div class="form-error" role="alert"></div><div class="actions"><button type="button" class="btn cancel">${t.cancel}</button><button type="submit" class="btn primary">${t.save}</button></div></form>`,
    );
    const form = el.querySelector("form");
    const input = (name) => el.querySelector(`#f-${CSS.escape(name)}`);
    const wrap = (name) => el.querySelector(`[data-field="${CSS.escape(name)}"]`);
    const current = (name) => {
      const i = input(name);
      return i ? (i.type === "checkbox" ? i.checked : i.value) : undefined;
    };
    const visibility = () =>
      el.querySelectorAll("[data-show-name]").forEach((w) => {
        w.hidden = String(current(w.dataset.showName)) !== w.dataset.showValue;
      });
    form.addEventListener("change", visibility);
    visibility();

    el.querySelector(".cancel").addEventListener("click", () => this._closeDialog());
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const out = {};
      let first = null;
      fields.forEach((f) => {
        const w = wrap(f.name);
        w.classList.remove("invalid");
        w.querySelector(".err").textContent = "";
        if (w.hidden) return;
        const i = input(f.name);
        let v;
        if (f.type === "boolean") v = i.checked;
        else if (f.type === "number") v = i.value === "" ? undefined : Number(i.value);
        else v = i.value.trim();
        if ((v === undefined || v === "") && f.required) {
          w.classList.add("invalid");
          w.querySelector(".err").textContent = t.required;
          first = first || i;
        } else if (v !== undefined && v !== "") {
          out[f.name] = v;
        }
      });
      const errBox = el.querySelector(".form-error");
      errBox.textContent = "";
      if (first) {
        first.focus();
        return;
      }
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      this._busy = true;
      try {
        await save(out);
      } catch (err) {
        errBox.textContent = `${t.saveFailed}: ${(err && err.message) || (err && err.code) || ""}`;
        const bad = err && err.code === "invalid_settings" && wrap(err.message);
        if (bad) {
          bad.classList.add("invalid");
          input(err.message).focus();
        }
        button.disabled = false;
        return;
      } finally {
        this._busy = false;
      }
      this._closeDialog(false);
      this._afterChange(done);
    });
    const firstInput = el.querySelector("input, select");
    if (firstInput) firstInput.focus();
  }
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

customElements.define("solarprio-panel", SolarPrioPanel);
