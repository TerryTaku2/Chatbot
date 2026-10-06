import { api } from "../api.js";
import { badge, confirmDialog, esc, fmtDateTime, formModal, handleError, icon, state, table, toast } from "../ui.js";

export default async function (el) {
  el.innerHTML = `
    <div class="page-head"><div><h1>User Accounts</h1><p>Teacher and parent logins are best created from the Staff and Guardians pages so they link to the right record.</p></div>
      <div class="page-actions"><button class="btn primary" id="add">${icon("plus")} New user</button></div></div>
    <div class="card"><div id="tbl"></div></div>`;
  const load = async () => {
    const { items } = await api.get("/users");
    table(el.querySelector("#tbl"), {
      rows: items,
      columns: [
        { key: "username", label: "Username", render: (u) => `<b>${esc(u.username)}</b>` },
        { key: "full_name", label: "Name" },
        { key: "role", label: "Role", render: (u) => `<span style="text-transform:capitalize">${esc(u.role)}</span>${u.staff_id ? ' <span class="muted small">· staff</span>' : u.guardian_id ? ' <span class="muted small">· guardian</span>' : ""}` },
        { key: "last_login", label: "Last login", render: (u) => fmtDateTime(u.last_login) },
        { key: "active", label: "Status", render: (u) => badge(u.active ? "active" : "void", u.active ? "active" : "disabled") },
        { key: "id", label: "", sort: false, cls: "actions", render: (u) => `<button class="btn sm" data-reset="${u.id}">Reset password</button> ${u.id === state.user.id ? "" : `<button class="btn sm ${u.active ? "danger" : ""}" data-toggle="${u.id}" data-active="${u.active}">${u.active ? "Disable" : "Enable"}</button>`}` },
      ],
    });
    el.querySelectorAll("[data-reset]").forEach((b) => (b.onclick = async () => {
      if (await formModal({ title: "Reset password", cols: 1, fields: [{ name: "password", label: "New password", type: "password", required: true, hint: "8+ characters, letters and numbers" }], onSubmit: (d) => api.put(`/users/${b.dataset.reset}`, d) })) toast("Password reset", "success");
    }));
    el.querySelectorAll("[data-toggle]").forEach((b) => (b.onclick = async () => {
      const enable = b.dataset.active !== "true";
      if (!enable && !(await confirmDialog("Disable this account? The user will no longer be able to sign in.", { danger: true, confirmText: "Disable" }))) return;
      try { await api.put(`/users/${b.dataset.toggle}`, { active: enable }); load(); } catch (err) { handleError(err); }
    }));
  };
  el.querySelector("#add").onclick = async () => {
    const r = await formModal({
      title: "New user account",
      fields: [{ name: "full_name", label: "Full name", required: true }, { name: "email", label: "Email", type: "email" },
        { name: "username", label: "Username", required: true }, { name: "password", label: "Password", type: "password", required: true, hint: "8+ characters, letters and numbers" },
        { name: "role", label: "Role", type: "select", required: true, options: [{ value: "admin", label: "Administrator" }, { value: "bursar", label: "Bursar" }] }],
      onSubmit: (d) => api.post("/users", d),
    });
    if (r) { toast("User created", "success"); load(); }
  };
  await load();
}
