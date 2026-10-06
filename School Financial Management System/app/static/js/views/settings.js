import { api } from "../api.js";
import { refreshMeta } from "../app.js";
import { badge, confirmDialog, esc, fmtDate, formModal, handleError, icon, table, toast } from "../ui.js";

export default async function (el) {
  el.innerHTML = `
    <div class="page-head"><div><h1>Settings</h1><p>Academic calendar, grading scale and end-of-year promotion</p></div></div>
    <div class="tabs"><button data-tab="calendar" class="active">Academic calendar</button><button data-tab="grading">Grading scale</button><button data-tab="promotion">Promotion</button></div>
    <div id="pane"></div>`;
  const pane = el.querySelector("#pane");

  const calendar = async () => {
    const { items } = await api.get("/years");
    pane.innerHTML = `<div class="row" style="justify-content:flex-end;margin-bottom:12px"><button class="btn primary" id="add-year">${icon("plus")} New academic year</button></div>
      <div class="stack">${items.map((y) => `<div class="card"><div class="card-head"><div><h3>${esc(y.name)} ${y.is_current ? badge("active", "current") : ""}</h3><div class="sub">${fmtDate(y.start_date)} – ${fmtDate(y.end_date)}</div></div>
        <button class="btn sm" data-term="${y.id}" data-start="${y.start_date}" data-end="${y.end_date}">${icon("plus")} Add term</button></div>
        <ul class="list">${y.terms.map((t) => `<li><span><b>${esc(t.name)}</b> <span class="muted small">${fmtDate(t.start_date)} – ${fmtDate(t.end_date)}</span></span>
          <span class="row">${t.is_current ? badge("active", "current term") : `<button class="btn sm" data-current="${t.id}">Make current</button><button class="btn sm danger" data-del="${t.id}">Delete</button>`}</span></li>`).join("") || `<li class="muted">No terms yet.</li>`}</ul></div>`).join("") || `<div class="card empty">No academic years configured.</div>`}</div>`;
    pane.querySelector("#add-year").onclick = async () => {
      if (await formModal({ title: "New academic year", fields: [{ name: "name", label: "Name", required: true, placeholder: "e.g. 2027" }, { type: "heading", name: "_", label: "" },
        { name: "start_date", label: "Starts", type: "date", required: true }, { name: "end_date", label: "Ends", type: "date", required: true }], onSubmit: (d) => api.post("/years", d) })) { toast("Year created", "success"); calendar(); }
    };
    pane.querySelectorAll("[data-term]").forEach((b) => (b.onclick = async () => {
      if (await formModal({ title: "Add term", fields: [{ name: "name", label: "Name", required: true, placeholder: "e.g. Term 1", full: true },
        { name: "start_date", label: "Starts", type: "date", required: true, min: b.dataset.start, max: b.dataset.end }, { name: "end_date", label: "Ends", type: "date", required: true, min: b.dataset.start, max: b.dataset.end }],
        onSubmit: (d) => api.post("/terms", { ...d, year_id: b.dataset.term }) })) { toast("Term added", "success"); await refreshMeta(); calendar(); }
    }));
    pane.querySelectorAll("[data-current]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog("Switch the current term? Dashboards, attendance and fees default to the current term.", { confirmText: "Switch" }))) return;
      await api.put(`/terms/${b.dataset.current}/current`).catch(handleError);
      await refreshMeta();
      calendar();
    }));
    pane.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog("Delete this term?", { danger: true, confirmText: "Delete" }))) return;
      try { await api.del(`/terms/${b.dataset.del}`); await refreshMeta(); calendar(); } catch (err) { handleError(err); }
    }));
  };

  const grading = async () => {
    let bands = (await api.get("/grade-bands")).items;
    const draw = () => {
      pane.innerHTML = `<div class="card" style="max-width:720px"><div class="card-head"><div><h3>Grade bands</h3><div class="sub">A score gets the highest band whose minimum it meets. One band must start at 0.</div></div></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Grade</th><th>Minimum %</th><th>Points</th><th>Remark</th><th></th></tr></thead><tbody>
        ${bands.map((b, i) => `<tr><td><input class="input" data-i="${i}" data-k="letter" value="${esc(b.letter)}" maxlength="3" style="width:70px"></td>
          <td><input class="input" type="number" min="0" max="100" data-i="${i}" data-k="min_score" value="${b.min_score}" style="width:100px"></td>
          <td><input class="input" type="number" min="0" step="0.5" data-i="${i}" data-k="points" value="${b.points}" style="width:90px"></td>
          <td><input class="input" data-i="${i}" data-k="remark" value="${esc(b.remark || "")}"></td>
          <td class="actions"><button class="btn sm ghost danger" data-rm="${i}" aria-label="Remove">✕</button></td></tr>`).join("")}</tbody></table></div>
        <div class="pager"><button class="btn sm" id="add-band">${icon("plus")} Add band</button><button class="btn primary" id="save">Save scale</button></div></div>`;
      pane.querySelectorAll("[data-k]").forEach((i) => (i.oninput = () => (bands[i.dataset.i][i.dataset.k] = i.value)));
      pane.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { bands.splice(+b.dataset.rm, 1); draw(); }));
      pane.querySelector("#add-band").onclick = () => { bands.push({ letter: "", min_score: 0, points: 0, remark: "" }); draw(); };
      pane.querySelector("#save").onclick = async () => {
        try { await api.put("/grade-bands", { bands }); toast("Grading scale saved", "success"); grading(); } catch (err) { handleError(err); }
      };
    };
    draw();
  };

  const promotion = async () => {
    const { items } = await api.get("/promotion/preview");
    const hold = new Set();
    const counts = items.reduce((a, p) => ((a[p.action] = (a[p.action] || 0) + 1), a), {});
    pane.innerHTML = `<div class="notice warn" style="margin-bottom:16px">Run this once at the end of the academic year, after final results are in. Every active student moves up one level (same stream where possible, respecting capacity); students in the top level graduate. Tick students who should repeat the year.</div>
      <div class="card"><div class="card-head"><div><h3>Promotion preview</h3><div class="sub">${counts.promote || 0} to promote · ${counts.graduate || 0} to graduate · ${counts.blocked || 0} blocked</div></div><button class="btn danger solid" id="run">Run promotion</button></div><div id="t"></div></div>`;
    table(pane.querySelector("#t"), {
      rows: items, empty: "No active students.",
      columns: [{ key: "hold", label: "Repeat", sort: false, render: (p) => `<input type="checkbox" data-hold="${p.student_id}" aria-label="Hold back ${esc(p.student)}">` },
        { key: "student", label: "Student" }, { key: "from", label: "Current class" },
        { key: "action", label: "Action", render: (p) => `${badge(p.action)}${p.reason ? ` <span class="muted small">${esc(p.reason)}</span>` : ""}` },
        { key: "to", label: "New class", render: (p) => esc(p.to || "—") }],
    });
    pane.querySelectorAll("[data-hold]").forEach((c) => (c.onchange = () => (c.checked ? hold.add(+c.dataset.hold) : hold.delete(+c.dataset.hold))));
    pane.querySelector("#run").onclick = async () => {
      const ok = await confirmDialog(`Promote all active students now? ${hold.size} student(s) will repeat. This cannot be undone automatically.`, { title: "Run promotion", danger: true, confirmText: "Promote", typed: "PROMOTE" });
      if (!ok) return;
      try {
        const r = await api.post("/promotion", { confirm: "PROMOTE", hold_back: [...hold] });
        toast(`Promoted ${r.promoted}, graduated ${r.graduated}, held back ${r.held_back}`, "success");
        promotion();
      } catch (err) { handleError(err); }
    };
  };

  const tabs = { calendar, grading, promotion };
  el.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => {
    el.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("active", x === b));
    tabs[b.dataset.tab]().catch(handleError);
  }));
  await calendar();
}
