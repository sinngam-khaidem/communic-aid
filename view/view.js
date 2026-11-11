// Communic-aid view. Draws what the core sends and reports what it sees.
// No rules live here: tiers come from the core, and every decision is made in Python.
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Icons from router-demo.html.
const SV = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICON = {
  blink: SV('<path d="M3 11c2.6 3.3 5.6 5 9 5s6.4-1.7 9-5"/><path d="M6.2 14.6 4.8 16.8M12 16v2.6M17.8 14.6l1.4 2.2"/>'),
  brows: SV('<path d="M5 6.2c4.2-2.6 9.8-2.6 14 0"/><path d="M3.5 14.5c2.4-3 5.3-4.5 8.5-4.5s6.1 1.5 8.5 4.5c-2.4 3-5.3 4.5-8.5 4.5s-6.1-1.5-8.5-4.5z"/><circle cx="12" cy="14.5" r="2.2"/>'),
  switch: SV('<path d="M12 2.5v4.2M9.9 4.9 12 7l2.1-2.1"/><path d="M6 16.5c0-3.4 2.7-6 6-6s6 2.6 6 6"/><rect x="3.5" y="16.5" width="17" height="4" rx="1.5"/>'),
  yes: SV('<path d="M4.5 4.5h15a1.5 1.5 0 0 1 1.5 1.5v8.5a1.5 1.5 0 0 1-1.5 1.5H10l-4.5 3.5V16H4.5A1.5 1.5 0 0 1 3 14.5V6a1.5 1.5 0 0 1 1.5-1.5z"/><path d="m8.5 10.3 2.4 2.4 4.6-4.6"/>'),
  undo: SV('<path d="M9 5 4.5 9.5 9 14"/><path d="M4.5 9.5H15a5 5 0 0 1 0 10h-3"/>'),
  redo: SV('<path d="M15 5l4.5 4.5L15 14"/><path d="M19.5 9.5H9a5 5 0 0 0 0 10h3"/>'),
  phone: SV('<path d="M7 3.5h2.6l1.3 3.7-1.9 1.2a11 11 0 0 0 6.6 6.6l1.2-1.9 3.7 1.3V17a2 2 0 0 1-2.2 2A15 15 0 0 1 5 5.7 2 2 0 0 1 7 3.5z"/>'),
  check: SV('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
  back: SV('<path d="M15 5l-7 7 7 7"/>'),
  up: SV('<path d="M6 15l6-6 6 6"/>'),
  down: SV('<path d="M6 9l6 6 6-6"/>'),
  chats: SV('<path d="M4.5 5h15a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19.5 16H10l-4.5 3.5V16h-1A1.5 1.5 0 0 1 3 14.5v-8A1.5 1.5 0 0 1 4.5 5z"/>'),
  settings: SV('<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>'),
  backspace: SV('<path d="M21 5H9l-6 7 6 7h12z"/><path d="M12 9l6 6M18 9l-6 6"/>'),
};
const NAMES = { blink: "Blink and hold", brows: "Raise eyebrows", yes: 'Say "yes"', switch: "Switch" };

let TIERS = {}, SIGNALS = [], INIT = {};
let state = null;
let ws = null, started = false;
const btn = new Map();          // action -> { m, at }: last button message, re-applied after every redraw
let checkPrompt = null;
const debug = { group: "", dwell: {}, choice: null, context: null };

// ---------- buttons ----------

const tierOf = (a) => TIERS[a.split(":")[0]] ?? 0;

function B(action, label, o = {}) {
  const inner = o.html ?? `${o.icon ? ICON[o.icon] : ""}${label ? `<span>${esc(label)}${o.sub ? `<span class="sub">${esc(o.sub)}</span>` : ""}</span>` : ""}`;
  return `<button class="t l${tierOf(action)} ${o.cls || ""}" data-action="${esc(action)}" tabindex="-1">` +
    `<i class="glow"></i><i class="fx"></i><span class="lb">${inner}</span><span class="cue"></span></button>`;
}

const elOf = (action) => document.querySelector(`[data-action="${CSS.escape(action)}"]`);

function setP(el, value, ms) {
  el.style.transition = ms ? `--p ${ms}ms linear, opacity .3s` : "none";
  if (!ms) getComputedStyle(el).getPropertyValue("--p");
  el.style.setProperty("--p", value);
}

function animateTo(el, from, to, ms) {
  setP(el, from, 0);
  requestAnimationFrame(() => setP(el, to, ms));
}

function applyButton(el, m, elapsed) {
  const cue = el.querySelector(".cue");
  switch (m.do) {
    case "fill": {
      const k = m.ms ? Math.min(1, elapsed / m.ms) : 1;
      animateTo(el, m.from + (1 - m.from) * k, 1, Math.max(0, m.ms - elapsed));
      el.classList.remove("locked", "fired");
      break;
    }
    case "drain": {
      const k = m.ms ? Math.min(1, elapsed / m.ms) : 1;
      animateTo(el, m.from * (1 - k), 0, Math.max(0, m.ms - elapsed));
      break;
    }
    case "hold":
      setP(el, m.from, 0);
      break;
    case "wait":
      setP(el, 0, 0);
      cue.innerHTML = ICON[m.check] || "";
      el.classList.add("await");
      el.style.transition = "none";
      el.style.setProperty("--amp", 1);
      requestAnimationFrame(() => {
        el.style.transition = `--amp ${Math.max(0, m.ms - elapsed)}ms linear`;
        el.style.setProperty("--amp", 0.15);
      });
      break;
    case "wrong":
      el.classList.add("await");
      cue.innerHTML = ICON[m.check] || "";
      el.classList.remove("nudge");
      void el.offsetWidth;
      el.classList.add("nudge");
      break;
    case "accept":
      el.classList.add("accept");
      cue.innerHTML = ICON.check;
      break;
    case "fired":
      setP(el, 0, 0);
      el.classList.remove("await", "nudge");
      el.classList.add("fired", "locked");
      setTimeout(() => el.classList.remove("fired", "accept"), 600);
      break;
    default:   // idle, timeout
      setP(el, 0, 0);
      el.classList.remove("await", "nudge", "accept", "fired", "locked");
  }
  updateGazeSize();
}

function onButton(m) {
  btn.set(m.action, { m, at: performance.now() });
  if (m.do === "wrong") sound("error");
  if (m.do === "accept") sound("tick");
  const el = elOf(m.action);
  if (el) applyButton(el, m, 0);
}

function reapplyButtons() {
  const now = performance.now();
  for (const [action, { m, at }] of btn) {
    const el = elOf(action);
    if (!el) continue;
    if (m.do === "fired" || m.do === "accept") el.classList.add("locked");
    else applyButton(el, m, now - at);
  }
}

function reportTargets() {
  requestAnimationFrame(() => {
    const targets = [...document.querySelectorAll("[data-action]")].map((el) => {
      const r = el.getBoundingClientRect();
      return { action: el.dataset.action, x: r.left, y: r.top, w: r.width, h: r.height };
    }).filter((t) => t.w > 0 && t.h > 0);
    send({ type: "targets", targets });
  });
}

// ---------- screens ----------

const chatOf = (id) => state.chats.find((c) => c.id === id);
const initial = (name) => esc(name.replace(/^Dr\.\s*/, "")[0]);
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

// The thread shows 4 messages at a time; scrolling moves this window.
function threadWindow(c) {
  const end = Math.max(0, c.messages.length - state.scroll);
  const start = Math.max(0, end - 4);
  return { shown: c.messages.slice(start, end), canUp: start > 0, canDown: state.scroll > 0 };
}

// Right sidebar on the thread: scroll buttons in a fixed place. When there is nothing to
// scroll, a faint outline keeps the place but is not a target.
function scrollBar() {
  if (state.screen !== "thread") return "";
  const { canUp, canDown } = threadWindow(chatOf(state.chat_id));
  const ghost = (icon) => `<div class="t ghost"><span class="lb">${ICON[icon]}</span></div>`;
  return (canUp ? B("scroll_up", "", { icon: "up" }) : ghost("up")) + (canDown ? B("scroll_down", "", { icon: "down" }) : ghost("down"));
}

// Send takes a quarter of the draft row and is always shown in the same place.
// With an empty draft it stays visible but faded and is not a target: sending nothing should never ask for a signal.
const sendOrSpace = () => (state.draft.trim() ? B("send", "Send", { cls: "w1" })
  : '<div class="t ghost w1"><span class="lb"><span>Send</span></span></div>');

const SCREENS = {
  landing() {
    const s = state;
    // Continue sits bottom right at a quarter of the width, like Send.
    const next = `<div class="row onb-next"><div class="w3"></div>${B("continue", "Continue", { cls: "w1" })}</div>`;
    if (s.landing === "calibrate") {
      const again = s.calib && s.calib.ok === false ? "Let's try that once more. Keep your head still and follow the dot." : "";
      return `<div class="onb-center"><h1>Let's set up your eyes</h1>
        <p class="onb-lead">Look at each pink dot until it moves. Keep your head still.</p>
        ${again ? `<p class="onb-lead">${again}</p>` : ""}</div>`;
    }
    if (s.landing === "about") {
      const opt = (kind, value, label, on) => B(`${kind}:${value}`, label, { cls: on ? "on" : "" });
      const groups = [
        ["Age", "age", [["under18", "Under 18"], ["18-30", "18 to 30"], ["31-50", "31 to 50"], ["over50", "Over 50"]], (v) => s.about.age === v],
        ["Condition", "disability", [["als", "ALS"], ["cp", "Cerebral palsy"], ["md", "Muscular dystrophy"], ["sci", "Spinal cord injury"], ["other", "Other"]], (v) => s.about.disability.includes(v)],
        ["Apps you use", "app", [["whatsapp", "WhatsApp"], ["gmail", "Gmail"], ["instagram", "Instagram"], ["youtube", "YouTube"]], (v) => s.about.app.includes(v)],
      ];
      const cols = Math.max(...groups.map((g) => g[2].length));   // one grid for all rows, so every answer is the same size
      const rows = groups.map(([label, kind, options, on]) => `<div class="onb-label">${label}</div>
        <div class="onb-opts" style="grid-template-columns: repeat(${cols}, 1fr)">${options.map(([v, l]) => opt(kind, v, l, on(v))).join("")}</div>`).join("");
      return `<div class="onb-head"><h1>About you</h1><p class="onb-lead">All optional. Look at an answer to pick it.</p></div>
        <div class="onb-form">${rows}</div>${next}`;
    }
    if (s.landing === "check") {
      return `<div class="onb-center"><p class="onb-kicker">Signal check</p>
        <p class="onb-prompt">${esc(checkPrompt ? checkPrompt.text : "Getting ready...")}</p></div>`;
    }
    const found = SIGNALS.map((k) => `<li class="${s.can_do[k] ? "yes" : "no"}"><span class="mark">${s.can_do[k] ? "✓" : "✗"}</span>${esc(NAMES[k])}${s.can_do[k] ? "" : '<span class="muted"> will not be asked</span>'}</li>`).join("");
    return `<div class="onb-center"><h1>All set</h1><ul class="onb-found">${found}</ul>
      <p class="onb-lead">You can change any of this in Settings.</p></div>${next}`;
  },

  chats() {
    const rows = state.chats.map((c) => {
      const last = c.messages[c.messages.length - 1];
      return B(`open:${c.id}`, null, { cls: "chatrow", html: `<span class="av">${initial(c.name)}</span><span><span class="nm">${esc(c.name)}</span><span class="sub">${esc(last ? last.text : "")}</span></span>` });
    }).join("");
    return `<h2>Chats</h2><div class="list">${rows}</div>`;
  },

  thread() {
    const c = chatOf(state.chat_id);
    const { shown } = threadWindow(c);
    const msgs = shown.map((m, i) => `<div class="msg ${m.from === "me" ? "me" : ""}">
        <div class="bubble"><span class="txt">${m.forwarded ? '<span class="fw">Forwarded</span>' : ""}${esc(m.text)}${m.reaction ? `<span class="re">${esc(m.reaction)}</span>` : ""}</span>
        ${i >= shown.length - 3 ? B(`more:${m.id}`, "More", { cls: "more" }) : ""}</div></div>`).join("");
    const draft = state.draft ? esc(state.draft) : '<span class="ph">Write a message</span>';
    return `<div class="head">${B("back", "Back", { icon: "back" })}<div class="who"><span class="av">${initial(c.name)}</span>${esc(c.name)}</div>${B("call", "Call", { icon: "phone" })}</div>
      <div class="thread"><div class="msgs">${msgs}</div></div>
      <div class="row">${B("compose", null, { html: `<span class="dtext">${draft}</span>`, cls: "w3" })}${sendOrSpace()}</div>`;
  },

  compose() {
    const s = state;
    const suggestions = s.draft ? s.predictions.map((w) => B(`predict:${w}`, w, { cls: "short" }))
      : s.quick.map((q, i) => B(`quick:${i}`, q, { cls: "short" }));
    let keys;
    if (s.settings.keyboard === "qwerty") {
      keys = `<div class="keys qwerty">${"qwertyuiopasdfghjklzxcvbnm".split("").map((k) => B(`key:${k}`, k.toUpperCase())).join("")}</div>`;
    } else if (s.kb_group) {
      keys = `<div class="keys letters" style="grid-template-columns: repeat(${s.kb_group.length + 1}, 1fr)">${s.kb_group.split("").map((k) => B(`key:${k}`, k.toUpperCase())).join("")}${B("groups", "Back", { icon: "back" })}</div>`;
    } else {
      keys = `<div class="keys">${s.kb_groups.map((g) => B(`group:${g}`, g.toUpperCase())).join("")}</div>`;
    }
    return `<div class="row"><div class="draft w3">${esc(s.draft)}<span class="caret"></span></div>${sendOrSpace()}</div>
      <div class="row" style="min-height:88px">${suggestions.join("")}</div>
      ${keys}
      <div class="row">${B("close_keyboard", "Close keyboard", { cls: "w1" })}${B("backspace", "Backspace", { icon: "backspace", cls: "w1" })}${B("space", "Space", { cls: "w2" })}</div>`;
  },

  actions() {
    const c = chatOf(state.chat_id);
    const m = c && c.messages.find((x) => x.id === state.selected);
    const text = `<div class="selected">${esc(m ? m.text : "")}</div>`;
    if (state.picker) {
      const others = state.chats.filter((x) => x.id !== state.chat_id);
      return `<h2>Forward to</h2>${text}<div class="list">${others.map((o) => B(`forward_to:${o.id}`, o.name)).join("")}</div>
        <div class="row">${B("close", "Cancel")}</div>`;
    }
    return `<h2>Message</h2>${text}<div class="grow"></div>
      <div class="row">${B("close", "Close")}${B("react", m && m.reaction ? "Remove ❤" : "React ❤")}${B("forward", "Forward")}${B("delete", "Delete")}</div>`;
  },

  call() {
    const call = state.call;
    const c = chatOf(call.chat_id);
    const status = call.connected ? `Connected ${mmss(call.seconds)}` : "Calling";
    return `<div class="calltop"><div><div class="av">${initial(c.name)}</div><div class="big">${esc(c.name)}</div>
      <p class="muted">${status}${call.muted ? " (muted)" : ""}</p></div></div>
      <div class="row">${B("mute", call.muted ? "Unmute" : "Mute")}${B("end_call", "End call", { icon: "phone" })}</div>`;
  },

  settings() {
    const st = state.settings;
    const toggles = SIGNALS.map((k) => B(`toggle:${k}`, null, { cls: `short ${st.enabled[k] ? "on" : "off"}`,
      html: `<span>${esc(NAMES[k])}<span class="sub">${st.enabled[k] ? "On" : "Off"}</span>${state.can_do[k] ? "" : '<span class="cant">not found</span>'}</span>` })).join("");
    const prefer = SIGNALS.filter((k) => st.enabled[k]).map((k) => B(`prefer:${k}`, NAMES[k], { cls: `short ${st.preferred === k ? "on" : ""}` })).join("");
    return `<h2>Settings</h2><div class="settings">
      <div class="label">Signals</div><div class="row">${toggles}</div>
      <div class="label">Try first</div><div class="row">${prefer}</div>
      <div class="label">Sounds</div><div class="row">${B("sounds", st.sounds ? "On" : "Off", { cls: `short ${st.sounds ? "on" : "off"}` })}<div style="flex:3"></div></div>
      <div class="label">Keyboard</div><div class="row">${B("keyboard:grouped", "Grouped", { cls: `short ${st.keyboard === "grouped" ? "on" : ""}` })}${B("keyboard:qwerty", "QWERTY", { cls: `short ${st.keyboard === "qwerty" ? "on" : ""}` })}<div style="flex:2"></div></div>
      <div class="label">Setup</div><div class="row">${B("recalibrate", "Recalibrate", { cls: "short" })}${B("check_signals", "Check my signals", { cls: "short" })}<div style="flex:2"></div></div>
      </div>`;
  },
};

function render() {
  if (!state) return;
  // During setup the whole screen belongs to the calibration and signal check dots.
  document.body.classList.toggle("setup", state.screen === "landing");
  $("#strip").innerHTML = state.undo
    ? B(state.undo.mode, state.undo.mode === "undo" ? "Undo" : "Redo", { icon: state.undo.mode })
    : `<div class="rest">${ICON.undo}</div>`;
  const side = !["landing", "compose"].includes(state.screen);
  $("#side").innerHTML = side
    ? B("nav_chats", "Chats", { icon: "chats", cls: state.screen === "chats" ? "on" : "" }) +
      B("nav_settings", "Settings", { icon: "settings", cls: state.screen === "settings" ? "on" : "" })
    : "";
  $("#main").innerHTML = (SCREENS[state.screen] || SCREENS.chats)();
  $("#rside").innerHTML = scrollBar();
  reapplyButtons();
  reportTargets();
  ring(state.call && !state.call.connected);
}

// ---------- gaze dot, calibration dot, banners ----------

// Phone link: until phone data arrives, say so calmly instead of showing a dot that never moves.
let phoneLinked = null;
function showWaiting() {
  $("#waiting").hidden = !(started && INIT.source === "arkit" && phoneLinked === false);
}

let gazeFrozen = false;
function onGaze(m) {
  const g = $("#gaze");
  if (!m.valid) { g.hidden = true; return; }
  g.hidden = false;
  g.style.transform = `translate(${m.x}px, ${m.y}px)`;
  gazeFrozen = !!m.frozen;
  updateGazeSize();
}
function updateGazeSize() {
  $("#gaze").classList.toggle("small", gazeFrozen || !!document.querySelector(".t.await, .t.locked"));
}

function showDot(x, y) {
  const d = $("#calib");
  if (x == null) { d.hidden = true; return; }
  d.hidden = false;
  d.style.left = `${x}px`;
  d.style.top = `${y}px`;
}

// ---------- corner: face view and the signal just detected ----------

let showFace = true;
try { showFace = localStorage.getItem("showFace") !== "no"; } catch (_) { /* fine without storage */ }
let sigTimer = null;
function showSignal(kind) {
  const s = $("#sig");
  s.innerHTML = `${ICON[kind] || ""}<span>${esc(NAMES[kind] || kind)}</span>`;
  s.hidden = false;
  s.style.animation = "none";
  void s.offsetWidth;
  s.style.animation = "";
  clearTimeout(sigTimer);
  sigTimer = setTimeout(() => (s.hidden = true), 1600);
}

let noticeTimer = null;
function notice(text) {
  const n = $("#notice");
  n.textContent = text;
  n.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => (n.hidden = true), 3000);
}

// ---------- sounds (made here, so there are no sound files) ----------

let audio = null;
function tone(freq, ms, gain = 0.08, type = "sine", delay = 0) {
  if (!audio) return;
  const t0 = audio.currentTime + delay / 1000;
  const o = audio.createOscillator(), g = audio.createGain();
  o.type = type;
  o.frequency.value = freq;
  g.gain.setValueAtTime(0, t0);
  g.gain.linearRampToValueAtTime(gain, t0 + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + ms / 1000);
  o.connect(g).connect(audio.destination);
  o.start(t0);
  o.stop(t0 + ms / 1000 + 0.02);
}
function sound(name) {
  if (state && state.settings && !state.settings.sounds) return;
  if (name === "tick") tone(1320, 120, 0.09);
  else if (name === "error") tone(220, 220, 0.06, "triangle");
  else if (name === "sent") { tone(660, 140); tone(990, 200, 0.08, "sine", 120); }
  else if (name === "received") { tone(780, 140); tone(520, 200, 0.07, "sine", 120); }
}
let ringTimer = null;
function ring(on) {
  if (on && !ringTimer) {
    const once = () => { if (!state || !state.settings || state.settings.sounds) { tone(440, 700, 0.05); tone(480, 700, 0.05); } };
    once();
    ringTimer = setInterval(once, 2200);
  } else if (!on && ringTimer) {
    clearInterval(ringTimer);
    ringTimer = null;
  }
}

// ---------- researcher panels ----------

function buildCosts(costs) {
  $("#costs").innerHTML = [0, 1, 2, 3].map((t) =>
    `<label>Tier ${t} <input type="number" step="0.5" min="0" id="cost${t}" value="${costs[`tier${t}`]}"></label>`).join("") +
    `<label>Version <input type="text" id="costVersion" value="${esc(costs.version)}"></label>`;
}
function renderDebug() {
  if ($("#debug").hidden) return;
  const lines = [
    `group: ${debug.group}`,
    `dwell now: ${Object.entries(debug.dwell).map(([t, ms]) => `tier ${t} ${ms} ms`).join(", ")}`,
    debug.context ? `tired: ${debug.context.tired}  shaky: ${debug.context.shaky}  poor tracking: ${debug.context.poor_tracking}` : "",
    debug.choice ? `last choice: ${debug.choice.action} -> ${debug.choice.check}\nscores: ${JSON.stringify(debug.choice.scores && debug.choice.scores.scores)}` : "",
  ];
  $("#debugText").textContent = lines.filter(Boolean).join("\n");
}

// ---------- connection ----------

function send(m) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(m)); }
// The page's size and where its top left sits on the screen, so the core can keep gaze anchored
// to the screen when the window leaves full screen or moves.
const origin = () => ({ ox: screenX + (outerWidth - innerWidth) / 2, oy: screenY + (outerHeight - innerHeight) });
function hello() { if (started) send({ type: "hello", w: innerWidth, h: innerHeight, ...origin() }); }
let lastOrigin = "";
setInterval(() => {   // moving a window fires no resize event, so check its position now and then
  const o = JSON.stringify(origin());
  if (o !== lastOrigin) { lastOrigin = o; hello(); }
}, 1000);

const HANDLERS = {
  init(m) {
    TIERS = m.tiers; SIGNALS = m.signals; INIT = m;
    $("#startInfo").textContent = `${m.person}, ${m.condition}, ${m.source === "mouse" ? "mouse test mode (B, E, Y, S are the signals)" : m.pointing === "head" ? "iPhone head pointing" : "iPhone gaze"}`;
    $("#studyInfo").textContent = `Participant ${m.person}. Condition: ${m.condition}. Source: ${m.source}.`;
    buildCosts(m.costs);
    document.body.classList.toggle("mouse", m.source === "mouse");
    hello();
    render();
  },
  state(m) { state = m.state; render(); },
  gaze: onGaze,
  button: onButton,
  dim(m) { document.body.classList.toggle("dim", !!m.on); },
  sound(m) { sound(m.name); },
  banner(m) { const b = $("#banner"); b.hidden = !m.text; b.textContent = m.text || ""; },
  notice(m) { notice(m.text); },
  calib_dot(m) { showDot(m.x, m.y); },
  calib_done(m) { showDot(null); },
  check_prompt(m) {
    checkPrompt = m;
    if (m.dot) showDot(m.dot[0] * innerWidth, m.dot[1] * innerHeight); else showDot(null);
    if (state && state.screen === "landing") render();
  },
  check_done() { showDot(null); checkPrompt = null; },
  preview(m) {
    $("#faceimg").src = `data:image/jpeg;base64,${m.jpg}`;
    $("#facecam").hidden = !showFace;
  },
  signal(m) { showSignal(m.kind); },
  link(m) { phoneLinked = m.phone; showWaiting(); },
  choice(m) { debug.choice = m; renderDebug(); },
  dwell_now(m) { debug.dwell[m.tier] = m.ms; debug.group = m.group; renderDebug(); },
  context(m) { debug.context = m; debug.group = m.group; renderDebug(); },
  config(m) { buildCosts(m.costs); },
  // Researcher only: never shown on the participant's screen.
  stale(m) { const s = $("#stale"); s.textContent = m.text; s.hidden = false; },
};

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => { const m = JSON.parse(e.data); const h = HANDLERS[m.type]; if (h) h(m); };
  ws.onopen = () => { hello(); if (state) reportTargets(); };
  ws.onclose = () => setTimeout(connect, 1000);
}

// ---------- input: keys, mouse (test mode), start ----------

addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("#study")) return;
  if (e.key === "`") { $("#study").hidden = !$("#study").hidden; return; }
  if (e.key === "\\") { $("#debug").hidden = !$("#debug").hidden; renderDebug(); return; }
  if (e.key === "f" || e.key === "F") {
    showFace = !showFace;
    try { localStorage.setItem("showFace", showFace ? "yes" : "no"); } catch (_) { /* fine */ }
    $("#facecam").hidden = !showFace || !$("#faceimg").src;
    return;
  }
  if (e.repeat) return;
  if (e.key === " " || e.key === "Enter") e.preventDefault();
  send({ type: "key", key: e.key, down: true });
});
addEventListener("keyup", (e) => {
  if (e.target.closest && e.target.closest("#study")) return;
  send({ type: "key", key: e.key, down: false });
});

let mouse = null, mouseSent = null;
addEventListener("mousemove", (e) => { mouse = { x: e.clientX, y: e.clientY }; });
(function pump() {
  if (INIT.source === "mouse" && mouse && mouse !== mouseSent) {
    send({ type: "mouse", ...mouse });
    mouseSent = mouse;
  }
  requestAnimationFrame(pump);
})();

// Buttons are chosen by gaze only. A click does nothing (except in the researcher panels).
addEventListener("mousedown", (e) => { if (!e.target.closest("#study, #start")) e.preventDefault(); }, true);
addEventListener("click", (e) => { if (!e.target.closest("#study, #start")) e.preventDefault(); }, true);

$("#start").addEventListener("click", () => {
  audio = audio || new (window.AudioContext || window.webkitAudioContext)();
  audio.resume();
  // Full screen is nice to have; never wait on it (some embedded browsers leave the promise pending).
  const fs = document.documentElement.requestFullscreen;
  if (fs) fs.call(document.documentElement).catch(() => {});
  $("#start").hidden = true;
  started = true;
  showWaiting();
  setTimeout(() => { hello(); reportTargets(); }, 400);
});

// Scale the 1280 x 860 frame to fill the screen height (or width, if that runs out first),
// keeping a 16 px margin and the same aspect ratio.
const FRAME = { w: 1280, h: 860, margin: 16 };
function fit() {
  const s = Math.min((innerWidth - 2 * FRAME.margin) / FRAME.w, (innerHeight - 2 * FRAME.margin) / FRAME.h);
  document.documentElement.style.setProperty("--s", Math.max(0.5, s).toFixed(4));
}
fit();

let resizeTimer = null;
addEventListener("resize", () => {
  fit();
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { hello(); reportTargets(); }, 200);
});
document.fonts && document.fonts.ready.then(reportTargets);

$("#applyCosts").addEventListener("click", () => {
  const costs = { version: $("#costVersion").value };
  for (const t of [0, 1, 2, 3]) costs[`tier${t}`] = parseFloat($(`#cost${t}`).value);
  send({ type: "set_costs", costs });
});
$("#resetLearning").addEventListener("click", () => {
  if (confirm("Reset everything this participant's learners have learned?")) send({ type: "reset_learning" });
});

connect();
