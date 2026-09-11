/* Kompass — Oberflaeche. Vanilla JS, keine Abhaengigkeiten.
   Eine Regel zieht sich durch: Jede Ansicht laedt erst, wenn man sie
   oeffnet, und jede Aktion schreibt sofort zurueck. Kein Zwischenzustand,
   den man verlieren kann. */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const KIND_LABEL = {
  aufgabe: "Aufgabe", idee: "Idee", notiz: "Notiz", kauf: "Kauf",
  person: "Person", empfehlung: "Empfehlung", routine: "Routine",
};
const ENERGY_LABEL = { niedrig: "wenig Energie", mittel: "mittel", hoch: "volle Energie" };

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
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2600);
}

async function guard(fn) {
  try { return await fn(); }
  catch (e) { toast(e.message, true); throw e; }
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

function dayLabel(iso) {
  if (!iso) return "";
  const today = new Date().toISOString().slice(0, 10);
  if (iso === today) return "heute";
  const d = new Date(iso + "T12:00:00");
  const diff = Math.round((d - new Date(today + "T12:00:00")) / 86400000);
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
  $$("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  window.scrollTo({ top: 0 });
  if (LOADERS[name]) LOADERS[name]();
}

$$("nav.tabs button").forEach((b) =>
  b.addEventListener("click", () => showView(b.dataset.view)));

/* ---------------------------------------------------- Ein Feld fuer alles */

async function capture() {
  const input = $("#captureInput");
  const raw = input.value.trim();
  if (!raw) return;
  input.value = "";
  await guard(async () => {
    const item = await api("/inbox", { method: "POST", body: { raw } });
    toast("Drin. Kompass schaut es sich an.");
    refreshInboxDot();
    api(`/inbox/${item.id}/suggest`, { method: "POST" })
      .then(() => { if (currentView === "inbox") LOADERS.inbox(); refreshInboxDot(); })
      .catch(() => {});
  });
}
$("#captureBtn").addEventListener("click", capture);
$("#captureInput").addEventListener("keydown", (e) => { if (e.key === "Enter") capture(); });

async function refreshInboxDot() {
  try {
    const s = await api("/status");
    $("#inboxDot").hidden = !s.inbox;
    const badge = $("#statusBadge");
    badge.textContent = s.ollama.erreichbar ? s.ollama.modell : "kein Modell";
    badge.className = "badge " + (s.ollama.erreichbar ? "ok" : "err");
  } catch (e) { /* beim Start egal */ }
}

/* ------------------------------------------------------------------ HEUTE */

let briefingSlot = new Date().getHours() >= 18 ? "evening" : "morning";

LOADERS.today = async function () {
  const [state, events] = await Promise.all([api("/today"), api("/events?limit=8")]);
  renderCapacity(state);
  renderTodayTasks(state.tasks);
  renderTodayRoutines(state.routines);
  $("#eventList").innerHTML = events.length
    ? events.map((e) => `<div class="row"><div class="grow">${esc(e.text)}
        <div class="meta">${esc(e.at)}</div></div></div>`).join("")
    : `<div class="empty">Noch nichts. Was Kompass selbst umstellt, steht hier.</div>`;
  loadDecisions();
  loadBriefing(false);
};

function renderCapacity(state) {
  const pct = state.capacity_min ? Math.min(140, state.used_min / state.capacity_min * 100) : 0;
  const fill = $("#capacityFill");
  fill.style.width = Math.min(100, pct) + "%";
  fill.classList.toggle("over", state.used_min > state.capacity_min);
  const over = state.used_min - state.capacity_min;
  $("#capacityText").textContent = state.capacity_min
    ? (over > 0
      ? `${state.used_min} von ${state.capacity_min} Minuten — ${over} zu viel. Streich etwas.`
      : `${state.used_min} von ${state.capacity_min} Minuten verplant.`)
    : "Für heute ist keine Zeit hinterlegt (unter Mehr).";
}

function taskRow(t, compact = false) {
  const meta = [
    t.est_min ? `${t.est_min} min` : null,
    t.due_date ? `fällig ${dayLabel(t.due_date)}` : null,
    t.project_title ? esc(t.project_title) : null,
    !compact && t.context ? esc(t.context) : null,
    !compact && t.energy !== "mittel" ? ENERGY_LABEL[t.energy] : null,
    t.snoozes > 1 ? `${t.snoozes}× verschoben` : null,
  ].filter(Boolean).join(" · ");
  const late = t.due_date && t.due_date < new Date().toISOString().slice(0, 10);
  return `<div class="row" data-task="${t.id}">
    <button class="check" data-act="done" title="Erledigt"></button>
    <div class="grow">
      <span class="title">${esc(t.title)}</span>
      <div class="meta">${meta}${late ? " · überfällig" : ""}</div>
    </div>
    <div class="row-actions">
      <button class="btn small ghost" data-act="snooze" title="Auf morgen">+1 Tag</button>
      <button class="btn small ghost danger" data-act="delete" title="Löschen">✕</button>
    </div>
  </div>`;
}

function renderTodayTasks(list) {
  const box = $("#todayTasks");
  box.innerHTML = list.length ? list.map((t) => taskRow(t, true)).join("")
    : `<div class="empty">Nichts geplant. Wirf oben etwas rein oder plan neu.</div>`;
  bindTaskRows(box, () => LOADERS.today());
}

function bindTaskRows(box, after) {
  box.querySelectorAll("[data-task]").forEach((row) => {
    const id = row.dataset.task;
    row.querySelector('[data-act="done"]')?.addEventListener("click", async () => {
      row.classList.add("done");
      await guard(() => api(`/tasks/${id}/done`, { method: "POST" }));
      after();
    });
    row.querySelector('[data-act="snooze"]')?.addEventListener("click", async () => {
      await guard(() => api(`/tasks/${id}/snooze?days=1`, { method: "POST" }));
      toast("Auf morgen geschoben.");
      after();
    });
    row.querySelector('[data-act="delete"]')?.addEventListener("click", async () => {
      await guard(() => api(`/tasks/${id}`, { method: "DELETE" }));
      after();
    });
  });
}

function routineRow(r) {
  const meta = [
    `${r.duration_min} min`,
    r.room ? esc(r.room) : null,
    r.overdue_days > 0 ? `seit ${plural(r.overdue_days, "Tag", "Tagen")} fällig` : "heute",
    `alle ${r.interval_days} Tage`,
  ].filter(Boolean).join(" · ");
  return `<div class="row" data-routine="${r.id}">
    <button class="check" data-act="done" title="Erledigt"></button>
    <div class="grow"><span class="title">${esc(r.title)}</span>
      <div class="meta">${meta}</div></div>
    <div class="row-actions">
      <button class="btn small ghost" data-act="snooze">+1 Tag</button>
    </div>
  </div>`;
}

function bindRoutineRows(box, after) {
  box.querySelectorAll("[data-routine]").forEach((row) => {
    const id = row.dataset.routine;
    row.querySelector('[data-act="done"]')?.addEventListener("click", async () => {
      row.classList.add("done");
      await guard(() => api(`/routines/${id}/done`, { method: "POST", body: {} }));
      after();
    });
    row.querySelector('[data-act="snooze"]')?.addEventListener("click", async () => {
      const r = await guard(() => api(`/routines/${id}/snooze?days=1`, { method: "POST" }));
      toast(r.skips === 0 && r.interval_days ? "Geschoben." : "Geschoben.");
      after();
    });
    row.querySelector('[data-act="delete"]')?.addEventListener("click", async () => {
      await guard(() => api(`/routines/${id}`, { method: "DELETE" }));
      after();
    });
  });
}

function renderTodayRoutines(list) {
  const box = $("#todayRoutines");
  box.innerHTML = list.length ? list.map(routineRow).join("")
    : `<div class="empty">Heute nichts fällig.</div>`;
  bindRoutineRows(box, () => LOADERS.today());
}

async function loadDecisions() {
  const [ideas, buys, meta, folks] = await Promise.all([
    api("/ideas?status=ripe"), api("/purchases?status=ready"),
    api("/purchases/meta"), api("/people/due"),
  ]);
  const parts = [];
  ideas.forEach((i) => parts.push(
    `<div class="row"><div class="grow"><span class="title">Idee: ${esc(i.title)}</span>
      <div class="meta">Karenz vorbei — entscheiden</div></div>
      <div class="row-actions"><button class="btn small" data-go="projects">Ansehen</button></div></div>`));
  buys.forEach((p) => parts.push(
    `<div class="row"><div class="grow"><span class="title">Kauf: ${esc(p.title)}</span>
      <div class="meta">Wartefrist vorbei${p.price_eur ? ` · ${p.price_eur} €` : ""}</div></div>
      <div class="row-actions"><button class="btn small" data-go="buy">Ansehen</button></div></div>`));
  (meta.nutzung_offen || []).forEach((p) => parts.push(
    `<div class="row"><div class="grow"><span class="title">Benutzt du „${esc(p.title)}“ noch?</span>
      <div class="meta">gekauft am ${esc(p.bought_at || "")}</div></div>
      <div class="row-actions"><button class="btn small" data-go="buy">Antworten</button></div></div>`));
  (folks.geburtstage || []).filter((p) => p.birthday_in <= 14).forEach((p) => parts.push(
    `<div class="row"><div class="grow"><span class="title">${esc(p.name)} hat Geburtstag</span>
      <div class="meta">in ${plural(p.birthday_in, "Tag", "Tagen")}</div></div>
      <div class="row-actions"><button class="btn small" data-go="people">Ansehen</button></div></div>`));
  (folks.fällig || []).slice(0, 3).forEach((p) => parts.push(
    `<div class="row"><div class="grow"><span class="title">${esc(p.name)} melden</span>
      <div class="meta">seit ${plural(p.days_since, "Tag", "Tagen")} nichts gehört</div></div>
      <div class="row-actions"><button class="btn small" data-go="people">Ansehen</button></div></div>`));

  const card = $("#decisionsCard");
  card.hidden = parts.length === 0;
  $("#decisions").innerHTML = parts.join("");
  $("#decisions").querySelectorAll("[data-go]").forEach((b) =>
    b.addEventListener("click", () => showView(b.dataset.go)));
}

async function loadBriefing(force) {
  const box = $("#briefingText");
  $("#briefingTitle").textContent = briefingSlot === "evening" ? "Heute Abend" : "Heute früh";
  $$("[data-slot]").forEach((b) => b.classList.toggle("accent", b.dataset.slot === briefingSlot));
  if (force) box.textContent = "Kompass denkt nach …";
  try {
    const data = await api(`/briefing?slot=${briefingSlot}&force=${force ? "true" : "false"}`);
    box.textContent = data.text;
  } catch (e) {
    box.textContent = "Das Briefing kam nicht durch: " + e.message;
  }
}
$$("[data-slot]").forEach((b) => b.addEventListener("click", () => {
  briefingSlot = b.dataset.slot; loadBriefing(false);
}));
$("#briefingRefresh").addEventListener("click", () => loadBriefing(true));
$("#replanBtn").addEventListener("click", async () => {
  const plan = await guard(() => api("/today/plan", { method: "POST" }));
  toast(`Neu gelegt: ${plan.tasks.length} Aufgaben, ${plan.routines.length} Haushalt.`);
  LOADERS.today();
});

/* Abend-Check-in */
let checkinValues = { mood: null, energy: null };
function buildScale(id, key) {
  const box = $(id);
  box.innerHTML = [1, 2, 3, 4, 5].map((n) => `<button data-v="${n}">${n}</button>`).join("");
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    checkinValues[key] = Number(b.dataset.v);
    box.querySelectorAll("button").forEach((o) => o.classList.toggle("on", o === b));
  }));
}
buildScale("#scaleMood", "mood");
buildScale("#scaleEnergy", "energy");
$("#checkinSave").addEventListener("click", async () => {
  await guard(() => api("/checkin", {
    method: "POST",
    body: { mood: checkinValues.mood, energy: checkinValues.energy, note: $("#checkinNote").value },
  }));
  toast("Notiert.");
  $("#checkinNote").value = "";
});

/* ------------------------------------------------------------------ INBOX */

let inboxStatus = "new";
LOADERS.inbox = async function () {
  const items = await api(`/inbox?status=${inboxStatus}`);
  const box = $("#inboxList");
  if (!items.length) {
    box.innerHTML = `<div class="empty">Leer. Genau so soll es aussehen.</div>`;
    return;
  }
  box.innerHTML = items.map((item) => {
    const s = item.suggestion || {};
    const kind = s.art || item.kind || "aufgabe";
    const opts = Object.entries(KIND_LABEL).map(([k, label]) =>
      `<option value="${k}"${k === kind ? " selected" : ""}>${label}</option>`).join("");
    if (inboxStatus !== "new") {
      return `<div class="row"><div class="grow"><span class="title">${esc(item.raw)}</span>
        <div class="meta">${esc(KIND_LABEL[item.kind] || item.status)} · ${esc(item.sorted_at || "")}</div></div></div>`;
    }
    return `<div class="row" data-inbox="${item.id}">
      <div class="grow">
        <span class="title">${esc(item.raw)}</span>
        <div class="meta">${s.begründung ? esc(s.begründung) : "noch nicht eingeschätzt"}</div>
        <div class="form-grid">
          <select data-f="kind">${opts}</select>
          <input data-f="titel" class="span2" value="${esc(s.titel || item.raw)}">
        </div>
        <div class="row-actions spread">
          <button class="btn small accent" data-act="apply">Übernehmen</button>
          <button class="btn small ghost" data-act="dismiss">Weg</button>
        </div>
      </div>
    </div>`;
  }).join("");

  box.querySelectorAll("[data-inbox]").forEach((row) => {
    const id = row.dataset.inbox;
    row.querySelector('[data-act="apply"]')?.addEventListener("click", async () => {
      const kind = row.querySelector('[data-f="kind"]').value;
      const titel = row.querySelector('[data-f="titel"]').value;
      const res = await guard(() => api(`/inbox/${id}/apply`,
        { method: "POST", body: { kind, fields: { titel } } }));
      toast(`Als ${KIND_LABEL[res.kind]} angelegt.`);
      LOADERS.inbox(); refreshInboxDot();
    });
    row.querySelector('[data-act="dismiss"]')?.addEventListener("click", async () => {
      await guard(() => api(`/inbox/${id}/dismiss`, { method: "POST" }));
      LOADERS.inbox(); refreshInboxDot();
    });
  });
};
$("#sortAllBtn").addEventListener("click", async () => {
  toast("Kompass sieht sie durch …");
  await guard(() => api("/inbox/sort", { method: "POST" }));
  LOADERS.inbox();
});
$("#inboxHistoryBtn").addEventListener("click", () => {
  inboxStatus = inboxStatus === "new" ? "sorted" : "new";
  $("#inboxHistoryBtn").textContent = inboxStatus === "new" ? "Erledigte zeigen" : "Offene zeigen";
  LOADERS.inbox();
});

/* --------------------------------------------------------------- AUFGABEN */

LOADERS.tasks = async function () {
  const status = $("#taskFilterStatus").value;
  const energy = $("#taskFilterEnergy").value;
  const context = $("#taskFilterContext").value;
  const qs = new URLSearchParams({ status });
  if (energy) qs.set("energy", energy);
  if (context) qs.set("context", context);
  const [list, projects] = await Promise.all([api("/tasks?" + qs), api("/projects")]);
  const box = $("#taskList");
  box.innerHTML = list.length ? list.map((t) => taskRow(t)).join("")
    : `<div class="empty">Nichts da.</div>`;
  bindTaskRows(box, () => LOADERS.tasks());
  $("#taskProject").innerHTML = `<option value="">ohne Projekt</option>`
    + projects.map((p) => `<option value="${p.id}">${esc(p.title)}</option>`).join("");
};
["#taskFilterStatus", "#taskFilterEnergy", "#taskFilterContext"].forEach((s) =>
  $(s).addEventListener("change", () => LOADERS.tasks()));

$("#taskAdd").addEventListener("click", async () => {
  const title = $("#taskTitle").value.trim();
  if (!title) return toast("Ohne Titel geht es nicht.", true);
  await guard(() => api("/tasks", {
    method: "POST",
    body: {
      title, est_min: Number($("#taskMin").value) || 15,
      energy: $("#taskEnergy").value, context: $("#taskContext").value || null,
      due_date: $("#taskDue").value || null,
      project_id: Number($("#taskProject").value) || null,
    },
  }));
  $("#taskTitle").value = ""; $("#taskMin").value = ""; $("#taskDue").value = "";
  toast("Angelegt.");
  LOADERS.tasks();
});

/* --------------------------------------------------------------- PROJEKTE */

LOADERS.projects = async function () {
  const [slots, projects, ideas, settings] = await Promise.all([
    api("/projects/slots"), api("/projects"), api("/ideas"), api("/settings"),
  ]);
  const s = slots.slots;
  const badge = $("#slotBadge");
  badge.textContent = `${s.used} von ${s.limit} Plätzen`;
  badge.className = "pill " + (s.free ? "good" : "warn");
  $("#cooldownHint").textContent = `Karenz: ${settings.idea_cooldown_days} Tage`;

  $("#projectList").innerHTML = projects.length ? projects.map((p) => `
    <div class="row" data-project="${p.id}">
      <div class="grow">
        <span class="title">${esc(p.title)}</span>
        <div class="meta">${[
          p.next_action ? "nächster Schritt: " + esc(p.next_action) : "kein nächster Schritt",
          `${p.open_tasks} offen`,
          p.deadline ? "bis " + dayLabel(p.deadline) : null,
          p.stale_days >= 10 ? `seit ${p.stale_days} Tagen nichts passiert` : null,
        ].filter(Boolean).join(" · ")}</div>
      </div>
      <div class="row-actions">
        <button class="btn small ghost" data-act="next">Schritt</button>
        <button class="btn small ghost" data-act="done">Fertig</button>
        <button class="btn small ghost danger" data-act="drop">✕</button>
      </div>
    </div>`).join("")
    : `<div class="empty">Kein Projekt aktiv. Das ist kein Mangel.</div>`;

  $("#projectList").querySelectorAll("[data-project]").forEach((row) => {
    const id = row.dataset.project;
    row.querySelector('[data-act="next"]').addEventListener("click", async () => {
      const value = prompt("Was ist der nächste konkrete Schritt?");
      if (value === null) return;
      await guard(() => api(`/projects/${id}`, { method: "PATCH", body: { next_action: value } }));
      LOADERS.projects();
    });
    row.querySelector('[data-act="done"]').addEventListener("click", async () => {
      await guard(() => api(`/projects/${id}`, { method: "PATCH", body: { status: "done" } }));
      toast("Abgeschlossen — ein Platz ist frei.");
      LOADERS.projects();
    });
    row.querySelector('[data-act="drop"]').addEventListener("click", async () => {
      if (!confirm("Projekt verwerfen?")) return;
      await guard(() => api(`/projects/${id}`, { method: "PATCH", body: { status: "dropped" } }));
      LOADERS.projects();
    });
  });

  renderIdeas(ideas);
};

function renderIdeas(ideas) {
  const open = ideas.filter((i) => ["parked", "ripe"].includes(i.status));
  const box = $("#ideaList");
  if (!open.length) {
    box.innerHTML = `<div class="empty">Parkplatz leer.</div>`;
    return;
  }
  box.innerHTML = open.map((i) => {
    const ripe = i.status === "ripe" || i.is_ripe;
    return `<div class="row" data-idea="${i.id}">
      <div class="grow">
        <span class="title">${esc(i.title)}</span>
        <div class="meta">${ripe ? "reif — entscheide" : `noch ${plural(i.days_left, "Tag", "Tage")} Karenz`}${
          i.revived ? ` · ${i.revived}× vertagt` : ""}</div>
        ${i.ai_take ? `<div class="take">${esc(i.ai_take)}</div>` : ""}
        <div data-panel></div>
      </div>
      <div class="row-actions">
        ${ripe ? `<button class="btn small" data-act="review">Bewerten</button>
                  <button class="btn small accent" data-act="promote">Projekt</button>` : ""}
        <button class="btn small ghost" data-act="sleep">Vertagen</button>
        <button class="btn small ghost danger" data-act="drop">✕</button>
      </div>
    </div>`;
  }).join("");

  box.querySelectorAll("[data-idea]").forEach((row) => {
    const id = row.dataset.idea;
    row.querySelector('[data-act="drop"]').addEventListener("click", async () => {
      await guard(() => api(`/ideas/${id}/drop`, { method: "POST" }));
      toast("Weg damit."); LOADERS.projects();
    });
    row.querySelector('[data-act="sleep"]').addEventListener("click", async () => {
      await guard(() => api(`/ideas/${id}/sleep?days=30`, { method: "POST" }));
      toast("Nochmal 30 Tage."); LOADERS.projects();
    });
    row.querySelector('[data-act="review"]')?.addEventListener("click", () => openRitual(row, id));
    row.querySelector('[data-act="promote"]')?.addEventListener("click", () => promoteIdea(id));
  });
}

async function openRitual(row, id) {
  const panel = row.querySelector("[data-panel]");
  if (panel.innerHTML) { panel.innerHTML = ""; return; }
  const questions = await api("/ideas/questions");
  panel.innerHTML = `<div class="panel">
    <h4>Vier unbequeme Fragen</h4>
    ${questions.map((q) => `<div class="q"><span>${esc(q.frage)}</span>
      <input data-q="${q.key}"></div>`).join("")}
    <button class="btn accent small" data-act="submit">Einschätzen lassen</button>
  </div>`;
  panel.querySelector('[data-act="submit"]').addEventListener("click", async () => {
    const answers = {};
    panel.querySelectorAll("[data-q]").forEach((i) => { answers[i.dataset.q] = i.value; });
    panel.innerHTML = `<div class="panel">Kompass denkt nach …</div>`;
    await guard(() => api(`/ideas/${id}/review`, { method: "POST", body: { answers } }));
    LOADERS.projects();
  });
}

async function promoteIdea(id) {
  try {
    await api(`/ideas/${id}/promote`, { method: "POST", body: {} });
    toast("Läuft jetzt als Projekt.");
  } catch (e) {
    const reason = prompt(e.message + "\n\nWenn es trotzdem sein muss: warum?");
    if (!reason) return;
    await guard(() => api(`/ideas/${id}/promote`,
      { method: "POST", body: { override_reason: reason } }));
    toast("Gestartet — mit Begründung im Protokoll.");
  }
  LOADERS.projects();
}

$("#projAdd").addEventListener("click", async () => {
  const body = {
    title: $("#projTitle").value.trim(), why: $("#projWhy").value,
    next_action: $("#projNext").value, deadline: $("#projDeadline").value || null,
  };
  if (!body.title) return toast("Ohne Titel geht es nicht.", true);
  try {
    await api("/projects", { method: "POST", body });
  } catch (e) {
    const reason = prompt(e.message + "\n\nTrotzdem starten? Dann sag warum.");
    if (!reason) return;
    await guard(() => api("/projects", { method: "POST", body: { ...body, override_reason: reason } }));
  }
  $("#projTitle").value = ""; $("#projWhy").value = ""; $("#projNext").value = "";
  LOADERS.projects();
});

/* --------------------------------------------------------------- HAUSHALT */

LOADERS.home = async function () {
  const [due, all, stats] = await Promise.all([
    api("/routines/due"), api("/routines"), api("/routines/stats"),
  ]);
  const dueBox = $("#homeDue");
  dueBox.innerHTML = due.length ? due.map(routineRow).join("")
    : `<div class="empty">Heute nichts. Genieß es.</div>`;
  bindRoutineRows(dueBox, () => LOADERS.home());

  const allBox = $("#homeAll");
  const rooms = {};
  all.forEach((r) => { (rooms[r.room || "Ohne Raum"] ||= []).push(r); });
  allBox.innerHTML = Object.entries(rooms).map(([room, list]) =>
    `<div class="row"><div class="grow"><span class="title">${esc(room)}</span>
      <div class="meta">${list.map((r) =>
        `${esc(r.title)} (alle ${r.interval_days} T)`).join(" · ")}</div></div></div>`
  ).join("");

  const z = stats.zahlen;
  $("#homeStats").textContent =
    `${z.fällig} fällig · ${z.woche_erledigt} diese Woche erledigt`;
};

$("#routAdd").addEventListener("click", async () => {
  const title = $("#routTitle").value.trim();
  if (!title) return toast("Ohne Titel geht es nicht.", true);
  await guard(() => api("/routines", {
    method: "POST",
    body: {
      title, room: $("#routRoom").value || null,
      interval_days: Number($("#routInterval").value) || 7,
      duration_min: Number($("#routMin").value) || 10,
    },
  }));
  $("#routTitle").value = ""; $("#routRoom").value = "";
  $("#routInterval").value = ""; $("#routMin").value = "";
  LOADERS.home();
});

/* ------------------------------------------------------------------ KÄUFE */

LOADERS.buy = async function () {
  const [meta, waiting, ready] = await Promise.all([
    api("/purchases/meta"), api("/purchases?status=waiting"), api("/purchases?status=ready"),
  ]);
  const settings = await api("/settings");
  $("#buyRuleHint").textContent =
    `Ab ${settings.buy_threshold_small} € wartest du ${settings.buy_wait_small_h} Stunden, `
    + `ab ${settings.buy_threshold_big} € ganze ${Math.round(settings.buy_wait_big_h / 24)} Tage.`;

  const b = meta.budget;
  if (b.budget) {
    $("#budgetFill").style.width = Math.min(100, b.spent / b.budget * 100) + "%";
    $("#budgetFill").classList.toggle("over", b.spent > b.budget);
    $("#budgetText").textContent = `${b.spent.toFixed(0)} von ${b.budget.toFixed(0)} € diesen Monat.`;
  } else {
    $("#budgetFill").style.width = "0";
    $("#budgetText").textContent = `${b.spent.toFixed(0)} € diesen Monat ausgegeben. Kein Budget gesetzt.`;
  }
  const z = meta.zahlen;
  $("#buyStats").innerHTML = `
    <div><b>${z.wartet}</b>wartet</div>
    <div><b>${z.gekauft}</b>gekauft</div>
    <div><b>${z.verworfen}</b>verworfen</div>
    <div><b>${z.gespart.toFixed(0)} €</b>nicht ausgegeben</div>
    ${z.verwerfungsquote !== null ? `<div><b>${z.verwerfungsquote} %</b>wieder verworfen</div>` : ""}`;

  renderReady(ready, meta);
  $("#buyWaiting").innerHTML = waiting.length ? waiting.map((p) => `
    <div class="row"><div class="grow"><span class="title">${esc(p.title)}</span>
      <div class="meta">${p.price_eur ? p.price_eur + " € · " : ""}noch ${
        p.hours_left >= 24 ? plural(Math.round(p.hours_left / 24), "Tag", "Tage")
                           : plural(Math.round(p.hours_left), "Stunde", "Stunden")}</div></div>
    </div>`).join("") : `<div class="empty">Nichts auf der Warteliste.</div>`;

  const usage = meta.nutzung_offen || [];
  if (usage.length) {
    $("#buyHistory").innerHTML = usage.map((p) => `
      <div class="row" data-usage="${p.id}"><div class="grow">
        <span class="title">Benutzt du „${esc(p.title)}“?</span>
        <div class="meta">gekauft am ${esc(p.bought_at)}</div></div>
        <div class="row-actions">
          <button class="btn small" data-v="oft">oft</button>
          <button class="btn small" data-v="manchmal">manchmal</button>
          <button class="btn small" data-v="nie">nie</button>
        </div></div>`).join("");
    $("#buyHistory").querySelectorAll("[data-usage]").forEach((row) => {
      row.querySelectorAll("[data-v]").forEach((b) => b.addEventListener("click", async () => {
        await guard(() => api(`/purchases/${row.dataset.usage}/usage`,
          { method: "POST", body: { verdict: b.dataset.v } }));
        toast("Danke — das rechnet er dir beim nächsten Mal vor.");
        LOADERS.buy();
      }));
    });
  }
};

function renderReady(ready, meta) {
  const box = $("#buyReady");
  if (!ready.length) {
    box.innerHTML = `<div class="empty">Nichts zu entscheiden.</div>`;
    return;
  }
  box.innerHTML = ready.map((p) => `
    <div class="row" data-buy="${p.id}">
      <div class="grow">
        <span class="title">${esc(p.title)}${p.price_eur ? ` · ${p.price_eur} €` : ""}</span>
        <div class="meta">${esc(p.reason || "")}</div>
        ${p.ai_take ? `<div class="take">${esc(p.ai_take)}</div>` : ""}
        ${p.research && p.research.zusammenfassung
          ? `<div class="take">${esc(p.research.zusammenfassung)}</div>` : ""}
        <div data-panel></div>
      </div>
      <div class="row-actions">
        <button class="btn small" data-act="ask">Fragen</button>
        ${meta.web ? `<button class="btn small" data-act="research">Recherche</button>` : ""}
        <button class="btn small accent" data-act="bought">Gekauft</button>
        <button class="btn small ghost" data-act="dropped">Doch nicht</button>
      </div>
    </div>`).join("");

  box.querySelectorAll("[data-buy]").forEach((row) => {
    const id = row.dataset.buy;
    row.querySelector('[data-act="ask"]').addEventListener("click", async () => {
      const panel = row.querySelector("[data-panel]");
      if (panel.innerHTML) { panel.innerHTML = ""; return; }
      panel.innerHTML = `<div class="panel">
        ${meta.fragen.map((q) => `<div class="q"><span>${esc(q.frage)}</span>
          <input data-q="${q.key}"></div>`).join("")}
        <button class="btn accent small" data-act="submit">Einschätzen lassen</button></div>`;
      panel.querySelector('[data-act="submit"]').addEventListener("click", async () => {
        const answers = {};
        panel.querySelectorAll("[data-q]").forEach((i) => { answers[i.dataset.q] = i.value; });
        panel.innerHTML = `<div class="panel">Kompass denkt nach …</div>`;
        await guard(() => api(`/purchases/${id}/answer`, { method: "POST", body: { answers } }));
        LOADERS.buy();
      });
    });
    row.querySelector('[data-act="research"]')?.addEventListener("click", async () => {
      toast("Sucht …");
      await guard(() => api(`/purchases/${id}/research`, { method: "POST" }));
      LOADERS.buy();
    });
    row.querySelector('[data-act="bought"]').addEventListener("click", async () => {
      const price = prompt("Was hat es gekostet? (Euro)");
      if (price === null) return;
      await guard(() => api(`/purchases/${id}/decide`,
        { method: "POST", body: { verdict: "gekauft", price: price || null } }));
      LOADERS.buy();
    });
    row.querySelector('[data-act="dropped"]').addEventListener("click", async () => {
      await guard(() => api(`/purchases/${id}/decide`,
        { method: "POST", body: { verdict: "verworfen" } }));
      toast("Gespart.");
      LOADERS.buy();
    });
  });
}

$("#buyAdd").addEventListener("click", async () => {
  const title = $("#buyTitle").value.trim();
  if (!title) return toast("Was willst du denn haben?", true);
  const created = await guard(() => api("/purchases", {
    method: "POST",
    body: {
      title, price_eur: $("#buyPrice").value || null,
      url: $("#buyUrl").value || null, reason: $("#buyReason").value || null,
    },
  }));
  $("#buyTitle").value = ""; $("#buyPrice").value = "";
  $("#buyUrl").value = ""; $("#buyReason").value = "";
  toast(created.wait_hours
    ? `Auf die Warteliste — ${created.wait_hours} Stunden.`
    : "Unter der Schwelle, kein Warten nötig.");
  LOADERS.buy();
});
$("#buyHistoryBtn").addEventListener("click", async () => {
  const all = await api("/purchases?status=alle");
  const done = all.filter((p) => ["bought", "dropped"].includes(p.status));
  $("#buyHistory").innerHTML = done.length ? done.map((p) => `
    <div class="row"><div class="grow"><span class="title">${esc(p.title)}</span>
      <div class="meta">${p.status === "bought" ? "gekauft" : "verworfen"}${
        p.price_eur ? ` · ${p.price_eur} €` : ""}${
        p.usage_verdict ? ` · benutzt: ${p.usage_verdict}` : ""}</div></div></div>`).join("")
    : `<div class="empty">Noch nichts entschieden.</div>`;
});

/* ---------------------------------------------------------------- NOTIZEN */

let noteTimer = null;
LOADERS.notes = async function () {
  const q = $("#noteSearch").value.trim();
  const [list, status] = await Promise.all([
    api("/notes" + (q ? `?q=${encodeURIComponent(q)}` : "")), api("/status"),
  ]);
  $("#noteStats").textContent = status.notizen.semantisch
    ? `${status.notizen.gesamt} Notizen · ${status.notizen.mit_vektor} auch nach Sinn durchsuchbar`
    : `${status.notizen.gesamt} Notizen · nur Wortsuche`;
  const box = $("#noteList");
  box.innerHTML = list.length ? list.map((n) => `
    <div class="row" data-note="${n.id}">
      <div class="grow"><span class="title">${esc(n.title || "ohne Titel")}</span>
        <div class="meta">${esc((n.body || "").slice(0, 160))}${
          n.match ? ` · Treffer: ${n.match}` : ""}</div></div>
      <div class="row-actions">
        <button class="btn small ghost danger" data-act="delete">✕</button>
      </div>
    </div>`).join("") : `<div class="empty">Nichts gefunden.</div>`;
  box.querySelectorAll("[data-note]").forEach((row) => {
    row.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      await guard(() => api(`/notes/${row.dataset.note}`, { method: "DELETE" }));
      LOADERS.notes();
    });
  });
};
$("#noteSearch").addEventListener("input", () => {
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => LOADERS.notes(), 350);
});
$("#noteAdd").addEventListener("click", async () => {
  const body = $("#noteBody").value.trim();
  if (!body) return toast("Leere Notiz bringt nichts.", true);
  await guard(() => api("/notes", {
    method: "POST",
    body: { title: $("#noteTitle").value, body, tags: $("#noteTags").value },
  }));
  $("#noteTitle").value = ""; $("#noteBody").value = ""; $("#noteTags").value = "";
  toast("Gespeichert.");
  LOADERS.notes();
});

/* ----------------------------------------------------------- EMPFEHLUNGEN */

LOADERS.recs = async function () {
  const meta = await api("/recs/meta");
  const options = Object.entries(meta.sorten).map(([k, v]) =>
    `<option value="${k}">${v}</option>`).join("");
  if (!$("#recKind").innerHTML) {
    $("#recKind").innerHTML = options;
    $("#recAddKind").innerHTML = options;
  }
  const list = await api(`/recs?status=${$("#recFilter").value}`);
  const box = $("#recList");
  box.innerHTML = list.length ? list.map((r) => `
    <div class="row" data-rec="${r.id}">
      <div class="grow"><span class="title">${esc(r.title)}</span>
        <div class="meta">${[meta.sorten[r.kind], r.creator, r.year,
          r.rating ? `${r.rating}/5` : null].filter(Boolean).map(esc).join(" · ")}</div>
        ${r.why ? `<div class="meta">${esc(r.why)}</div>` : ""}</div>
      <div class="row-actions">
        ${r.status !== "done" ? `<button class="btn small" data-act="done">Durch</button>` : ""}
        ${r.status === "done" ? [1,2,3,4,5].map((n) =>
          `<button class="btn small ghost" data-rate="${n}">${n}</button>`).join("") : ""}
        <button class="btn small ghost danger" data-act="delete">✕</button>
      </div>
    </div>`).join("") : `<div class="empty">Liste leer.</div>`;
  box.querySelectorAll("[data-rec]").forEach((row) => {
    const id = row.dataset.rec;
    row.querySelector('[data-act="done"]')?.addEventListener("click", async () => {
      await guard(() => api(`/recs/${id}`, { method: "PATCH", body: { status: "done" } }));
      LOADERS.recs();
    });
    row.querySelectorAll("[data-rate]").forEach((b) => b.addEventListener("click", async () => {
      await guard(() => api(`/recs/${id}`, { method: "PATCH", body: { rating: Number(b.dataset.rate) } }));
      toast("Gemerkt — das schärft die nächsten Vorschläge.");
      LOADERS.recs();
    }));
    row.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      await guard(() => api(`/recs/${id}`, { method: "DELETE" }));
      LOADERS.recs();
    });
  });
};
$("#recFilter").addEventListener("change", () => LOADERS.recs());
$("#recSuggest").addEventListener("click", async () => {
  $("#recSuggestions").innerHTML = `<div class="empty">Kompass überlegt …</div>`;
  const data = await guard(() => api("/recs/suggest", {
    method: "POST",
    body: { kind: $("#recKind").value, hint: $("#recHint").value || null },
  }));
  const list = data.vorschläge || [];
  $("#recSuggestions").innerHTML = list.length ? list.map((r, i) => `
    <div class="row" data-sug="${i}">
      <div class="grow"><span class="title">${esc(r.title)}</span>
        <div class="meta">${[r.creator, r.year, r.verified ? "belegt" : "ungeprüft"]
          .filter(Boolean).map(esc).join(" · ")}</div>
        ${r.why ? `<div class="meta">${esc(r.why)}</div>` : ""}</div>
      <div class="row-actions"><button class="btn small accent" data-act="keep">Merken</button></div>
    </div>`).join("") : `<div class="empty">Nichts gekommen — läuft das Modell?</div>`;
  $("#recSuggestions").querySelectorAll("[data-sug]").forEach((row) => {
    row.querySelector('[data-act="keep"]').addEventListener("click", async () => {
      const r = list[Number(row.dataset.sug)];
      await guard(() => api("/recs", { method: "POST", body: { ...r, source: "kompass" } }));
      row.remove(); toast("Auf der Liste."); LOADERS.recs();
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
  $("#peopleDue").innerHTML = (due.fällig.length || due.geburtstage.length)
    ? [...due.fällig.map((p) => personRow(p, `seit ${plural(p.days_since, "Tag", "Tagen")} nichts gehört`)),
       ...due.geburtstage.filter((p) => p.birthday_in <= 30)
         .map((p) => personRow(p, `Geburtstag in ${plural(p.birthday_in, "Tag", "Tagen")}`))].join("")
    : `<div class="empty">Alles im Lot.</div>`;
  $("#peopleList").innerHTML = all.length
    ? all.map((p) => personRow(p, [
        p.cadence_days ? `alle ${p.cadence_days} Tage` : "ohne Rhythmus",
        p.last_contact ? `zuletzt ${dayLabel(p.last_contact)}` : "noch nie eingetragen",
        p.note ? esc(p.note) : null,
      ].filter(Boolean).join(" · "))).join("")
    : `<div class="empty">Noch niemand eingetragen.</div>`;
  bindPeople($("#peopleDue"));
  bindPeople($("#peopleList"));
};

function personRow(p, meta) {
  return `<div class="row" data-person="${p.id}">
    <div class="grow"><span class="title">${esc(p.name)}</span>
      <div class="meta">${meta}</div></div>
    <div class="row-actions">
      <button class="btn small" data-act="contact">Gemeldet</button>
      <button class="btn small ghost danger" data-act="delete">✕</button>
    </div></div>`;
}

function bindPeople(box) {
  box.querySelectorAll("[data-person]").forEach((row) => {
    const id = row.dataset.person;
    row.querySelector('[data-act="contact"]').addEventListener("click", async () => {
      const what = prompt("Worum ging es? (optional)") ?? "";
      await guard(() => api(`/people/${id}/contact`, { method: "POST", body: { what } }));
      toast("Notiert."); LOADERS.people();
    });
    row.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      if (!confirm("Person löschen?")) return;
      await guard(() => api(`/people/${id}`, { method: "DELETE" }));
      LOADERS.people();
    });
  });
}

$("#perAdd").addEventListener("click", async () => {
  const name = $("#perName").value.trim();
  if (!name) return toast("Name fehlt.", true);
  await guard(() => api("/people", {
    method: "POST",
    body: {
      name, birthday: $("#perBirthday").value || null,
      cadence_days: Number($("#perCadence").value) || null,
      note: $("#perNote").value || null,
    },
  }));
  $("#perName").value = ""; $("#perBirthday").value = "";
  $("#perCadence").value = ""; $("#perNote").value = "";
  LOADERS.people();
});

/* ------------------------------------------------------------------ FRAGEN */

LOADERS.chat = async function () {
  const log = await api("/chat");
  renderChat(log);
};
function renderChat(log) {
  const box = $("#chatLog");
  box.innerHTML = log.length ? log.map((m) =>
    `<div class="msg ${m.role}">${esc(m.content)}</div>`).join("")
    : `<div class="empty">Frag ihn etwas — er kennt deinen Stand.</div>`;
  box.scrollTop = box.scrollHeight;
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
    const res = await api("/chat", { method: "POST", body: { message } });
    renderChat(res.history);
  } catch (e) {
    $("#pending").textContent = "Das ging schief: " + e.message;
  }
}
$("#chatSend").addEventListener("click", sendChat);
$("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
$("#chatClear").addEventListener("click", async () => {
  await guard(() => api("/chat", { method: "DELETE" }));
  LOADERS.chat();
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
  const [settings, status, profile, models] = await Promise.all([
    api("/settings"), api("/status"), api("/profile"), api("/models"),
  ]);
  Object.entries(SETTING_FIELDS).forEach(([sel, key]) => { $(sel).value = settings[key] ?? ""; });

  let capacity = {};
  try { capacity = JSON.parse(settings.capacity_json || "{}"); } catch (e) { capacity = {}; }
  $("#capacityGrid").innerHTML = WEEKDAYS.map((d) =>
    `<label>${d}<input type="number" min="0" data-day="${d}" value="${capacity[d] ?? 60}"></label>`).join("");

  $("#profileList").innerHTML = profile.length
    ? profile.map((f) => `<div class="row"><div class="grow">${esc(f.text)}</div></div>`).join("")
    : `<div class="empty">Noch zu wenig Daten. Nach ein paar Tagen steht hier etwas.</div>`;

  $("#modelList").innerHTML = models.presets.map((m) => `
    <div class="row" data-model="${esc(m.name)}">
      <div class="grow"><span class="title">${esc(m.label)}${
        m.name === models.aktiv ? " · aktiv" : ""}</span>
        <div class="meta">${m.size_gb} GB · ${esc(m.speed)} — ${esc(m.note)}</div></div>
      ${m.name === models.aktiv ? "" :
        `<div class="row-actions"><button class="btn small">Nehmen</button></div>`}
    </div>`).join("");
  $("#modelList").querySelectorAll("[data-model]").forEach((row) => {
    row.querySelector("button")?.addEventListener("click", async () => {
      await guard(() => api("/models", { method: "POST", body: { name: row.dataset.model } }));
      toast("Wird gewechselt — der Download läuft im Hintergrund.");
      LOADERS.more();
    });
  });
  const pull = models.pull;
  $("#modelHint").textContent = pull.status === "laden"
    ? `Lädt ${pull.model}: ${pull.percent} %`
    : (status.ollama.erreichbar ? "" : "Ollama ist nicht erreichbar — läuft der Container?");

  $("#statusBlock").innerHTML = [
    `Version ${status.version} (Stand ${status.built_at})`,
    `Modell: ${status.ollama.modell}${status.ollama.vorhanden ? "" : " (noch nicht geladen)"}`,
    `Einbettungen: ${status.ollama.einbettung || "aus"}`,
    `Internet: ${status.web ? "erlaubt" : "aus"}`,
    `Aufgaben offen: ${status.aufgaben.offen} · heute erledigt: ${status.aufgaben.heute_erledigt}`,
    `Haushalt fällig: ${status.haushalt.fällig} von ${status.haushalt.gesamt}`,
    `Projekte: ${status.projekte.used} von ${status.projekte.limit}`,
  ].map((t) => `<div class="row"><div class="grow">${esc(t)}</div></div>`).join("");
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
  await guard(() => api("/profile", { method: "POST" }));
  LOADERS.more();
});

/* -------------------------------------------------------------------- Start */

refreshInboxDot();
showView("today");
setInterval(refreshInboxDot, 120000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
