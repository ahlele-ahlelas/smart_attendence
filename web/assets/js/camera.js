// Camera capture built on getUserMedia.
// Mount on a .cam-stage element; capture() resolves a JPEG Blob.

export class Camera {
  constructor(stage) {
    this.stage = stage;
    this.video = stage.querySelector('video');
    this.stream = null;
  }

  async start() {
    if (this.stream) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('Camera not supported here. Use HTTPS or localhost, or upload a photo instead.');
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        throw new Error('Camera permission denied. Allow camera access in your browser, or upload a photo.');
      }
      throw new Error('Could not open the camera. Try uploading a photo instead.');
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    return true;
  }

  capture() {
    return new Promise((resolve, reject) => {
      const v = this.video;
      if (!v.videoWidth) return reject(new Error('Camera not ready yet.'));
      const canvas = document.createElement('canvas');
      canvas.width = v.videoWidth;
      canvas.height = v.videoHeight;
      canvas.getContext('2d').drawImage(v, 0, 0);
      this.stage.classList.remove('cam-flash');
      void this.stage.offsetWidth; // restart animation
      this.stage.classList.add('cam-flash');
      canvas.toBlob(b => b ? resolve(b) : reject(new Error('Capture failed.')), 'image/jpeg', 0.92);
    });
  }

  stop() {
    this.stream?.getTracks().forEach(t => t.stop());
    this.stream = null;
    this.video.srcObject = null;
  }
}

// Record microphone audio; resolves a webm/ogg Blob.
export class Recorder {
  constructor() { this.rec = null; this.chunks = []; this.stream = null; }

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone not supported here.');
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      throw new Error('Microphone permission denied.');
    }
    this.chunks = [];
    this.rec = new MediaRecorder(this.stream);
    this.rec.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start();
  }

  stop() {
    return new Promise(resolve => {
      this.rec.onstop = () => {
        this.stream.getTracks().forEach(t => t.stop());
        resolve(new Blob(this.chunks, { type: this.rec.mimeType || 'audio/webm' }));
      };
      this.rec.stop();
    });
  }

  get active() { return this.rec?.state === 'recording'; }
}

// Convert any recorded audio blob to 16 kHz mono WAV (what the server's
// voice pipeline reads natively; webm/opus would need ffmpeg server-side).
export async function blobToWav(blob, sampleRate = 16000) {
  const raw = await blob.arrayBuffer();
  const probe = new AudioContext();
  const decoded = await probe.decodeAudioData(raw);
  probe.close();

  const frames = Math.ceil(decoded.duration * sampleRate);
  const off = new OfflineAudioContext(1, frames, sampleRate);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  const pcm = rendered.getChannelData(0);

  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const writeStr = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  writeStr(0, 'RIFF'); out.setUint32(4, 36 + pcm.length * 2, true); writeStr(8, 'WAVE');
  writeStr(12, 'fmt '); out.setUint32(16, 16, true); out.setUint16(20, 1, true);
  out.setUint16(22, 1, true); out.setUint32(24, sampleRate, true);
  out.setUint32(28, sampleRate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  writeStr(36, 'data'); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    out.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return new Blob([out.buffer], { type: 'audio/wav' });
}
