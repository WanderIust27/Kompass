/* Kompass — Oberfläche. Vanilla JS, keine Abhängigkeiten.

   Zwei Regeln bestimmen den Aufbau:
   1. Eine Ansicht zeigt eine Sache. Alles Zweitrangige liegt hinter einem
      Antippen, nicht neben dem Wichtigen.
   2. Leeres wird nicht angezeigt. Eine Überschrift über "nichts da" ist
      genau der Lärm, den man beim Draufschauen wegfiltern muss. */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const KIND_LABEL = {
  aufgabe: "Aufgabe", idee: "Idee", notiz: "Notiz", kauf: "Kauf",
  person: "Person", empfehlung: "Empfehlung", routine: "Routine",
};
const TABS = ["today", "inbox", "hub", "more"];
const today = () => new Date().toISOString().slice(0, 10);

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* egal */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

let toastTimer = null;
function toast(text, isError = false) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.toggle("err", !!isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2400);
}

async function guard(fn) {
  try { return await fn(); }
  catch (e) { toast(e.message, true); throw e; }
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function dayLabel(iso) {
  if (!iso) return "";
  if (iso === today()) return "heute";
  const d = new Date(iso + "T12:00:00");
  const diff = Math.round((d - new Date(today() + "T12:00:00")) / 86400000);
  if (diff === 1) return "morgen";
  if (diff === -1) return "gestern";
  if (diff < 0) return `seit ${plural(-diff, "Tag", "Tagen")}`;
  return d.toLocaleDateString("de-DE", { day: "numeric", month: "short" });
}

/* ------------------------------------------------------------------ Reiter */

const LOADERS = {};
let currentView = "today";

function showView(name) {
  currentView = name;
  const tab = TABS.includes(name) ? name : "hub";
  $$("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === tab));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  window.scrollTo({ top: 0 });
  if (LOADERS[name]) LOADERS[name]();
}
document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-view]");
  if (target) showView(target.dataset.view);
});

/* --------------------------------------------------- Ein Feld für alles */

async function capture() {
  const input = $("#captureInput");
  const raw = input.value.trim();
  if (!raw) return;
  input.value = "";
  const item = await guard(() => api("/inbox", { method: "POST", body: { raw } }));
  toast("Drin.");
  refreshState();
  api(`/inbox/${item.id}/suggest`, { method: "POST" })
    .then(() => { if (currentView === "inbox") LOADERS.inbox(); refreshState(); })
    .catch(() => {});
}
$("#captureBtn").addEventListener("click", capture);
$("#captureInput").addEventListener("keydown", (e) => { if (e.key === "Enter") capture(); });

let lastStatus = null;
async function refreshState() {
  try {
    const s = await api("/status");
    lastStatus = s;
    $("#inboxDot").hidden = !s.inbox;
    const badge = $("#statusBadge");
    badge.className = "state " + (s.ollama.erreichbar ? "ok" : "err");
    badge.title = s.ollama.erreichbar
      ? `Modell: ${s.ollama.modell}` : "Kein Modell erreichbar";
  } catch (e) { /* beim Start egal */ }
}
$("#statusBadge").addEventListener("click", () => {
  toast(lastStatus?.ollama.erreichbar
    ? `Modell ${lastStatus.ollama.modell} antwortet.`
    : "Kein Modell erreichbar — Kompass rechnet solange selbst.");
});

/* --------------------------------------------------------------- Zeilen */

/* Eine Zeile, ein Muster — für Aufgaben, Routinen, alles Abhakbare.
   Die Aktionen tauchen erst auf, wenn man die Zeile antippt. */
function row(item) {
  return `<div class="row" data-kind="${item.kind}" data-id="${item.id}">
    ${item.check === false ? "" : `<button class="check" aria-label="Erledigt"></button>`}
    <div class="grow">
      <span class="title">${esc(item.title)}</span>
      ${item.meta ? `<div class="meta">${item.meta}</div>` : ""}
      ${item.extra || ""}
    </div>
    ${item.when ? `<span class="when">${esc(item.when)}</span>` : ""}
  </div>`;
}

function bindRows(box, actions, after) {
  box.querySelectorAll(".row[data-kind]").forEach((el) => {
    const kind = el.dataset.kind;
    const id = el.dataset.id;
    const conf = actions[kind];
    if (!conf) return;
    el.querySelector(".check")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      el.classList.add("gone");
      await guard(() => conf.done(id));
      setTimeout(after, 220);
    });
    el.querySelector(".grow")?.addEventListener("click", () => {
      const open = el.querySelector(".acts");
      if (open) { open.remove(); return; }
      const acts = document.createElement("div");
      acts.className = "acts";
      acts.innerHTML = (conf.actions || []).map((a, i) =>
        `<button data-i="${i}" class="${a.warn ? "warn" : ""}">${esc(a.label)}</button>`).join("");
      el.querySelector(".grow").appendChild(acts);
      acts.querySelectorAll("button").forEach((b) =>
        b.addEventListener("click", async (e) => {
          e.stopPropagation();
          await guard(() => conf.actions[Number(b.dataset.i)].run(id));
          after();
        }));
    });
  });
}

const TASK_ACTIONS = {
  done: (id) => api(`/tasks/${id}/done`, { method: "POST" }),
  actions: [
    { label: "morgen", run: (id) => api(`/tasks/${id}/snooze?days=1`, { method: "POST" }) },
    { label: "in 3 Tagen", run: (id) => api(`/tasks/${id}/snooze?days=3`, { method: "POST" }) },
    { label: "löschen", warn: true, run: (id) => api(`/tasks/${id}`, { method: "DELETE" }) },
  ],
};
const ROUTINE_ACTIONS = {
  done: (id) => api(`/routines/${id}/done`, { method: "POST", body: {} }),
  actions: [
    { label: "morgen", run: (id) => api(`/routines/${id}/snooze?days=1`, { method: "POST" }) },
    { label: "in 3 Tagen", run: (id) => api(`/routines/${id}/snooze?days=3`, { method: "POST" }) },
  ],
};

/* ------------------------------------------------------------------ HEUTE */

LOADERS.today = async function () {
  const state = await api("/today");
  renderDay(state);
  loadBriefing(false);
  loadDecisions();
  renderCheckin();
};

function renderDay(state) {
  const late = (t) => t.due_date && t.due_date < today();
  const items = [
    ...state.tasks.map((t) => ({
      kind: "task", id: t.id, title: t.title,
      when: t.est_min ? `${t.est_min} min` : "",
      meta: [late(t) ? `fällig ${dayLabel(t.due_date)}` : null,
             t.project_title ? esc(t.project_title) : null]
             .filter(Boolean).join(" · "),
      rank: late(t) ? 0 : 1, min: t.est_min || 15,
    })),
    ...state.routines.map((r) => ({
      kind: "routine", id: r.id, title: r.title,
      when: `${r.duration_min} min`,
      meta: r.overdue_days > 2 ? `seit ${plural(r.overdue_days, "Tag", "Tagen")} offen` : "",
      rank: r.overdue_days > 2 ? 0 : 2, min: r.duration_min || 10,
    })),
  ].sort((a, b) => a.rank - b.rank || a.min - b.min);

  $("#dayList").innerHTML = items.length ? items.map(row).join("")
    : `<p class="empty">Heute steht nichts an.</p>`;
  bindRows($("#dayList"), { task: TASK_ACTIONS, routine: ROUTINE_ACTIONS },
           () => LOADERS.today());

  const foot = $("#dayFoot");
  const over = state.used_min - state.capacity_min;
  foot.innerHTML = items.length
    ? `<span>${plural(items.length, "Sache", "Sachen")} · ${state.used_min} min`
      + (over > 0 ? ` — ${over} mehr als du hast` : "") + `</span>`
      + `<button class="link" id="replanBtn">neu planen</button>`
    : `<button class="link" id="replanBtn">Tag planen</button>`;
  $("#replanBtn").addEventListener("click", async () => {
    await guard(() => api("/today/plan", { method: "POST" }));
    LOADERS.today();
  });
}

async function loadBriefing(force) {
  const box = $("#briefing");
  const slot = new Date().getHours() >= 17 ? "evening" : "morning";
  if (force) box.textContent = "…";
  try {
    const data = await api(`/briefing?slot=${slot}&force=${force ? "true" : "false"}`);
    box.innerHTML = esc(data.text)
      + (data.computed ? ` <span class="quiet">gerechnet, kein Modell</span>` : "")
      + ` <button class="link again" id="briefAgain">neu</button>`;
    $("#briefAgain").addEventListener("click", () => loadBriefing(true));
  } catch (e) {
    box.textContent = "Briefing kam nicht durch: " + e.message;
  }
}

async function loadDecisions() {
  const [ideas, buys, meta, folks] = await Promise.all([
    api("/ideas?status=ripe"), api("/purchases?status=ready"),
    api("/purchases/meta"), api("/people/due"),
  ]);
  const lines = [];
  ideas.forEach((i) => lines.push({ view: "projects", text: `Idee „${i.title}“ ist reif` }));
  buys.forEach((p) => lines.push({ view: "buy", text: `„${p.title}“ hat die Wartefrist hinter sich` }));
  (meta.nutzung_offen || []).forEach((p) =>
    lines.push({ view: "buy", text: `Benutzt du „${p.title}“ noch?` }));
  (folks.geburtstage || []).filter((p) => p.birthday_in <= 14).forEach((p) =>
    lines.push({ view: "people", text: `${p.name} hat in ${plural(p.birthday_in, "Tag", "Tagen")} Geburtstag` }));
  (folks.fällig || []).slice(0, 2).forEach((p) =>
    lines.push({ view: "people", text: `${p.name} — seit ${plural(p.days_since, "Tag", "Tagen")} nichts gehört` }));

  const box = $("#decisions");
  box.hidden = lines.length === 0;
  box.innerHTML = `<p class="label">Warten auf dich</p>` + lines.map((l) =>
    `<div class="row"><div class="grow"><button class="link" data-view="${l.view}"
      style="color:var(--ink);font-size:1rem">${esc(l.text)}</button></div></div>`).join("");
}

/* Der Check-in taucht erst am Abend auf. Vorher wäre er nur eine weitere
   Kachel, die man den ganzen Tag ignoriert. */
let checkinMood = null;
async function renderCheckin() {
  const settings = await api("/settings");
  const hour = Number(settings.evening_hour || 21);
  const box = $("#checkinBox");
  box.hidden = new Date().getHours() < hour;
  if (box.hidden || $("#scaleMood").innerHTML) return;
  $("#scaleMood").innerHTML = [1, 2, 3, 4, 5].map((n) =>
    `<button data-v="${n}">${n}</button>`).join("");
  $("#scaleMood").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", async () => {
      checkinMood = Number(b.dataset.v);
      $("#scaleMood").querySelectorAll("button").forEach((o) =>
        o.classList.toggle("on", o === b));
      await save();
    }));
  const save = () => api("/checkin", {
    method: "POST",
    body: { mood: checkinMood, note: $("#checkinNote").value || null },
  }).then(() => toast("Notiert.")).catch(() => {});
  $("#checkinNote").addEventListener("change", save);
}

/* ------------------------------------------------------------------ INBOX */

let inboxStatus = "new";
LOADERS.inbox = async function () {
  const items = await api(`/inbox?status=${inboxStatus}`);
  const box = $("#inboxList");
  if (!items.length) {
    box.innerHTML = `<p class="empty">${inboxStatus === "new"
      ? "Leer. Genau so soll es aussehen." : "Nichts einsortiert."}</p>`;
    return;
  }
  if (inboxStatus !== "new") {
    box.innerHTML = items.map((i) => `<div class="row"><div class="grow">
      <span class="title">${esc(i.raw)}</span>
      <div class="meta">${esc(KIND_LABEL[i.kind] || i.status)}</div></div></div>`).join("");
    return;
  }
  box.innerHTML = items.map((item) => {
    const s = item.suggestion || {};
    const kind = s.art || item.kind || "aufgabe";
    return `<div class="row" data-inbox="${item.id}"><div class="grow">
      <span class="title">${esc(item.raw)}</span>
      <div class="acts">
        <button data-act="apply">als ${esc(KIND_LABEL[kind])} übernehmen</button>
        <button data-act="other">andere Schublade</button>
        <button data-act="dismiss" class="warn">weg</button>
      </div>
      <div data-picker hidden>
        <div class="acts">${Object.entries(KIND_LABEL).map(([k, l]) =>
          `<button data-kind="${k}">${l}</button>`).join("")}</div>
      </div>
    </div></div>`;
  }).join("");

  box.querySelectorAll("[data-inbox]").forEach((el) => {
    const id = el.dataset.inbox;
    const apply = async (kind) => {
      const res = await guard(() => api(`/inbox/${id}/apply`,
        { method: "POST", body: kind ? { kind } : {} }));
      toast(`Als ${KIND_LABEL[res.kind]} angelegt.`);
      LOADERS.inbox(); refreshState();
    };
    el.querySelector('[data-act="apply"]').addEventListener("click", () => apply(null));
    el.querySelector('[data-act="other"]').addEventListener("click", () => {
      const picker = el.querySelector("[data-picker]");
      picker.hidden = !picker.hidden;
    });
    el.querySelectorAll("[data-kind]").forEach((b) =>
      b.addEventListener("click", () => apply(b.dataset.kind)));
    el.querySelector('[data-act="dismiss"]').addEventListener("click", async () => {
      await guard(() => api(`/inbox/${id}/dismiss`, { method: "POST" }));
      LOADERS.inbox(); refreshState();
    });
  });
};
$("#inboxHistoryBtn").addEventListener("click", () => {
  inboxStatus = inboxStatus === "new" ? "sorted" : "new";
  $("#inboxHistoryBtn").textContent =
    inboxStatus === "new" ? "Schon einsortiert" : "Offene zeigen";
  LOADERS.inbox();
});

/* -------------------------------------------------------------------- HUB */

LOADERS.hub = async function () {
  const [s, buy, recs, folks] = await Promise.all([
    api("/status"), api("/purchases/meta"), api("/recs/meta"), api("/people/due"),
  ]);
  const set = (id, text) => { $(id).textContent = text; };
  set("#hubTasks", s.aufgaben.offen ? `${s.aufgaben.offen} offen` : "");
  set("#hubProjects", `${s.projekte.used} von ${s.projekte.limit}`);
  set("#hubHome", s.haushalt.fällig ? `${s.haushalt.fällig} fällig` : "");
  set("#hubBuy", buy.zahlen.entscheiden
    ? `${buy.zahlen.entscheiden} entscheiden`
    : (buy.zahlen.wartet ? `${buy.zahlen.wartet} wartet` : ""));
  set("#hubNotes", s.notizen.gesamt ? `${s.notizen.gesamt}` : "");
  set("#hubRecs", recs.zahlen.liste ? `${recs.zahlen.liste} vorgemerkt` : "");
  set("#hubPeople", folks.fällig.length ? `${folks.fällig.length} dran` : "");
};

/* --------------------------------------------------------------- AUFGABEN */

let taskStatus = "open";
let taskShowAll = false;
LOADERS.tasks = async function () {
  const [list, projects] = await Promise.all([
    api(`/tasks?status=${taskStatus}`), api("/projects"),
  ]);
  const shown = taskShowAll || taskStatus !== "open" ? list : list.slice(0, 25);
  $("#taskList").innerHTML = shown.length ? shown.map((t) => row({
    kind: "task", id: t.id, title: t.title,
    check: taskStatus !== "done",
    when: t.est_min ? `${t.est_min} min` : "",
    meta: [t.due_date ? `fällig ${dayLabel(t.due_date)}` : null,
           t.project_title ? esc(t.project_title) : null,
           t.snoozes > 2 ? `${t.snoozes}× verschoben` : null].filter(Boolean).join(" · "),
  })).join("") : `<p class="empty">Nichts offen.</p>`;
  bindRows($("#taskList"), { task: TASK_ACTIONS }, () => LOADERS.tasks());
  $("#taskProject").innerHTML = `<option value="">ohne Projekt</option>`
    + projects.map((p) => `<option value="${p.id}">${esc(p.title)}</option>`).join("");
  $("#taskFilterAll").textContent = taskShowAll ? "weniger zeigen" : "alle zeigen";
  $("#taskFilterDone").textContent = taskStatus === "done" ? "offene" : "erledigte";
};
$("#taskFilterAll").addEventListener("click", () => {
  taskShowAll = !taskShowAll; LOADERS.tasks();
});
$("#taskFilterDone").addEventListener("click", () => {
  taskStatus = taskStatus === "done" ? "open" : "done"; LOADERS.tasks();
});
$("#taskAdd").addEventListener("click", async () => {
  const title = $("#taskTitle").value.trim();
  if (!title) return toast("Ohne Titel geht es nicht.", true);
  await guard(() => api("/tasks", {
    method: "POST",
    body: { title, est_min: Number($("#taskMin").value) || 15,
            energy: $("#taskEnergy").value, due_date: $("#taskDue").value || null,
            project_id: Number($("#taskProject").value) || null },
  }));
  $("#taskTitle").value = ""; $("#taskMin").value = ""; $("#taskDue").value = "";
  LOADERS.tasks();
});

/* --------------------------------------------------------------- PROJEKTE */

LOADERS.projects = async function () {
  const [slots, projects, ideas, settings] = await Promise.all([
    api("/projects/slots"), api("/projects"), api("/ideas"), api("/settings"),
  ]);
  $("#slotBadge").textContent = `${slots.slots.used} von ${slots.slots.limit}`;
  $("#cooldownHint").textContent = `${settings.idea_cooldown_days} Tage Karenz`;

  $("#projectList").innerHTML = projects.length ? projects.map((p) => `
    <div class="row" data-project="${p.id}"><div class="grow">
      <span class="title">${esc(p.title)}</span>
      <div class="meta">${[
        p.next_action ? esc(p.next_action) : "kein nächster Schritt",
        p.open_tasks ? `${p.open_tasks} offen` : null,
        p.stale_days >= 10 ? `seit ${p.stale_days} Tagen nichts passiert` : null,
      ].filter(Boolean).join(" · ")}</div>
      <div class="acts">
        <button data-act="next">Schritt ändern</button>
        <button data-act="done">abschließen</button>
        <button data-act="drop" class="warn">verwerfen</button>
      </div>
    </div></div>`).join("")
    : `<p class="empty">Kein Projekt aktiv. Das ist kein Mangel.</p>`;

  $("#projectList").querySelectorAll("[data-project]").forEach((el) => {
    const id = el.dataset.project;
    el.querySelector('[data-act="next"]').addEventListener("click", async () => {
      const value = prompt("Was ist der nächste konkrete Schritt?");
      if (value === null) return;
      await guard(() => api(`/projects/${id}`, { method: "PATCH", body: { next_action: value } }));
      LOADERS.projects();
    });
    el.querySelector('[data-act="done"]').addEventListener("click", async () => {
      await guard(() => api(`/projects/${id}`, { method: "PATCH", body: { status: "done" } }));
      toast("Ein Platz ist frei."); LOADERS.projects();
    });
    el.querySelector('[data-act="drop"]').addEventListener("click", async () => {
      if (!confirm("Projekt verwerfen?")) return;
      await guard(() => api(`/projects/${id}`, { method: "PATCH", body: { status: "dropped" } }));
      LOADERS.projects();
    });
  });

  const open = ideas.filter((i) => ["parked", "ripe"].includes(i.status));
  $("#ideaList").innerHTML = open.length ? open.map((i) => {
    const ripe = i.status === "ripe" || i.is_ripe;
    return `<div class="row" data-idea="${i.id}"><div class="grow">
      <span class="title">${esc(i.title)}</span>
      <div class="meta">${ripe ? "reif" : `noch ${plural(i.days_left, "Tag", "Tage")}`}</div>
      ${i.ai_take ? `<div class="take">${esc(i.ai_take)}</div>` : ""}
      <div class="acts">
        ${ripe ? `<button data-act="review">bewerten</button>
                  <button data-act="promote">Projekt daraus</button>` : ""}
        <button data-act="sleep">vertagen</button>
        <button data-act="drop" class="warn">verwerfen</button>
      </div>
      <div data-panel></div>
    </div></div>`;
  }).join("") : `<p class="empty">Parkplatz leer.</p>`;

  $("#ideaList").querySelectorAll("[data-idea]").forEach((el) => {
    const id = el.dataset.idea;
    el.querySelector('[data-act="drop"]').addEventListener("click", async () => {
      await guard(() => api(`/ideas/${id}/drop`, { method: "POST" })); LOADERS.projects();
    });
    el.querySelector('[data-act="sleep"]').addEventListener("click", async () => {
      await guard(() => api(`/ideas/${id}/sleep?days=30`, { method: "POST" }));
      toast("Nochmal 30 Tage."); LOADERS.projects();
    });
    el.querySelector('[data-act="review"]')?.addEventListener("click", () => ritual(el, id));
    el.querySelector('[data-act="promote"]')?.addEventListener("click", () => promote(id));
  });
};

async function ritual(el, id) {
  const panel = el.querySelector("[data-panel]");
  if (panel.innerHTML) { panel.innerHTML = ""; return; }
  const questions = await api("/ideas/questions");
  panel.innerHTML = questions.map((q) =>
    `<label class="quiet" style="display:block;margin-top:10px">${esc(q.frage)}
      <input data-q="${q.key}" style="margin-top:4px"></label>`).join("")
    + `<button class="btn" style="margin-top:12px" data-act="submit">Einschätzen lassen</button>`;
  panel.querySelector('[data-act="submit"]').addEventListener("click", async () => {
    const answers = {};
    panel.querySelectorAll("[data-q]").forEach((i) => { answers[i.dataset.q] = i.value; });
    panel.innerHTML = `<p class="quiet">Kompass denkt nach …</p>`;
    await guard(() => api(`/ideas/${id}/review`, { method: "POST", body: { answers } }));
    LOADERS.projects();
  });
}

async function promote(id) {
  try {
    await api(`/ideas/${id}/promote`, { method: "POST", body: {} });
    toast("Läuft jetzt als Projekt.");
  } catch (e) {
    const reason = prompt(e.message + "\n\nWenn es trotzdem sein muss: warum?");
    if (!reason) return;
    await guard(() => api(`/ideas/${id}/promote`,
      { method: "POST", body: { override_reason: reason } }));
  }
  LOADERS.projects();
}

$("#projAdd").addEventListener("click", async () => {
  const body = { title: $("#projTitle").value.trim(), next_action: $("#projNext").value };
  if (!body.title) return toast("Ohne Titel geht es nicht.", true);
  try {
    await api("/projects", { method: "POST", body });
  } catch (e) {
    const reason = prompt(e.message + "\n\nTrotzdem starten? Dann sag warum.");
    if (!reason) return;
    await guard(() => api("/projects", { method: "POST", body: { ...body, override_reason: reason } }));
  }
  $("#projTitle").value = ""; $("#projNext").value = "";
  LOADERS.projects();
});

/* --------------------------------------------------------------- HAUSHALT */

LOADERS.home = async function () {
  const due = await api("/routines/due");
  $("#homeDue").innerHTML = due.length ? due.map((r) => row({
    kind: "routine", id: r.id, title: r.title, when: `${r.duration_min} min`,
    meta: [r.room, r.overdue_days > 0 ? `seit ${plural(r.overdue_days, "Tag", "Tagen")}` : "heute"]
      .filter(Boolean).map(esc).join(" · "),
  })).join("") : `<p class="empty">Heute nichts. Genieß es.</p>`;
  bindRows($("#homeDue"), { routine: ROUTINE_ACTIONS }, () => LOADERS.home());

  if (!$("#homeAll").hidden) {
    const all = await api("/routines");
    $("#homeAll").innerHTML = all.map((r) => `<div class="row" data-routine-edit="${r.id}">
      <div class="grow"><span class="title">${esc(r.title)}</span>
        <div class="meta">${[r.room, `alle ${r.interval_days} Tage`,
          `${r.duration_min} min`].filter(Boolean).map(esc).join(" · ")}</div>
        <div class="acts">
          <button data-act="slower">seltener</button>
          <button data-act="faster">öfter</button>
          <button data-act="del" class="warn">löschen</button>
        </div></div></div>`).join("");
    $("#homeAll").querySelectorAll("[data-routine-edit]").forEach((el) => {
      const id = el.dataset.routineEdit;
      const change = async (factor) => {
        const r = all.find((x) => String(x.id) === id);
        const next = Math.max(1, Math.round(r.interval_days * factor * 10) / 10);
        await guard(() => api(`/routines/${id}`, { method: "PATCH", body: { interval_days: next } }));
        LOADERS.home();
      };
      el.querySelector('[data-act="slower"]').addEventListener("click", () => change(1.5));
      el.querySelector('[data-act="faster"]').addEventListener("click", () => change(0.66));
      el.querySelector('[data-act="del"]').addEventListener("click", async () => {
        await guard(() => api(`/routines/${id}`, { method: "DELETE" })); LOADERS.home();
      });
    });
  }
};
$("#homeAllBtn").addEventListener("click", () => {
  const box = $("#homeAll");
  box.hidden = !box.hidden;
  $("#homeAllBtn").textContent = box.hidden ? "Alle Routinen" : "Nur Fälliges";
  LOADERS.home();
});
$("#routAdd").addEventListener("click", async () => {
  const title = $("#routTitle").value.trim();
  if (!title) return toast("Ohne Titel geht es nicht.", true);
  await guard(() => api("/routines", {
    method: "POST",
    body: { title, room: $("#routRoom").value || null,
            interval_days: Number($("#routInterval").value) || 7,
            duration_min: Number($("#routMin").value) || 10 },
  }));
  ["#routTitle", "#routRoom", "#routInterval", "#routMin"].forEach((s) => { $(s).value = ""; });
  LOADERS.home();
});

/* ------------------------------------------------------------------ KÄUFE */

LOADERS.buy = async function () {
  const [meta, waiting, ready, settings] = await Promise.all([
    api("/purchases/meta"), api("/purchases?status=waiting"),
    api("/purchases?status=ready"), api("/settings"),
  ]);
  const b = meta.budget;
  $("#budgetBadge").textContent = b.budget
    ? `${b.spent.toFixed(0)} von ${b.budget.toFixed(0)} €`
    : (b.spent ? `${b.spent.toFixed(0)} € diesen Monat` : "");
  $("#buyRuleHint").textContent =
    `Ab ${settings.buy_threshold_small} € wartest du ${settings.buy_wait_small_h} Stunden, `
    + `ab ${settings.buy_threshold_big} € ${Math.round(settings.buy_wait_big_h / 24)} Tage.`;

  const usage = meta.nutzung_offen || [];
  $("#buyReady").innerHTML = [
    ...usage.map((p) => `<div class="row" data-usage="${p.id}"><div class="grow">
      <span class="title">Benutzt du „${esc(p.title)}“?</span>
      <div class="acts">${["oft", "manchmal", "nie"].map((v) =>
        `<button data-v="${v}">${v}</button>`).join("")}</div></div></div>`),
    ...ready.map((p) => `<div class="row" data-buy="${p.id}"><div class="grow">
      <span class="title">${esc(p.title)}${p.price_eur ? ` · ${p.price_eur} €` : ""}</span>
      ${p.reason ? `<div class="meta">${esc(p.reason)}</div>` : ""}
      ${p.ai_take ? `<div class="take">${esc(p.ai_take)}</div>` : ""}
      ${p.research?.zusammenfassung ? `<div class="take">${esc(p.research.zusammenfassung)}</div>` : ""}
      <div class="acts">
        <button data-act="ask">Fragen beantworten</button>
        ${meta.web ? `<button data-act="research">nachschlagen</button>` : ""}
        <button data-act="bought">gekauft</button>
        <button data-act="dropped" class="warn">doch nicht</button>
      </div>
      <div data-panel></div></div></div>`),
  ].join("") || `<p class="empty">Nichts zu entscheiden.</p>`;

  $("#buyWaiting").innerHTML = waiting.length
    ? `<p class="label">Wartet</p>` + waiting.map((p) => `<div class="row"><div class="grow">
        <span class="title">${esc(p.title)}</span></div>
        <span class="when">${p.hours_left >= 24
          ? "noch " + plural(Math.round(p.hours_left / 24), "Tag", "Tage")
          : "noch " + plural(Math.round(p.hours_left), "Stunde", "Stunden")}</span></div>`).join("")
    : "";

  $("#buyReady").querySelectorAll("[data-usage]").forEach((el) => {
    el.querySelectorAll("[data-v]").forEach((b2) => b2.addEventListener("click", async () => {
      await guard(() => api(`/purchases/${el.dataset.usage}/usage`,
        { method: "POST", body: { verdict: b2.dataset.v } }));
      toast("Das rechnet er dir beim nächsten Mal vor."); LOADERS.buy();
    }));
  });
  $("#buyReady").querySelectorAll("[data-buy]").forEach((el) => {
    const id = el.dataset.buy;
    el.querySelector('[data-act="ask"]').addEventListener("click", async () => {
      const panel = el.querySelector("[data-panel]");
      if (panel.innerHTML) { panel.innerHTML = ""; return; }
      panel.innerHTML = meta.fragen.map((q) =>
        `<label class="quiet" style="display:block;margin-top:10px">${esc(q.frage)}
          <input data-q="${q.key}" style="margin-top:4px"></label>`).join("")
        + `<button class="btn" style="margin-top:12px" data-act="submit">Einschätzen lassen</button>`;
      panel.querySelector('[data-act="submit"]').addEventListener("click", async () => {
        const answers = {};
        panel.querySelectorAll("[data-q]").forEach((i) => { answers[i.dataset.q] = i.value; });
        panel.innerHTML = `<p class="quiet">Kompass denkt nach …</p>`;
        await guard(() => api(`/purchases/${id}/answer`, { method: "POST", body: { answers } }));
        LOADERS.buy();
      });
    });
    el.querySelector('[data-act="research"]')?.addEventListener("click", async () => {
      toast("Sucht …");
      await guard(() => api(`/purchases/${id}/research`, { method: "POST" }));
      LOADERS.buy();
    });
    el.querySelector('[data-act="bought"]').addEventListener("click", async () => {
      const price = prompt("Was hat es gekostet? (Euro)");
      if (price === null) return;
      await guard(() => api(`/purchases/${id}/decide`,
        { method: "POST", body: { verdict: "gekauft", price: price || null } }));
      LOADERS.buy();
    });
    el.querySelector('[data-act="dropped"]').addEventListener("click", async () => {
      await guard(() => api(`/purchases/${id}/decide`,
        { method: "POST", body: { verdict: "verworfen" } }));
      toast("Gespart."); LOADERS.buy();
    });
  });
};
$("#buyAdd").addEventListener("click", async () => {
  const title = $("#buyTitle").value.trim();
  if (!title) return toast("Was willst du denn haben?", true);
  const created = await guard(() => api("/purchases", {
    method: "POST",
    body: { title, price_eur: $("#buyPrice").value || null,
            url: $("#buyUrl").value || null, reason: $("#buyReason").value || null },
  }));
  ["#buyTitle", "#buyPrice", "#buyUrl", "#buyReason"].forEach((s) => { $(s).value = ""; });
  toast(created.wait_hours ? `Wartet ${created.wait_hours} Stunden.` : "Unter der Schwelle.");
  LOADERS.buy();
});
$("#buyHistoryBtn").addEventListener("click", async () => {
  const box = $("#buyHistory");
  if (box.innerHTML) { box.innerHTML = ""; return; }
  const all = await api("/purchases?status=alle");
  const done = all.filter((p) => ["bought", "dropped"].includes(p.status));
  box.innerHTML = done.length ? done.map((p) => `<div class="row"><div class="grow">
    <span class="title">${esc(p.title)}</span>
    <div class="meta">${p.status === "bought" ? "gekauft" : "verworfen"}${
      p.price_eur ? ` · ${p.price_eur} €` : ""}${
      p.usage_verdict ? ` · benutzt: ${p.usage_verdict}` : ""}</div></div></div>`).join("")
    : `<p class="empty">Noch nichts entschieden.</p>`;
});

/* ---------------------------------------------------------------- NOTIZEN */

let noteTimer = null;
LOADERS.notes = async function () {
  const q = $("#noteSearch").value.trim();
  const list = await api("/notes" + (q ? `?q=${encodeURIComponent(q)}` : ""));
  $("#noteList").innerHTML = list.length ? list.map((n) => `
    <div class="row" data-note="${n.id}"><div class="grow">
      <span class="title">${esc(n.title || "ohne Titel")}</span>
      <div class="meta">${esc((n.body || "").slice(0, 140))}</div>
      <div class="acts"><button data-act="del" class="warn">löschen</button></div>
    </div></div>`).join("") : `<p class="empty">Nichts gefunden.</p>`;
  $("#noteList").querySelectorAll("[data-note]").forEach((el) => {
    el.querySelector('[data-act="del"]').addEventListener("click", async () => {
      await guard(() => api(`/notes/${el.dataset.note}`, { method: "DELETE" }));
      LOADERS.notes();
    });
  });
};
$("#noteSearch").addEventListener("input", () => {
  clearTimeout(noteTimer); noteTimer = setTimeout(() => LOADERS.notes(), 350);
});
$("#noteAdd").addEventListener("click", async () => {
  const body = $("#noteBody").value.trim();
  if (!body) return toast("Leere Notiz bringt nichts.", true);
  await guard(() => api("/notes", {
    method: "POST", body: { title: $("#noteTitle").value, body },
  }));
  $("#noteTitle").value = ""; $("#noteBody").value = "";
  LOADERS.notes();
});

/* ----------------------------------------------------------- EMPFEHLUNGEN */

LOADERS.recs = async function () {
  const meta = await api("/recs/meta");
  if (!$("#recKind").innerHTML) {
    const options = Object.entries(meta.sorten).map(([k, v]) =>
      `<option value="${k}">${v}</option>`).join("");
    $("#recKind").innerHTML = options;
    $("#recAddKind").innerHTML = options;
  }
  const list = await api(`/recs?status=${$("#recFilter").value}`);
  $("#recList").innerHTML = list.length ? list.map((r) => `
    <div class="row" data-rec="${r.id}"><div class="grow">
      <span class="title">${esc(r.title)}</span>
      <div class="meta">${[meta.sorten[r.kind], r.creator, r.year,
        r.rating ? `${r.rating}/5` : null].filter(Boolean).map(esc).join(" · ")}</div>
      <div class="acts">
        ${r.status !== "done" ? `<button data-act="done">durch</button>` : ""}
        ${[1, 2, 3, 4, 5].map((n) => `<button data-rate="${n}">${n}</button>`).join("")}
        <button data-act="del" class="warn">weg</button>
      </div></div></div>`).join("") : `<p class="empty">Liste leer.</p>`;
  $("#recList").querySelectorAll("[data-rec]").forEach((el) => {
    const id = el.dataset.rec;
    el.querySelector('[data-act="done"]')?.addEventListener("click", async () => {
      await guard(() => api(`/recs/${id}`, { method: "PATCH", body: { status: "done" } }));
      LOADERS.recs();
    });
    el.querySelectorAll("[data-rate]").forEach((b) => b.addEventListener("click", async () => {
      await guard(() => api(`/recs/${id}`,
        { method: "PATCH", body: { rating: Number(b.dataset.rate), status: "done" } }));
      LOADERS.recs();
    }));
    el.querySelector('[data-act="del"]').addEventListener("click", async () => {
      await guard(() => api(`/recs/${id}`, { method: "DELETE" })); LOADERS.recs();
    });
  });
};
$("#recFilter").addEventListener("change", () => LOADERS.recs());
$("#recSuggest").addEventListener("click", async () => {
  $("#recSuggestions").innerHTML = `<p class="empty">Kompass überlegt …</p>`;
  const data = await guard(() => api("/recs/suggest",
    { method: "POST", body: { kind: $("#recKind").value } }));
  const list = data.vorschläge || [];
  $("#recSuggestions").innerHTML = list.length ? `<p class="label">Vorschläge</p>`
    + list.map((r, i) => `<div class="row" data-sug="${i}"><div class="grow">
      <span class="title">${esc(r.title)}</span>
      <div class="meta">${[r.creator, r.year, r.verified ? "belegt" : "ungeprüft"]
        .filter(Boolean).map(esc).join(" · ")}</div>
      ${r.why ? `<div class="meta">${esc(r.why)}</div>` : ""}
      <div class="acts"><button data-act="keep">merken</button></div>
    </div></div>`).join("")
    : `<p class="empty">Nichts gekommen — läuft das Modell?</p>`;
  $("#recSuggestions").querySelectorAll("[data-sug]").forEach((el) => {
    el.querySelector('[data-act="keep"]').addEventListener("click", async () => {
      await guard(() => api("/recs", {
        method: "POST", body: { ...list[Number(el.dataset.sug)], source: "kompass" },
      }));
      el.remove(); LOADERS.recs();
    });
  });
});
$("#recAdd").addEventListener("click", async () => {
  const title = $("#recTitle").value.trim();
  if (!title) return toast("Titel fehlt.", true);
  await guard(() => api("/recs", {
    method: "POST",
    body: { title, creator: $("#recCreator").value || null, kind: $("#recAddKind").value },
  }));
  $("#recTitle").value = ""; $("#recCreator").value = "";
  LOADERS.recs();
});

/* --------------------------------------------------------------- MENSCHEN */

LOADERS.people = async function () {
  const [all, due] = await Promise.all([api("/people"), api("/people/due")]);
  const dueIds = new Set(due.fällig.map((p) => p.id));
  $("#peopleList").innerHTML = all.length ? all.map((p) => `
    <div class="row" data-person="${p.id}"><div class="grow">
      <span class="title">${esc(p.name)}</span>
      <div class="meta">${[
        dueIds.has(p.id) ? "wäre dran" : null,
        p.last_contact ? `zuletzt ${dayLabel(p.last_contact)}` : "noch nie eingetragen",
        p.birthday_in !== null && p.birthday_in <= 30
          ? `Geburtstag in ${plural(p.birthday_in, "Tag", "Tagen")}` : null,
        p.note ? esc(p.note) : null].filter(Boolean).join(" · ")}</div>
      <div class="acts">
        <button data-act="contact">gemeldet</button>
        <button data-act="del" class="warn">löschen</button>
      </div></div></div>`).join("")
    : `<p class="empty">Noch niemand eingetragen.</p>`;
  $("#peopleList").querySelectorAll("[data-person]").forEach((el) => {
    const id = el.dataset.person;
    el.querySelector('[data-act="contact"]').addEventListener("click", async () => {
      await guard(() => api(`/people/${id}/contact`, { method: "POST", body: {} }));
      toast("Notiert."); LOADERS.people();
    });
    el.querySelector('[data-act="del"]').addEventListener("click", async () => {
      if (!confirm("Person löschen?")) return;
      await guard(() => api(`/people/${id}`, { method: "DELETE" })); LOADERS.people();
    });
  });
};
$("#perAdd").addEventListener("click", async () => {
  const name = $("#perName").value.trim();
  if (!name) return toast("Name fehlt.", true);
  await guard(() => api("/people", {
    method: "POST",
    body: { name, birthday: $("#perBirthday").value || null,
            cadence_days: Number($("#perCadence").value) || null,
            note: $("#perNote").value || null },
  }));
  ["#perName", "#perBirthday", "#perCadence", "#perNote"].forEach((s) => { $(s).value = ""; });
  LOADERS.people();
});

/* ------------------------------------------------------------------ FRAGEN */

LOADERS.chat = async function () { renderChat(await api("/chat")); };
function renderChat(log) {
  $("#chatLog").innerHTML = log.length
    ? log.map((m) => `<div class="msg ${m.role}">${esc(m.content)}</div>`).join("")
    : `<p class="empty">Frag ihn etwas — er kennt deinen Stand.</p>`;
  window.scrollTo({ top: document.body.scrollHeight });
}
async function sendChat() {
  const input = $("#chatInput");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  const box = $("#chatLog");
  box.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(message)}</div>`);
  box.insertAdjacentHTML("beforeend", `<div class="msg assistant" id="pending">denkt nach …</div>`);
  try {
    renderChat((await api("/chat", { method: "POST", body: { message } })).history);
  } catch (e) {
    $("#pending").textContent = "Das ging schief: " + e.message;
  }
}
$("#chatSend").addEventListener("click", sendChat);
$("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
$("#chatClear").addEventListener("click", async () => {
  await guard(() => api("/chat", { method: "DELETE" })); LOADERS.chat();
});

/* -------------------------------------------------------------------- MEHR */

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const SETTING_FIELDS = {
  "#setCooldown": "idea_cooldown_days", "#setWip": "wip_limit",
  "#setBuySmall": "buy_threshold_small", "#setBuySmallH": "buy_wait_small_h",
  "#setBuyBig": "buy_threshold_big", "#setBuyBigH": "buy_wait_big_h",
  "#setBudget": "buy_budget_month", "#setUsage": "buy_usage_check_days",
  "#setMorning": "morning_hour", "#setEvening": "evening_hour",
  "#setTone": "tone", "#setName": "user_name",
};

LOADERS.more = async function () {
  const [settings, status, profile, models, events] = await Promise.all([
    api("/settings"), api("/status"), api("/profile"), api("/models"), api("/events?limit=12"),
  ]);
  Object.entries(SETTING_FIELDS).forEach(([sel, key]) => { $(sel).value = settings[key] ?? ""; });

  let capacity = {};
  try { capacity = JSON.parse(settings.capacity_json || "{}"); } catch (e) { capacity = {}; }
  $("#capacityGrid").innerHTML = WEEKDAYS.map((d) =>
    `<label>${d}<input type="number" min="0" data-day="${d}" value="${capacity[d] ?? 60}"></label>`).join("");

  $("#profileList").innerHTML = profile.length
    ? profile.map((f) => `<div class="row"><div class="grow">${esc(f.text)}</div></div>`).join("")
    : `<p class="empty">Noch zu wenig Daten.</p>`;

  $("#eventList").innerHTML = events.length
    ? events.map((e) => `<div class="row"><div class="grow">${esc(e.text)}
        <div class="meta">${esc(e.at)}</div></div></div>`).join("")
    : `<p class="empty">Noch nichts umgestellt.</p>`;

  $("#modelList").innerHTML = models.presets.map((m) => `
    <div class="row" data-model="${esc(m.name)}"><div class="grow">
      <span class="title">${esc(m.label)}${m.name === models.aktiv ? " · aktiv" : ""}</span>
      <div class="meta">${m.size_gb} GB · ${esc(m.speed)}</div>
      ${m.name === models.aktiv ? "" : `<div class="acts"><button>nehmen</button></div>`}
    </div></div>`).join("");
  $("#modelList").querySelectorAll("[data-model]").forEach((el) => {
    el.querySelector("button")?.addEventListener("click", async () => {
      await guard(() => api("/models", { method: "POST", body: { name: el.dataset.model } }));
      toast("Wird gewechselt."); LOADERS.more();
    });
  });
  $("#modelHint").textContent = models.pull.status === "laden"
    ? `Lädt ${models.pull.model}: ${models.pull.percent} %` : "";

  $("#statusBlock").innerHTML = [
    `Version ${status.version} (Stand ${status.built_at})`,
    `Modell: ${status.ollama.modell}${status.ollama.vorhanden ? "" : " (nicht geladen)"}`,
    `Notizen nach Sinn durchsuchbar: ${status.notizen.mit_vektor} von ${status.notizen.gesamt}`,
    `Internet: ${status.web ? "erlaubt" : "aus"}`,
  ].map((t) => `<div class="row"><div class="grow meta">${esc(t)}</div></div>`).join("");
};

$("#saveSettings").addEventListener("click", async () => {
  const body = {};
  Object.entries(SETTING_FIELDS).forEach(([sel, key]) => { body[key] = $(sel).value; });
  const capacity = {};
  $$("#capacityGrid input").forEach((i) => { capacity[i.dataset.day] = Number(i.value) || 0; });
  body.capacity_json = JSON.stringify(capacity);
  await guard(() => api("/settings", { method: "POST", body }));
  $("#settingsSaved").textContent = "gespeichert";
  setTimeout(() => { $("#settingsSaved").textContent = ""; }, 2500);
});
$("#profileRefresh").addEventListener("click", async () => {
  await guard(() => api("/profile", { method: "POST" })); LOADERS.more();
});

/* ------------------------------------------------------------------- Start */

refreshState();
showView("today");
setInterval(refreshState, 120000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
