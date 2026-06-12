import { getJSON, postJSON, postForm, requireRole, logout } from '/assets/js/api.js';
import { esc, toast, openModal, closeModal, wireTabs, withBusy, meterClass, fmtTime } from '/assets/js/ui.js';
import { Camera, Recorder, blobToWav } from '/assets/js/camera.js';

const $ = id => document.getElementById(id);

const me = await requireRole('teacher', '/teacher.html');
if (!me) throw new Error('redirecting');
$('who-name').textContent = me.teacher.name;
$('btn-logout').addEventListener('click', logout);

let subjects = [];
const subjectSelects = ['att-subject', 'rec-subject', 'ana-subject'].map($);

async function loadSubjects() {
  const data = await getJSON('/api/teacher/overview');
  subjects = data.subjects;
  const options = subjects.map(s =>
    `<option value="${s.subject_id}">${esc(s.name)} · ${esc(s.subject_code)}</option>`).join('');
  subjectSelects.forEach(sel => {
    const prev = sel.value;
    sel.innerHTML = options || '<option value="">No subjects yet</option>';
    if (prev && subjects.some(s => String(s.subject_id) === prev)) sel.value = prev;
  });
  renderSubjectList();
}

// Keep the three pickers in sync: change one, all follow.
subjectSelects.forEach(sel => sel.addEventListener('change', () => {
  subjectSelects.forEach(other => { if (other !== sel) other.value = sel.value; });
  if (sel === $('rec-subject')) loadRecords();
  if (sel === $('ana-subject')) loadAnalytics();
}));

const tabs = wireTabs($('main-tabs'), panel => {
  if (panel === 'tab-records') loadRecords();
  if (panel === 'tab-analytics') loadAnalytics();
});

await loadSubjects();

/* ================= TAKE ATTENDANCE ================= */

const attPhotos = [];

function renderAttThumbs() {
  const wrap = $('att-thumbs');
  wrap.innerHTML = '';
  attPhotos.forEach((blob, i) => {
    const t = document.createElement('div');
    t.className = 'thumb';
    const img = document.createElement('img');
    img.src = URL.createObjectURL(blob);
    img.alt = `Class photo ${i + 1}`;
    const x = document.createElement('button');
    x.className = 'thumb-x';
    x.textContent = '✕';
    x.setAttribute('aria-label', `Remove photo ${i + 1}`);
    x.addEventListener('click', () => { attPhotos.splice(i, 1); renderAttThumbs(); });
    t.append(img, x);
    wrap.appendChild(t);
  });
  $('btn-analyze').disabled = attPhotos.length === 0;
  $('btn-att-clear').disabled = attPhotos.length === 0;
  $('cam-count').textContent = `${attPhotos.length} photo(s) captured`;
}

const attCam = new Camera($('att-stage'));
$('btn-att-camera').addEventListener('click', () => {
  openModal('modal-camera');
  attCam.start().catch(err => toast(err.message, 'danger'));
});
$('modal-camera').addEventListener('close', () => attCam.stop());
$('btn-att-snap').addEventListener('click', () =>
  withBusy($('btn-att-snap'), async () => { attPhotos.push(await attCam.capture()); renderAttThumbs(); }));
$('btn-att-done').addEventListener('click', () => closeModal('modal-camera'));

$('att-upload').addEventListener('change', e => {
  for (const f of e.target.files) attPhotos.push(f);
  e.target.value = '';
  renderAttThumbs();
});
$('btn-att-clear').addEventListener('click', () => { attPhotos.length = 0; renderAttThumbs(); });

let reviewProposal = [];

$('btn-analyze').addEventListener('click', () =>
  withBusy($('btn-analyze'), async () => {
    const subjectId = $('att-subject').value;
    if (!subjectId) { toast('Create a subject first.', 'danger'); return; }
    const fd = new FormData();
    fd.append('subject_id', subjectId);
    attPhotos.forEach((b, i) => fd.append('photos', b, `class${i}.jpg`));
    const res = await postForm('/api/teacher/attendance/analyze', fd);
    openReview(res.proposal, res.photos);
  }).catch(() => {}));

function openReview(proposal, photoResults = null) {
  reviewProposal = proposal.map(p => ({ ...p }));

  // Annotated class photos: boxes positioned as % of natural size
  const photosWrap = $('review-photos');
  photosWrap.innerHTML = '';
  if (photoResults) {
    photoResults.forEach((pr, idx) => {
      const wrap = document.createElement('div');
      wrap.className = 'overlay-wrap';
      const img = document.createElement('img');
      img.src = URL.createObjectURL(attPhotos[idx]);
      img.alt = `Class photo ${idx + 1}: ${pr.num_faces} face(s) detected`;
      img.addEventListener('load', () => {
        const W = img.naturalWidth, H = img.naturalHeight;
        pr.faces.forEach(f => {
          if (!f.box || !f.box.w) return;
          const box = document.createElement('div');
          box.className = 'face-box' + (f.student_id ? '' : ' unknown');
          box.style.left = (100 * f.box.x / W) + '%';
          box.style.top = (100 * f.box.y / H) + '%';
          box.style.width = (100 * f.box.w / W) + '%';
          box.style.height = (100 * f.box.h / H) + '%';
          const tag = document.createElement('span');
          tag.className = 'face-tag';
          tag.textContent = f.name || 'Unknown';
          box.appendChild(tag);
          wrap.appendChild(box);
        });
      });
      wrap.appendChild(img);
      photosWrap.appendChild(wrap);
    });
  }

  renderReviewRows();
  openModal('modal-review');
}

function renderReviewRows() {
  const present = reviewProposal.filter(p => p.is_present).length;
  $('review-summary').textContent =
    `${present} of ${reviewProposal.length} marked present. Flip any switch the AI got wrong.`;
  $('review-rows').innerHTML = reviewProposal.map((p, i) => `
    <tr>
      <td><b>${esc(p.name)}</b></td>
      <td class="muted">${p.sources?.length ? esc(p.sources.join(', ')) : '—'}</td>
      <td>
        <label class="switch">
          <input type="checkbox" data-i="${i}" ${p.is_present ? 'checked' : ''}
                 aria-label="${esc(p.name)} present">
          <span class="track"></span>
        </label>
      </td>
    </tr>`).join('');
  $('review-rows').querySelectorAll('input[type="checkbox"]').forEach(cb =>
    cb.addEventListener('change', () => {
      reviewProposal[+cb.dataset.i].is_present = cb.checked;
      const present = reviewProposal.filter(p => p.is_present).length;
      $('review-summary').textContent =
        `${present} of ${reviewProposal.length} marked present. Flip any switch the AI got wrong.`;
    }));
}

$('btn-review-discard').addEventListener('click', () => closeModal('modal-review'));
$('btn-review-save').addEventListener('click', () =>
  withBusy($('btn-review-save'), async () => {
    const res = await postJSON('/api/teacher/attendance/confirm', {
      subject_id: +$('att-subject').value,
      entries: reviewProposal.map(p => ({ student_id: p.student_id, is_present: p.is_present })),
    });
    closeModal('modal-review');
    attPhotos.length = 0;
    renderAttThumbs();
    toast(`Saved: ${res.present}/${res.total} present.`, 'ok');
    loadSubjects();
  }).catch(() => {}));

/* ---------- voice attendance ---------- */

const rec = new Recorder();
let voiceWav = null;

$('btn-voice').addEventListener('click', () => {
  voiceWav = null;
  $('voice-playback').hidden = true;
  $('btn-voice-analyze').disabled = true;
  $('btn-voice-rec').textContent = '🎤 Start recording';
  openModal('modal-voice');
});

$('btn-voice-rec').addEventListener('click', async () => {
  const btn = $('btn-voice-rec');
  try {
    if (!rec.active) {
      await rec.start();
      btn.textContent = '⏹ Stop recording';
    } else {
      const raw = await rec.stop();
      btn.textContent = '🎤 Record again';
      voiceWav = await blobToWav(raw);
      const player = $('voice-playback');
      player.src = URL.createObjectURL(voiceWav);
      player.hidden = false;
      $('btn-voice-analyze').disabled = false;
    }
  } catch (err) {
    toast(err.message, 'danger');
  }
});

$('btn-voice-analyze').addEventListener('click', () =>
  withBusy($('btn-voice-analyze'), async () => {
    const fd = new FormData();
    fd.append('subject_id', $('att-subject').value);
    fd.append('audio', voiceWav, 'class.wav');
    const res = await postForm('/api/teacher/attendance/voice', fd);
    closeModal('modal-voice');
    openReview(res.proposal);
  }).catch(() => {}));

/* ---------- live QR attendance ---------- */

let qrSession = null;
let qrFinishing = false;
let qrTimers = [];

function stopQrTimers() { qrTimers.forEach(clearInterval); qrTimers = []; }

async function refreshQrCode() {
  if (!qrSession) return;
  try {
    const res = await getJSON(`/api/teacher/qr/code?qid=${qrSession}`);
    $('qr-live-img').src = res.qr;
  } catch { /* session ended */ }
}

async function refreshQrFeed() {
  if (!qrSession) return;
  try {
    const res = await getJSON(`/api/teacher/qr/status?qid=${qrSession}`);
    $('qr-count').textContent = res.checked_in.length;
    $('qr-feed').innerHTML = res.checked_in.length
      ? res.checked_in.map(c =>
          `<li style="padding:6px 0; border-bottom:1px solid var(--line)">
             ✅ <b>${esc(c.name)}</b> <small class="muted">${esc(c.time)}</small>
           </li>`).join('')
      : '<li class="muted">Waiting for scans…</li>';
  } catch { /* session ended */ }
}

$('btn-qr-live').addEventListener('click', () =>
  withBusy($('btn-qr-live'), async () => {
    const subjectId = +$('att-subject').value;
    if (!subjectId) { toast('Create a subject first.', 'danger'); return; }
    const res = await postJSON('/api/teacher/qr/start', { subject_id: subjectId });
    qrSession = res.qid;
    qrFinishing = false;
    $('qr-count').textContent = '0';
    $('qr-feed').innerHTML = '<li class="muted">Waiting for scans…</li>';
    openModal('modal-qr');
    await refreshQrCode();
    qrTimers.push(setInterval(refreshQrCode, 15000), setInterval(refreshQrFeed, 3000));
  }).catch(() => {}));

$('modal-qr').addEventListener('close', () => {
  stopQrTimers();
  if (qrSession && !qrFinishing) {
    postJSON('/api/teacher/qr/cancel', { qid: qrSession }).catch(() => {});
    qrSession = null;
  }
});

$('btn-qr-finish').addEventListener('click', () =>
  withBusy($('btn-qr-finish'), async () => {
    qrFinishing = true;
    try {
      const res = await postJSON('/api/teacher/qr/finish', { qid: qrSession });
      qrSession = null;
      closeModal('modal-qr');
      openReview(res.proposal);
    } finally {
      qrFinishing = false;
    }
  }).catch(() => {}));

/* ================= SUBJECTS ================= */

function renderSubjectList() {
  const wrap = $('subject-list');
  if (!subjects.length) {
    wrap.innerHTML = `<div class="empty" style="grid-column:1/-1">
      <span class="glyph" aria-hidden="true">📚</span>
      <b>No subjects yet.</b><br>Create one, then share its code or QR with students.
    </div>`;
    return;
  }
  wrap.innerHTML = subjects.map(s => `
    <article class="card subject-card">
      <div class="row row--between">
        <h3>${esc(s.name)}</h3>
        ${s.low_attendance ? `<span class="badge badge--danger">⚠ ${s.low_attendance} below 75%</span>` : ''}
      </div>
      <p class="meta">Code <span class="code-chip">${esc(s.subject_code)}</span> · Section ${esc(s.section)}</p>
      <div class="statline">
        <span class="stat-chip">👥 <b>${s.total_students}</b> students</span>
        <span class="stat-chip">📅 <b>${s.total_classes}</b> classes</span>
      </div>
      <div class="row">
        <button class="btn" data-share="${s.subject_id}">🔗 Share</button>
        <button class="btn" data-roster="${s.subject_id}" data-name="${esc(s.name)}">👥 Roster</button>
      </div>
    </article>`).join('');

  wrap.querySelectorAll('[data-share]').forEach(b =>
    b.addEventListener('click', () => openShare(b.dataset.share)));
  wrap.querySelectorAll('[data-roster]').forEach(b =>
    b.addEventListener('click', () => openRoster(b.dataset.roster, b.dataset.name)));
}

$('btn-new-subject').addEventListener('click', () => openModal('modal-subject'));
$('btn-create-subject').addEventListener('click', () =>
  withBusy($('btn-create-subject'), async () => {
    await postJSON('/api/teacher/subjects', {
      name: $('sub-name').value, code: $('sub-code').value, section: $('sub-section').value,
    });
    closeModal('modal-subject');
    ['sub-name', 'sub-code', 'sub-section'].forEach(id => $(id).value = '');
    toast('Subject created.', 'ok');
    loadSubjects();
  }).catch(() => {}));

async function openShare(subjectId) {
  const res = await getJSON(`/api/teacher/subjects/${subjectId}/share`);
  $('share-body').innerHTML = `
    <img src="${res.qr}" alt="QR code to join with code ${esc(res.code)}" width="220" height="220"
         style="border-radius:12px; border:1px solid var(--line)">
    <p class="mt-1">Scan to join, or share the code:</p>
    <p><span class="code-chip" style="font-size:1.3rem">${esc(res.code)}</span></p>
    <button class="btn btn--primary" id="btn-copy-link">📋 Copy join link</button>`;
  openModal('modal-share');
  $('btn-copy-link').addEventListener('click', async () => {
    await navigator.clipboard.writeText(res.join_url);
    toast('Link copied.', 'ok');
  });
}

async function openRoster(subjectId, name) {
  $('roster-title').textContent = `Roster · ${name}`;
  $('roster-body').innerHTML = '<div class="skeleton"></div>';
  openModal('modal-roster');
  const res = await getJSON(`/api/teacher/subjects/${subjectId}/roster`);
  if (!res.students.length) {
    $('roster-body').innerHTML = `<div class="empty"><span class="glyph">🪪</span>
      <b>No students enrolled.</b><br>Share the subject code to get them in.</div>`;
    return;
  }
  $('roster-body').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Student</th><th>Attended</th><th>Rate</th><th></th></tr></thead>
    <tbody>${res.students.map(s => `
      <tr>
        <td><b>${esc(s.name)}</b><br><small class="muted">@${esc(s.username ?? '')}</small></td>
        <td>${s.attended}/${s.total}</td>
        <td>${s.percent === null ? '<span class="muted">—</span>' : s.percent + '%'}</td>
        <td>${s.low ? '<span class="badge badge--danger">Low</span>'
                    : (s.percent !== null ? '<span class="badge badge--ok">OK</span>' : '')}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

/* ================= RECORDS ================= */

$('rec-date').addEventListener('change', loadRecords);
$('rep-period').addEventListener('change', updateReportLinks);

function updateReportLinks() {
  const subjectId = $('rec-subject').value;
  if (!subjectId) return;
  $('btn-export').href = `/api/teacher/export?subject_id=${subjectId}`;
  $('btn-pdf').href = `/api/teacher/report?subject_id=${subjectId}&period=${$('rep-period').value}`;
}

async function loadRecords() {
  const subjectId = $('rec-subject').value;
  if (!subjectId) { $('rec-sessions').innerHTML = ''; return; }
  updateReportLinks();
  const date = $('rec-date').value;
  const url = `/api/teacher/records?subject_id=${subjectId}` + (date ? `&date=${date}` : '');
  $('rec-sessions').innerHTML = '<div class="skeleton"></div>';
  const res = await getJSON(url);
  if (!res.sessions.length) {
    $('rec-sessions').innerHTML = `<div class="empty"><span class="glyph">🗓️</span>
      <b>No attendance records${date ? ' on this date' : ' yet'}.</b><br>
      Take attendance and it will show up here.</div>`;
    return;
  }
  $('rec-sessions').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>When</th><th>Present</th><th>Rate</th><th></th></tr></thead>
    <tbody>${res.sessions.map(s => {
      const pct = s.total ? Math.round(100 * s.present / s.total) : 0;
      return `<tr>
        <td><b>${fmtTime(s.time)}</b></td>
        <td>${s.present}/${s.total}</td>
        <td>${pct}%</td>
        <td><button class="btn btn--ghost" data-detail="${esc(s.key)}" data-time="${esc(s.time ?? '')}">View</button></td>
      </tr>`;
    }).join('')}</tbody></table></div>`;
  $('rec-sessions').querySelectorAll('[data-detail]').forEach(b =>
    b.addEventListener('click', () => openSession(b.dataset.detail, b.dataset.time)));
}

async function openSession(key, time) {
  $('session-title').textContent = `Session · ${fmtTime(time)}`;
  $('session-body').innerHTML = '<div class="skeleton"></div>';
  openModal('modal-session');
  const subjectId = $('rec-subject').value;
  const res = await getJSON(`/api/teacher/records/detail?subject_id=${subjectId}&key=${encodeURIComponent(key)}`);
  $('session-body').innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Student</th><th>Status</th></tr></thead>
    <tbody>${res.rows.map(r => `
      <tr>
        <td>${esc(r.name)}</td>
        <td>${r.is_present
          ? '<span class="badge badge--ok">Present</span>'
          : '<span class="badge badge--danger">Absent</span>'}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

/* ================= ANALYTICS ================= */

async function loadAnalytics() {
  const subjectId = $('ana-subject').value;
  const body = $('ana-body');
  if (!subjectId) { body.innerHTML = ''; return; }
  body.innerHTML = '<div class="skeleton mt-2"></div>';
  const res = await getJSON(`/api/teacher/analytics?subject_id=${subjectId}`);

  if (!res.trend.length) {
    body.innerHTML = `<div class="empty mt-2"><span class="glyph">📈</span>
      <b>No data yet.</b><br>Analytics appear after the first attendance.</div>`;
    return;
  }

  const trendBars = res.trend.slice(-16).map(s => {
    const pct = s.total ? Math.round(100 * s.present / s.total) : 0;
    return `<div class="bar" style="height:${Math.max(pct, 4)}%"
                 title="${fmtTime(s.time)}: ${s.present}/${s.total} present">
              <span class="tip">${pct}%</span>
            </div>`;
  }).join('');

  const insightsBlock = res.insights?.length
    ? `<h4 class="mt-3">🧠 Smart insights</h4>
       <div class="stack">${res.insights.map(i =>
         `<div class="panel">${i.icon} ${esc(i.text)}</div>`).join('')}</div>`
    : '';

  const chronicBlock = res.chronic.length
    ? `<h4 class="mt-3">⚠ Below ${res.cutoff}% attendance</h4>
       <div class="row">${res.chronic.map(c =>
         `<span class="badge badge--danger">${esc(c.name)} · ${c.percent}%</span>`).join(' ')}</div>`
    : `<p class="mt-3"><span class="badge badge--ok">Everyone is at or above ${res.cutoff}% 🎉</span></p>`;

  body.innerHTML = `
    <h4 class="mt-2">Presence per class (latest ${Math.min(res.trend.length, 16)})</h4>
    <div class="bars" role="img" aria-label="Attendance percentage per class session">${trendBars}</div>
    ${insightsBlock}
    ${chronicBlock}
    <h4 class="mt-3">Per student</h4>
    <div class="table-wrap"><table>
      <thead><tr><th>Student</th><th>Attended</th><th style="width:40%">Rate</th></tr></thead>
      <tbody>${res.students.map(s => `
        <tr>
          <td><b>${esc(s.name)}</b></td>
          <td>${s.attended}/${s.total}</td>
          <td>
            <div class="meter">
              <div class="meter-track"><div class="meter-fill ${meterClass(s.percent)}"
                   style="width:${s.percent ?? 0}%"></div></div>
              <small class="muted">${s.percent === null ? 'No classes yet' : s.percent + '%'}</small>
            </div>
          </td>
        </tr>`).join('')}</tbody>
    </table></div>`;
}
