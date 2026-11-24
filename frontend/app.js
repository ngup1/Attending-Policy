// Attending! Policy: Bills & Votes page. Talks to the FastAPI backend at /api.
(() => {
  const API = "/api";
  const TABLE_PREVIEW = 10;

  const state = {
    chamber: "all",
    q: "",
    votes: [],
    selectedId: null,
    detail: null,
    summaryOpen: false,
    memberQ: "",
    memberFilter: "all",
    showAllMembers: false,
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fmtDate = (iso) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const fmtNum = (n) => n.toLocaleString("en-US");
  const ordinal = (n) => {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  };
  const district = (d) => (d === null || d === undefined || d === 0 ? "At-large" : ordinal(d));
  const initials = (m) => ((m.first_name || "")[0] || "") + ((m.last_name || "")[0] || "");

  const store = {
    get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } },
  };

  async function getJSON(path) {
    const res = await fetch(API + path);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
      throw new Error(detail);
    }
    return res.json();
  }

  const ICONS = {
    calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="1"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    building: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6"/></svg>',
    external: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/></svg>',
    bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" aria-hidden="true" style="width:16px;height:16px"><path d="m9 6 6 6-6 6"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  };

  // --- Vote list ---------------------------------------------------------

  let searchTimer;
  async function loadList() {
    const list = $("#vote-list");
    list.innerHTML = '<li class="list-note">Loading…</li>';
    try {
      const params = new URLSearchParams({ chamber: state.chamber, q: state.q });
      const data = await getJSON(`/votes?${params}`);
      state.votes = data.results;
      renderList(data.note);
      const fromHash = location.hash.slice(1);
      const target = state.votes.find((v) => v.id === fromHash) || state.votes.find((v) => v.id === state.selectedId) || state.votes[0];
      if (target && target.id !== state.selectedId) selectVote(target.id, { replace: true });
      if (!target) renderEmptyDetail(data.note);
    } catch (err) {
      list.innerHTML = `<li class="list-note">Couldn't load votes: ${esc(err.message)}</li>`;
      $("#result-count").textContent = "";
    }
  }

  function renderList(note) {
    const list = $("#vote-list");
    $("#result-count").textContent = `${state.votes.length} result${state.votes.length === 1 ? "" : "s"}`;
    if (!state.votes.length) {
      list.innerHTML = `<li class="list-note">${esc(note || "No bills match your search.")}</li>`;
      return;
    }
    list.innerHTML = state.votes.map((v) => `
      <li class="vote-item">
        <button type="button" data-id="${esc(v.id)}" aria-current="${v.id === state.selectedId}">
          <div class="vi-top">
            <span class="vi-label">${esc(v.bill.label)}</span>
            ${v.bill.policy_area ? `<span class="tag" title="${esc(v.bill.policy_area)}">${esc(v.bill.policy_area)}</span>` : ""}
          </div>
          <div class="vi-title">${esc(v.bill.title)}</div>
          <div class="vi-bottom">
            <span>${fmtDate(v.date)}</span>
            <span class="vi-score">${v.totals.yea}–${v.totals.nay} ${ICONS.chevron}</span>
          </div>
        </button>
      </li>`).join("");
  }

  function markSelected() {
    document.querySelectorAll(".vote-item button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === state.selectedId)));
  }

  // --- Detail ------------------------------------------------------------

  async function selectVote(id, { replace = false } = {}) {
    state.selectedId = id;
    state.summaryOpen = false;
    state.memberQ = "";
    state.memberFilter = "all";
    state.showAllMembers = false;
    markSelected();
    history[replace ? "replaceState" : "pushState"](null, "", `#${id}`);

    const panel = $("#detail");
    panel.innerHTML = '<div class="placeholder">Loading vote…</div>';
    const [congress, session, roll] = id.split("-");
    try {
      const detail = await getJSON(`/votes/${congress}/${session}/${roll}`);
      if (state.selectedId !== id) return; // a newer click won
      state.detail = detail;
      renderDetail();
    } catch (err) {
      panel.innerHTML = `<div class="placeholder">Couldn't load this vote: ${esc(err.message)}</div>`;
    }
  }

  function renderEmptyDetail(note) {
    state.selectedId = null;
    $("#detail").innerHTML = `<div class="placeholder">${esc(note || "Select a vote to see how members voted.")}</div>`;
  }

  function statusClass(status) {
    if (status === "Became law") return "law";
    if (/fail|veto/i.test(status)) return "failed";
    return "";
  }

  function summaryHTML(bill) {
    const s = bill.summary;
    if (!s) {
      const a = bill.latest_action;
      return `<div class="summary"><p>No official summary has been published for this bill yet.${a ? ` Latest action (${esc(fmtDate(a.actionDate + "T12:00:00"))}): ${esc(a.text)}` : ""}</p></div>`;
    }
    const body = state.summaryOpen || !s.truncated
      ? s.paragraphs.map((p) => `<p>${esc(p)}</p>`).join("")
      : `<p>${esc(s.preview)}</p>`;
    const toggle = s.truncated
      ? `<button type="button" class="link-btn" data-action="toggle-summary" aria-expanded="${state.summaryOpen}">${state.summaryOpen ? "View less" : `View more (${fmtNum(s.word_count)} words)`}</button>`
      : "";
    return `<div class="summary" id="bill-summary">${body}${toggle}
      <div class="summary-source">Summary by the ${esc(s.source)}${s.version ? ` · ${esc(s.version)} version` : ""}</div></div>`;
  }

  function partyBy(d, code) { return d.party_totals.find((p) => p.party === code); }

  function glance(d) {
    const t = d.totals;
    const voting = t.yea + t.nay;
    const pct = voting ? Math.round((t.yea / voting) * 100) : 0;
    const D = partyBy(d, "D"), R = partyBy(d, "R");
    const share = (p) => (p && p.yea + p.nay ? p.yea / (p.yea + p.nay) : null);
    const dS = share(D), rS = share(R);

    let title = "Party-line vote", text = "";
    if (dS !== null && rS !== null) {
      if (dS > 0.5 && rS > 0.5) {
        title = "Bipartisan support";
        text = D.nay + R.nay === 0 ? "Every member voting from both parties said Yea." : `Most Democrats and most Republicans voted Yea; ${D.nay + R.nay} voted Nay.`;
      } else if (dS < 0.5 && rS < 0.5) {
        title = "Bipartisan opposition";
        text = "Most Democrats and most Republicans voted Nay.";
      } else {
        const [win, lose, wName, lName] = dS > rS ? [D, R, "Democrats", "Republicans"] : [R, D, "Republicans", "Democrats"];
        const cross = lose.yea;
        title = cross ? "Mostly party-line" : "Party-line vote";
        text = cross
          ? `${cross} ${cross === 1 ? lName.slice(0, -1) : lName} joined most ${wName} in voting Yea.`
          : `${wName} voted Yea; no ${lName} did.`;
      }
    }
    const r = 52, c = 2 * Math.PI * r;
    return `
      <p class="eyebrow">At a glance</p>
      <div class="glance-top">
        <div class="donut" role="img" aria-label="${pct}% of members voting said Yea">
          <svg viewBox="0 0 128 128"><circle cx="64" cy="64" r="${r}" stroke="#dfe5ee" stroke-width="12"/>
            <circle cx="64" cy="64" r="${r}" stroke="var(--navy-700)" stroke-width="12" stroke-linecap="butt" stroke-dasharray="${(c * pct) / 100} ${c}"/></svg>
          <b>${pct}%</b>
        </div>
        <div><h3>${esc(title)}</h3><p>${esc(text)}</p><p class="muted" style="font-size:13px;margin-top:6px">${pct}% of members voting said Yea</p></div>
      </div>
      <div class="party-rows">
        ${d.party_totals.map((p) => `
          <div class="party-row"><span><span class="dot" style="background:${p.party === "D" ? "var(--dem)" : p.party === "R" ? "var(--rep)" : "var(--gray)"}"></span>${esc(p.name || p.party)}</span>
          <strong>${p.yea} yea · ${p.nay} nay</strong></div>`).join("")}
      </div>`;
  }

  function finalVote(d) {
    const t = d.totals, all = t.yea + t.nay + t.present + t.not_voting || 1;
    const passed = /pass|agreed/i.test(d.result || "");
    const seg = (n, color) => (n ? `<span style="flex:${n};background:${color}" title="${n}"></span>` : "");
    const item = (label, n, color) => `<div><div class="k"><span class="sw" style="background:${color}"></span>${label}</div><div class="v">${n}</div></div>`;
    return `
      <p class="eyebrow">Final vote</p>
      <div class="score-row">
        <span class="score">${t.yea}–${t.nay}</span>
        <span class="result-badge ${passed ? "" : "failed"}">${esc(d.result || "")}</span>
      </div>
      <div class="bar" role="img" aria-label="${t.yea} yea, ${t.nay} nay, ${t.present} present, ${t.not_voting} not voting out of ${all}">
        ${seg(t.yea, "var(--dem)")}${seg(t.nay, "var(--rep)")}${seg(t.present, "#c9cfd9")}${seg(t.not_voting, "var(--gray)")}
      </div>
      <div class="legend3">
        ${item("Yea", t.yea, "var(--dem)")}${item("Nay", t.nay, "var(--rep)")}
        ${t.present ? item("Present", t.present, "#c9cfd9") : ""}${item("Not voting", t.not_voting, "var(--gray)")}
      </div>
      <p class="muted" style="font-size:14px;margin:18px 0 0">${esc(d.question || "")} · Roll call ${d.roll_call}</p>`;
  }

  // Seat colours by party and position.
  function seatColor(m) {
    if (m.vote === "Yea") return m.party === "R" ? "var(--rep)" : m.party === "D" ? "var(--dem)" : "#7d8597";
    if (m.vote === "Nay") return m.party === "R" ? "var(--rep-soft)" : m.party === "D" ? "var(--dem-dark)" : "#c3c8d2";
    return "#4b5568";
  }

  function hemicycle(members) {
    const W = 760, H = 390, cx = W / 2, cy = H - 10, rows = 12, rOuter = 370, rInner = 150;
    const radii = Array.from({ length: rows }, (_, i) => rInner + ((rOuter - rInner) * i) / (rows - 1));
    const total = members.length;
    const sumR = radii.reduce((a, b) => a + b, 0);
    const counts = radii.map((r) => Math.round((total * r) / sumR));
    counts[rows - 1] += total - counts.reduce((a, b) => a + b, 0);

    const seats = [];
    radii.forEach((r, i) => {
      const n = counts[i];
      for (let j = 0; j < n; j++) {
        const a = Math.PI - (Math.PI * j) / Math.max(n - 1, 1);
        seats.push({ a, x: cx + r * Math.cos(a), y: cy - r * Math.sin(a) });
      }
    });
    seats.sort((p, q) => q.a - p.a || p.x - q.x);

    const rank = { D: 0, I: 1, R: 2 };
    const dOrder = { "Not voting": 0, Present: 1, Nay: 2, Yea: 3 };
    const rOrder = { Yea: 0, Nay: 1, Present: 2, "Not voting": 3 };
    const ordered = [...members].sort((m1, m2) =>
      (rank[m1.party] ?? 1) - (rank[m2.party] ?? 1) ||
      (m1.party === "R" ? rOrder[m1.vote] - rOrder[m2.vote] : dOrder[m1.vote] - dOrder[m2.vote]) ||
      m1.last_name.localeCompare(m2.last_name));

    const dot = 7.2;
    return `<svg class="hemi" viewBox="0 0 ${W} ${H}" role="img" aria-label="Seat chart of ${total} House members, grouped by party and colored by vote">
      ${ordered.map((m, i) => `<circle cx="${seats[i].x.toFixed(1)}" cy="${seats[i].y.toFixed(1)}" r="${dot}" fill="${seatColor(m)}" data-id="${esc(m.bioguide_id)}"><title>${esc(m.name)} (${esc(m.party)}-${esc(m.state)}): ${esc(m.vote)}</title></circle>`).join("")}
    </svg>`;
  }

  function memberMatches(m) {
    const q = state.memberQ.trim().toLowerCase();
    const okVote = state.memberFilter === "all" || m.vote === state.memberFilter;
    const okQ = !q || m.name.toLowerCase().includes(q) || m.state.toLowerCase() === q || `${m.state}-${m.district}`.toLowerCase() === q;
    return okVote && okQ;
  }

  function memberRows() {
    const matches = state.detail.members.filter(memberMatches);
    const shown = state.showAllMembers ? matches : matches.slice(0, TABLE_PREVIEW);
    const rows = shown.map((m) => `
      <tr>
        <td><div class="who"><span class="avatar ${esc(m.party)}">${esc(initials(m))}${m.photo_url ? `<img src="${esc(m.photo_url)}" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>${esc(m.name)}</div></td>
        <td class="col-party"><span class="pill ${esc(m.party)}" title="${m.party === "D" ? "Democrat" : m.party === "R" ? "Republican" : "Independent"}">${esc(m.party)}</span></td>
        <td>${esc(m.state)} · ${esc(district(m.district))}</td>
        <td><span class="vote-cell ${esc(m.vote.split(" ")[0])}"><span class="sw"></span>${esc(m.vote)}</span></td>
      </tr>`).join("");
    const more = matches.length > TABLE_PREVIEW
      ? `<a href="#" class="view-all" data-action="toggle-members">${state.showAllMembers ? "Show fewer" : `View all ${matches.length} members`} ${ICONS.arrow}</a>`
      : "";
    return {
      body: rows || `<tr><td colspan="4" class="muted" style="padding:24px 12px">No members match.</td></tr>`,
      more,
      ids: new Set(matches.map((m) => m.bioguide_id)),
    };
  }

  function renderMembers() {
    const { body, more, ids } = memberRows();
    $("#member-tbody").innerHTML = body;
    $("#member-more").innerHTML = more;
    const svg = $(".hemi");
    const filtering = state.memberQ.trim() || state.memberFilter !== "all";
    svg.classList.toggle("dim", Boolean(filtering));
    svg.querySelectorAll("circle").forEach((c) => c.classList.toggle("hit", ids.has(c.dataset.id)));
  }

  function renderDetail() {
    const d = state.detail, b = d.bill;
    const following = store.get("followed", []).includes(b.id);
    const counts = { D: 0, R: 0, I: 0 };
    d.members.forEach((m) => { counts[m.party] = (counts[m.party] || 0) + 1; });

    $("#detail").innerHTML = `
      <div class="d-head">
        <div class="d-badges"><span class="status ${statusClass(b.status)}">${esc(b.status)}</span><span class="d-label">${esc(b.label)}</span></div>
        <div class="d-title-row">
          <h2 class="d-title">${esc(b.title)}</h2>
          <button type="button" class="btn ${following ? "following" : ""}" data-action="follow" aria-pressed="${following}">${ICONS.bell}${following ? "Following" : "Follow bill"}</button>
        </div>
        ${summaryHTML(b)}
        <div class="d-meta">
          <span>${ICONS.calendar}Last vote ${fmtDate(d.date)}</span>
          <span>${ICONS.building}House floor</span>
          ${b.policy_area ? `<span class="tag">${esc(b.policy_area)}</span>` : ""}
          ${b.url ? `<a href="${esc(b.url)}" target="_blank" rel="noopener">View full bill ${ICONS.external}</a>` : ""}
        </div>
      </div>
      <div class="d-results">
        <div class="final-vote">${finalVote(d)}</div>
        <div class="glance">${glance(d)}</div>
      </div>
      <div class="individual">
        <div class="ind-head">
          <div><p class="eyebrow">Individual votes</p><h2>How the House voted</h2></div>
          <div class="ind-controls">
            <div class="search-box small">${ICONS.search}<input id="member-search" type="search" placeholder="Search member or state" aria-label="Search member or state"></div>
            <select id="member-filter" aria-label="Filter by vote">
              <option value="all">All votes</option><option value="Yea">Yea</option><option value="Nay">Nay</option>
              <option value="Present">Present</option><option value="Not voting">Not voting</option>
            </select>
          </div>
        </div>
        <div class="chamber-box">
          <div class="chamber-head">
            <div><strong>House chamber</strong><small>${d.members.length} members voting or absent · grouped by party</small></div>
            <div class="seat-legend">
              <span><span class="dot" style="margin:0;background:var(--dem)"></span>Dem Yea</span>
              <span><span class="dot" style="margin:0;background:var(--dem-dark)"></span>Dem Nay</span>
              <span><span class="dot" style="margin:0;background:var(--rep)"></span>GOP Yea</span>
              <span><span class="dot" style="margin:0;background:var(--rep-soft)"></span>GOP Nay</span>
              <span><span class="dot" style="margin:0;background:#4b5568"></span>Not voting</span>
            </div>
          </div>
          <div class="hemi-wrap">
            ${hemicycle(d.members)}
            <div class="hemi-side left"><strong>Democrats</strong><small>${counts.D} members</small></div>
            <div class="hemi-side right"><strong>Republicans</strong><small>${counts.R} members</small></div>
          </div>
        </div>
        <table class="members-table">
          <thead><tr><th scope="col">Legislator</th><th scope="col" class="col-party">Party</th><th scope="col">State / District</th><th scope="col">Vote</th></tr></thead>
          <tbody id="member-tbody"></tbody>
        </table>
        <div id="member-more"></div>
        <p class="muted" style="font-size:13px;margin-top:24px">Source: <a href="${esc(d.source_url)}" target="_blank" rel="noopener">House Clerk roll call ${d.roll_call}</a> via Congress.gov.</p>
      </div>`;
    renderMembers();
  }

  // --- Events ------------------------------------------------------------

  $("#vote-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-id]");
    if (btn && btn.dataset.id !== state.selectedId) {
      selectVote(btn.dataset.id);
      if (window.matchMedia("(max-width: 860px)").matches) $("#detail").scrollIntoView({ behavior: "smooth" });
    }
  });

  $("#bill-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { state.q = e.target.value.trim(); loadList(); }, 200);
  });

  document.querySelectorAll(".seg button").forEach((btn) => btn.addEventListener("click", () => {
    state.chamber = btn.dataset.chamber;
    document.querySelectorAll(".seg button").forEach((b) => {
      b.classList.toggle("active", b === btn);
      b.setAttribute("aria-pressed", String(b === btn));
    });
    loadList();
  }));

  $("#detail").addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    if (action === "toggle-summary") {
      state.summaryOpen = !state.summaryOpen;
      $("#bill-summary").outerHTML = summaryHTML(state.detail.bill);
    } else if (action === "toggle-members") {
      e.preventDefault();
      state.showAllMembers = !state.showAllMembers;
      renderMembers();
    } else if (action === "follow") {
      const id = state.detail.bill.id;
      const set = new Set(store.get("followed", []));
      set.has(id) ? set.delete(id) : set.add(id);
      store.set("followed", [...set]);
      const on = set.has(id);
      el.classList.toggle("following", on);
      el.setAttribute("aria-pressed", String(on));
      el.innerHTML = `${ICONS.bell}${on ? "Following" : "Follow bill"}`;
    }
  });

  $("#detail").addEventListener("input", (e) => {
    if (e.target.id === "member-search") { state.memberQ = e.target.value; state.showAllMembers = false; renderMembers(); }
  });
  $("#detail").addEventListener("change", (e) => {
    if (e.target.id === "member-filter") { state.memberFilter = e.target.value; state.showAllMembers = false; renderMembers(); }
  });

  window.addEventListener("popstate", () => {
    const id = location.hash.slice(1);
    if (id && id !== state.selectedId && state.votes.some((v) => v.id === id)) selectVote(id, { replace: true });
  });

  loadList();
})();
