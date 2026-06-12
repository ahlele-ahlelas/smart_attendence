import { getJSON, postJSON, postForm } from '/assets/js/api.js';
import { toast, wireTabs, withBusy } from '/assets/js/ui.js';
import { Camera, Recorder, blobToWav } from '/assets/js/camera.js';

const $ = id => document.getElementById(id);
const DASH = '/student-dashboard.html' + window.location.search;

// Already signed in (e.g. arriving from a scanned QR)? Straight to the dashboard.
getJSON('/api/auth/me').then(me => {
  if (me.role === 'student') window.location.href = DASH;
}).catch(() => {});

wireTabs($('login-tabs'));

const cam = new Camera($('login-stage'));
cam.start().catch(err => {
  $('face-error').textContent = err.message;
  $('face-error').hidden = false;
});

let loginShot = null;        // blob from the recognition attempt
const extraShots = [];       // additional registration photos
let voiceBlob = null;

// ---------- face login ----------
$('btn-face-login').addEventListener('click', () =>
  withBusy($('btn-face-login'), async () => {
    $('face-error').hidden = true;
    loginShot = await cam.capture();
    const fd = new FormData();
    fd.append('photo', loginShot, 'login.jpg');
    try {
      const res = await postForm('/api/auth/student/face-login', fd);
      if (res.recognized) {
        toast(`Welcome back, ${res.student.name}!`, 'ok');
        window.location.href = DASH;
      } else {
        $('register-card').hidden = false;
        $('register-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
        toast('Face not recognized. Register below to get started.');
      }
    } catch (err) {
      $('face-error').textContent = err.message;
      $('face-error').hidden = false;
      if (err.status === 422) {
        // no face / multiple faces: keep camera flow, no register prompt
      }
      throw err;
    }
  }).catch(() => {}));

// ---------- registration photos ----------
function renderThumbs() {
  const wrap = $('reg-thumbs');
  wrap.innerHTML = '';
  const all = [...(loginShot ? [loginShot] : []), ...extraShots];
  all.forEach((blob, i) => {
    const t = document.createElement('div');
    t.className = 'thumb';
    const img = document.createElement('img');
    img.src = URL.createObjectURL(blob);
    img.alt = `Photo ${i + 1}`;
    t.appendChild(img);
    if (i > 0 || !loginShot) {
      const x = document.createElement('button');
      x.className = 'thumb-x';
      x.textContent = '✕';
      x.setAttribute('aria-label', `Remove photo ${i + 1}`);
      x.addEventListener('click', () => {
        extraShots.splice(loginShot ? i - 1 : i, 1);
        renderThumbs();
      });
      t.appendChild(x);
    }
    wrap.appendChild(t);
  });
}

$('btn-reg-snap').addEventListener('click', () =>
  withBusy($('btn-reg-snap'), async () => {
    extraShots.push(await cam.capture());
    renderThumbs();
  }));

$('reg-upload').addEventListener('change', e => {
  for (const f of e.target.files) extraShots.push(f);
  e.target.value = '';
  renderThumbs();
});

// ---------- voice ----------
const rec = new Recorder();
$('btn-rec').addEventListener('click', async () => {
  const btn = $('btn-rec');
  try {
    if (!rec.active) {
      await rec.start();
      btn.textContent = '⏹ Stop recording';
    } else {
      const raw = await rec.stop();
      btn.textContent = '🎤 Record again';
      voiceBlob = await blobToWav(raw);
      $('rec-done').hidden = false;
    }
  } catch (err) {
    toast(err.message, 'danger');
  }
});

// ---------- register ----------
$('btn-register').addEventListener('click', () =>
  withBusy($('btn-register'), async () => {
    const errEl = $('reg-error');
    errEl.hidden = true;
    const name = $('reg-name').value.trim();
    const username = $('reg-username').value.trim();
    const pass = $('reg-pass').value;
    const pass2 = $('reg-pass2').value;

    const fail = msg => { errEl.textContent = msg; errEl.hidden = false; throw new Error(msg); };
    if (!name) fail('Enter your name.');
    if (!username) fail('Choose a username.');
    if (!pass) fail('Set a password.');
    if (pass !== pass2) fail('Passwords do not match.');
    if (!loginShot && extraShots.length === 0) fail('Add at least one face photo.');

    const fd = new FormData();
    fd.append('name', name);
    fd.append('username', username);
    fd.append('password', pass);
    if (loginShot) fd.append('photos', loginShot, 'login.jpg');
    extraShots.forEach((b, i) => fd.append('photos', b, `photo${i}.jpg`));
    if (voiceBlob) fd.append('audio', voiceBlob, 'voice.wav');

    try {
      const res = await postForm('/api/auth/student/register', fd);
      let msg = `Welcome, ${res.student.name}! Profile created with ${res.photos_used} photo(s).`;
      if (res.photos_skipped) msg += ` ${res.photos_skipped} skipped (need exactly one clear face).`;
      toast(msg, 'ok');
      window.location.href = DASH;
    } catch (err) {
      errEl.textContent = err.message;
      errEl.hidden = false;
      throw err;
    }
  }).catch(() => {}));

// ---------- password login ----------
$('btn-pass-login').addEventListener('click', () =>
  withBusy($('btn-pass-login'), async () => {
    const res = await postJSON('/api/auth/student/login', {
      username: $('pl-username').value,
      password: $('pl-pass').value,
    });
    toast(`Welcome back, ${res.student.name}!`, 'ok');
    window.location.href = DASH;
  }).catch(() => {}));

$('pl-pass').addEventListener('keydown', e => { if (e.key === 'Enter') $('btn-pass-login').click(); });
