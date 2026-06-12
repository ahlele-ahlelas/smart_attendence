import { getJSON, postJSON, postForm, del, requireRole, logout } from '/assets/js/api.js';
import { esc, toast, openModal, closeModal, withBusy, meterClass } from '/assets/js/ui.js';
import { Camera } from '/assets/js/camera.js';

const $ = id => document.getElementById(id);
const FACE_TARGET = 5;

let me = await requireRole('student', '/student.html');
if (!me) throw new Error('redirecting');

$('btn-logout').addEventListener('click', logout);

// ---------- render ----------
function renderFaceCard(student) {
  $('who-name').textContent = student.name;
  const n = student.face_samples || 0;
  const pct = Math.min(100, Math.round(100 * n / FACE_TARGET));
  $('face-meter').style.width = pct + '%';
  $('face-meter').className = 'meter-fill ' + (n >= FACE_TARGET ? 'meter-fill--ok' : '');
  $('face-meter-label').textContent =
    n >= FACE_TARGET
      ? `${n} photos enrolled. Recognition is at full strength.`
      : `${n}/${FACE_TARGET} photos enrolled. Add ${FACE_TARGET - n} more for best accuracy.`;
}

function subjectCard(s) {
  const pctText = s.percent === null ? 'No classes yet' : `${s.percent}% attended`;
  const badge = s.percent !== null && s.percent < 75
    ? '<span class="badge badge--danger">Low attendance</span>' : '';
  return `
  <article class="card subject-card">
    <div class="row row--between">
      <h3>${esc(s.name)}</h3>${badge}
    </div>
    <p class="meta">Code <span class="code-chip">${esc(s.code)}</span> · Section ${esc(s.section)}</p>
    <div class="statline">
      <span class="stat-chip">📅 <b>${s.total_classes}</b> classes</span>
      <span class="stat-chip">✅ <b>${s.attended}</b> attended</span>
    </div>
    <div class="meter">
      <div class="meter-track"><div class="meter-fill ${meterClass(s.percent)}" style="width:${s.percent ?? 0}%"></div></div>
      <small class="muted">${pctText}</small>
    </div>
    <button class="btn btn--danger mt-2" data-unenroll="${s.subject_id}" data-name="${esc(s.name)}">Unenroll</button>
  </article>`;
}

async function refresh() {
  const data = await getJSON('/api/student/overview');
  renderFaceCard(data.student);
  const wrap = $('subjects');
  if (!data.subjects.length) {
    wrap.innerHTML = `<div class="empty" style="grid-column:1/-1">
      <span class="glyph" aria-hidden="true">📚</span>
      <b>No subjects yet.</b><br>Tap “Join a subject” and enter the code your teacher shared.
    </div>`;
    return;
  }
  wrap.innerHTML = data.subjects.map(subjectCard).join('');
  wrap.querySelectorAll('[data-unenroll]').forEach(btn =>
    btn.addEventListener('click', async () => {
      if (!confirm(`Unenroll from ${btn.dataset.name}?`)) return;
      await del(`/api/student/subjects/${btn.dataset.unenroll}`);
      toast(`Unenrolled from ${btn.dataset.name}.`, 'ok');
      refresh();
    }));
}

await refresh();

// ---------- PDF report ----------
$('report-period').addEventListener('change', () => {
  $('btn-report').href = `/api/student/report?period=${$('report-period').value}`;
});

// ---------- join subject ----------
$('btn-join').addEventListener('click', () => { openModal('modal-join'); $('join-code').focus(); });
$('btn-join-go').addEventListener('click', () =>
  withBusy($('btn-join-go'), async () => {
    const code = $('join-code').value.trim();
    if (!code) { toast('Enter the subject code.', 'danger'); return; }
    const res = await postJSON('/api/student/enroll', { code });
    closeModal('modal-join');
    $('join-code').value = '';
    toast(res.already_enrolled
      ? `You're already enrolled in ${res.subject.name}.`
      : `Enrolled in ${res.subject.name}!`, 'ok');
    refresh();
  }).catch(() => {}));

// Live QR attendance check-in (?attend=TOKEN from a scanned code)
const attendToken = new URLSearchParams(window.location.search).get('attend');
if (attendToken) {
  history.replaceState(null, '', window.location.pathname);
  try {
    const res = await postJSON('/api/student/checkin', { token: attendToken });
    toast(`✅ You're checked in for ${res.subject}!`, 'ok');
  } catch (err) {
    toast(err.message, 'danger');
  }
}

// Auto-enroll from a shared link / QR (?join-code=CODE)
const joinCode = new URLSearchParams(window.location.search).get('join-code');
if (joinCode) {
  history.replaceState(null, '', window.location.pathname);
  try {
    const res = await postJSON('/api/student/enroll', { code: joinCode });
    toast(res.already_enrolled
      ? `You're already enrolled in ${res.subject.name}.`
      : `Enrolled in ${res.subject.name}!`, 'ok');
    refresh();
  } catch (err) {
    toast(err.message, 'danger');
  }
}

// ---------- add photos ----------
const photosCam = new Camera($('photos-stage'));
const pending = [];

function renderThumbs() {
  const wrap = $('photo-thumbs');
  wrap.innerHTML = '';
  pending.forEach((blob, i) => {
    const t = document.createElement('div');
    t.className = 'thumb';
    const img = document.createElement('img');
    img.src = URL.createObjectURL(blob);
    img.alt = `Photo ${i + 1}`;
    const x = document.createElement('button');
    x.className = 'thumb-x';
    x.textContent = '✕';
    x.setAttribute('aria-label', `Remove photo ${i + 1}`);
    x.addEventListener('click', () => { pending.splice(i, 1); renderThumbs(); });
    t.append(img, x);
    wrap.appendChild(t);
  });
  $('btn-save-photos').disabled = pending.length === 0;
}

$('btn-add-photos').addEventListener('click', () => {
  openModal('modal-photos');
  photosCam.start().catch(err => toast(err.message, 'danger'));
});
$('modal-photos').addEventListener('close', () => photosCam.stop());

$('btn-snap').addEventListener('click', () =>
  withBusy($('btn-snap'), async () => { pending.push(await photosCam.capture()); renderThumbs(); }));

$('photos-upload').addEventListener('change', e => {
  for (const f of e.target.files) pending.push(f);
  e.target.value = '';
  renderThumbs();
});

$('btn-save-photos').addEventListener('click', () =>
  withBusy($('btn-save-photos'), async () => {
    const fd = new FormData();
    pending.forEach((b, i) => fd.append('photos', b, `photo${i}.jpg`));
    const res = await postForm('/api/student/face-photos', fd);
    pending.length = 0;
    renderThumbs();
    closeModal('modal-photos');
    let msg = `Added ${res.added} photo(s).`;
    if (res.skipped) msg += ` Skipped ${res.skipped} (need exactly one clear face).`;
    toast(msg, 'ok');
    renderFaceCard(res.student);
  }).catch(() => {}));

// ---------- test recognition ----------
const testCam = new Camera($('test-stage'));
$('btn-test').addEventListener('click', () => {
  $('test-result').hidden = true;
  openModal('modal-test');
  testCam.start().catch(err => toast(err.message, 'danger'));
});
$('modal-test').addEventListener('close', () => testCam.stop());

$('btn-run-test').addEventListener('click', () =>
  withBusy($('btn-run-test'), async () => {
    const blob = await testCam.capture();
    const fd = new FormData();
    fd.append('photo', blob, 'test.jpg');
    const res = await postForm('/api/student/test-recognition', fd);
    const box = $('test-result');
    const messages = {
      recognized: ['✅ Recognized! You\'re all set for attendance.', 'ok'],
      not_recognized: ['❌ Not recognized. Add a few more photos (different angle or lighting) and try again.', 'danger'],
      no_face: ['😶 No face detected. Get closer and face the light.', ''],
      multiple_faces: ['👥 More than one face in frame. Make sure only you are visible.', ''],
      spoof: ['🚫 That looks like a photo of a screen or print. Use your live face.', 'danger'],
    };
    const [text] = messages[res.result] || ['Unexpected result.'];
    box.textContent = text;
    if (res.result === 'not_recognized' && res.matched_someone_else) {
      box.textContent += ' (The AI matched someone else; more photos of you will fix this.)';
    }
    box.hidden = false;
  }).catch(() => {}));
