/* solarprio sidebar panel: drag-and-drop priorities. No build step, no dependencies. */

const T = {
  en: {
    title: "Solar routing",
    routing: "Routing",
    available: "Available",
    routed: "Routed",
    hint: "Drag the handle (or use the arrows) to set the order. The top device is served first.",
    empty: "No device yet. Add some in Settings > Devices & services > solarprio > Configure.",
    on: "on",
    off: "off",
    max: "max",
    soc: "SoC",
    unplugged: "unplugged",
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
    empty: "Aucun appareil. Ajoutez-en dans Paramètres > Appareils et services > solarprio > Configurer.",
    on: "marche",
    off: "arrêt",
    max: "max",
    soc: "Niveau",
    unplugged: "débranché",
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
  @media (max-width: 520px) { .power { display: none; } .summary .value { font-size: 20px; } }
`;

const GRIP =
  '<svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 3h2v2H9V3m4 0h2v2h-2V3M9 7h2v2H9V7m4 0h2v2h-2V7m-4 4h2v2H9v-2m4 0h2v2h-2v-2m-4 4h2v2H9v-2m4 0h2v2h-2v-2m-4 4h2v2H9v-2m4 0h2v2h-2v-2Z"/></svg>';

const fmtW = (w) => (w == null ? "-" : `${Math.round(w)} W`);

class SolarPrioPanel extends HTMLElement {
  constructor() {
    super();
    this._state = null;
    this._key = null;
    this._notConfigured = false;
    this._busy = false; // saving or dragging: do not overwrite local order with a poll
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
    } catch (err) {
      if (err && err.code === "not_configured") this._notConfigured = true;
      else return;
    }
    if (!this._busy) this._render();
  }

  _toast(message) {
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "alert");
    el.textContent = message;
    this.shadowRoot.appendChild(el);
    setTimeout(() => el.remove(), 4000);
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

    root.innerHTML = `<style>${STYLE}</style><div class="wrap"><header><h1>${t.title}</h1></header>${body}</div>`;
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
    set(status, t.status[s.status] || s.status);
    status.classList.toggle("bad", s.status.startsWith("measurement_lost"));
    const routing = root.getElementById("routing");
    if (routing.checked !== s.routing_enabled) routing.checked = s.routing_enabled;

    // rows are in the same order as s.devices (guaranteed by the structure key)
    root.querySelectorAll("li.row").forEach((row, i) => {
      const d = s.devices[i];
      const on = d.cmd_w > 0;
      row.classList.toggle("off", !d.enabled);
      const parts = [d.entity_id, d.enabled ? (on ? t.on : t.off) : t.disabled];
      if (d.connected === false) parts.push(t.unplugged);
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
  }
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

customElements.define("solarprio-panel", SolarPrioPanel);
