/**
 * Vision Assistant — Web Client
 *
 * Protocol (JSON over WebSocket /ws/web):
 *   TX: { type:"audio", data:"<base64 pcm 16kHz 16bit mono>" }
 *       { type:"video", data:"<base64 jpeg>" }
 *   RX: { type:"audio",      data:"<base64 pcm 24kHz 16bit mono>" }
 *       { type:"transcript", role:"input"|"output", text:"..." }
 *       { type:"interrupted" }
 */

'use strict';

// ─── DOM refs ────────────────────────────────────────────────────────────────
const video        = document.getElementById('video');
const camPlaceholder = document.getElementById('cam-placeholder');
const recDot       = document.getElementById('rec-dot');
const statusDot    = document.getElementById('status-dot');
const messages     = document.getElementById('messages');
const btnToggle    = document.getElementById('btn-toggle');
const micRing      = document.getElementById('mic-ring');
const micBarEls    = document.querySelectorAll('#mic-bars span');

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  ws:               null,
  audioCtx:         null,
  micStream:        null,
  videoStream:      null,
  scriptProcessor:  null,
  analyser:         null,
  micAnimId:        null,
  camInterval:      null,
  nextPlayTime:     0,
  currentUserMsg:   null,   // active user message element
  currentModelMsg:  null,   // active model message element
};

const BAR_COUNT = 12;

// ─── Utilities ───────────────────────────────────────────────────────────────
function float32ToInt16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    out[i] = Math.max(-32768, Math.min(32767, f32[i] * 32768));
  }
  return out;
}

function downsample(buf, fromRate, toRate) {
  if (fromRate === toRate) return buf;
  const ratio  = fromRate / toRate;
  const len    = Math.floor(buf.length / ratio);
  const out    = new Float32Array(len);
  for (let i = 0; i < len; i++) out[i] = buf[Math.floor(i * ratio)];
  return out;
}

function bufToBase64(ab) {
  const bytes = new Uint8Array(ab);
  let s = '';
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

function base64ToInt16(b64) {
  const binary = atob(b64);
  const buf    = new ArrayBuffer(binary.length);
  const view   = new Uint8Array(buf);
  for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);
  return new Int16Array(buf);
}

// ─── WebSocket ───────────────────────────────────────────────────────────────
function wsConnect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  state.ws    = new WebSocket(`${proto}://${location.host}/ws/web`);

  state.ws.addEventListener('open',    onWsOpen);
  state.ws.addEventListener('message', onWsMessage);
  state.ws.addEventListener('close',   onWsClose);
  state.ws.addEventListener('error',   (e) => console.error('WS error', e));
}

async function onWsOpen() {
  statusDot.classList.add('connected');
  btnToggle.textContent = 'Disconnect';
  btnToggle.classList.add('live');
  btnToggle.disabled = false;

  await setupCamera();
  await setupMic();
  startCameraCapture();

  recDot.classList.add('active');
  micRing.classList.add('active');
}

function onWsClose() {
  statusDot.classList.remove('connected');
  btnToggle.textContent = 'Connect';
  btnToggle.classList.remove('live');
  btnToggle.disabled = false;
  teardown();
}

function onWsMessage(evt) {
  let msg;
  try { msg = JSON.parse(evt.data); } catch { return; }

  switch (msg.type) {
    case 'audio':
      ensureModelMsg();
      playAudio(msg.data);
      setWaveformLive(state.currentModelMsg, true);
      break;

    case 'transcript':
      if (msg.role === 'input') {
        ensureUserMsg();
        setTranscript(state.currentUserMsg, msg.text);
        sealUserMsg();
      } else if (msg.role === 'output') {
        ensureModelMsg();
        setTranscript(state.currentModelMsg, msg.text);
      }
      break;

    case 'interrupted':
      sealModelMsg();
      break;
  }
}

// ─── Camera ──────────────────────────────────────────────────────────────────
async function setupCamera() {
  try {
    state.videoStream = await navigator.mediaDevices.getUserMedia({
      video: { width: 320, height: 240, facingMode: 'environment' },
    });
    video.srcObject = state.videoStream;
    camPlaceholder.style.display = 'none';
  } catch (err) {
    console.warn('Camera unavailable:', err);
  }
}

function startCameraCapture() {
  const canvas = document.createElement('canvas');
  canvas.width  = 320;
  canvas.height = 240;
  const ctx2d   = canvas.getContext('2d');

  state.camInterval = setInterval(() => {
    if (!isWsOpen() || !state.videoStream) return;
    ctx2d.drawImage(video, 0, 0, 320, 240);
    canvas.toBlob((blob) => {
      if (!blob) return;
      blob.arrayBuffer().then((buf) => {
        send({ type: 'video', data: bufToBase64(buf) });
      });
    }, 'image/jpeg', 0.72);
  }, 200); // 5 fps
}

// ─── Microphone ───────────────────────────────────────────────────────────────
async function setupMic() {
  state.audioCtx = new AudioContext();

  try {
    state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  } catch (err) {
    console.warn('Microphone unavailable:', err);
    return;
  }

  const source = state.audioCtx.createMediaStreamSource(state.micStream);

  // Analyser for mic-bar visualization
  state.analyser        = state.audioCtx.createAnalyser();
  state.analyser.fftSize = 128;
  source.connect(state.analyser);

  // ScriptProcessor — extract PCM, resample to 16 kHz, send
  const proc = state.audioCtx.createScriptProcessor(4096, 1, 1);
  proc.onaudioprocess = (e) => {
    if (!isWsOpen()) return;
    const raw        = e.inputBuffer.getChannelData(0);
    const downsampled = downsample(raw, state.audioCtx.sampleRate, 16000);
    const pcm        = float32ToInt16(downsampled);
    send({ type: 'audio', data: bufToBase64(pcm.buffer) });
    // Drive user waveform from raw amplitude
    updateUserWaveform(raw);
  };

  source.connect(proc);
  proc.connect(state.audioCtx.destination);
  state.scriptProcessor = proc;

  animateMicBars();
  ensureUserMsg();
}

// ─── Audio Playback ───────────────────────────────────────────────────────────
function playAudio(b64) {
  if (!state.audioCtx) return;

  const int16  = base64ToInt16(b64);
  const buffer = state.audioCtx.createBuffer(1, int16.length, 24000);
  const ch     = buffer.getChannelData(0);
  for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 32768;

  const src   = state.audioCtx.createBufferSource();
  src.buffer  = buffer;
  src.connect(state.audioCtx.destination);

  const start = Math.max(state.nextPlayTime, state.audioCtx.currentTime + 0.02);
  src.start(start);
  state.nextPlayTime = start + buffer.duration;

  // When the chunk finishes and no more audio is queued, seal the bubble
  src.addEventListener('ended', () => {
    setTimeout(() => {
      if (state.audioCtx && state.nextPlayTime <= state.audioCtx.currentTime + 0.15) {
        sealModelMsg();
      }
    }, 400);
  });
}

// ─── Chat messages ────────────────────────────────────────────────────────────
function createMessage(role) {
  const el = document.createElement('div');
  el.className = `message ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'U' : '✦';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  const waveform = document.createElement('div');
  waveform.className = 'waveform live';
  for (let i = 0; i < BAR_COUNT; i++) {
    const span = document.createElement('span');
    waveform.appendChild(span);
  }

  const transcript = document.createElement('p');
  transcript.className = 'transcript';
  transcript.style.display = 'none';

  bubble.appendChild(waveform);
  bubble.appendChild(transcript);
  el.appendChild(avatar);
  el.appendChild(bubble);
  messages.appendChild(el);

  scrollToBottom();
  return el;
}

function ensureUserMsg() {
  if (!state.currentUserMsg) state.currentUserMsg = createMessage('user');
}

function ensureModelMsg() {
  if (!state.currentModelMsg) state.currentModelMsg = createMessage('model');
}

function sealUserMsg() {
  if (!state.currentUserMsg) return;
  setWaveformLive(state.currentUserMsg, false);
  state.currentUserMsg = null;
}

function sealModelMsg() {
  if (!state.currentModelMsg) return;
  setWaveformLive(state.currentModelMsg, false);
  state.currentModelMsg = null;
}

function setWaveformLive(msgEl, live) {
  if (!msgEl) return;
  msgEl.querySelector('.waveform')?.classList.toggle('live', live);
}

function setTranscript(msgEl, text) {
  if (!msgEl) return;
  const t = msgEl.querySelector('.transcript');
  if (!t) return;
  t.textContent = text;
  t.style.display = 'block';
}

// Update user bubble waveform bars from microphone amplitude data
function updateUserWaveform(raw) {
  if (!state.currentUserMsg) return;
  const bars = state.currentUserMsg.querySelectorAll('.waveform span');
  const step = Math.floor(raw.length / bars.length) || 1;
  bars.forEach((bar, i) => {
    const amp = Math.abs(raw[i * step] ?? 0);
    bar.style.height = `${Math.max(3, Math.min(20, amp * 80))}px`;
  });
}

// ─── Mic-ring bar visualization (AnalyserNode driven) ─────────────────────────
function animateMicBars() {
  if (!state.analyser) return;
  const data = new Uint8Array(state.analyser.frequencyBinCount);

  function frame() {
    state.micAnimId = requestAnimationFrame(frame);
    state.analyser.getByteFrequencyData(data);
    const step = Math.floor(data.length / micBarEls.length) || 1;
    micBarEls.forEach((bar, i) => {
      const v = data[i * step] / 255;
      bar.style.height = `${Math.max(3, v * 17)}px`;
    });
  }
  frame();
}

// ─── Scroll & blur ────────────────────────────────────────────────────────────
function scrollToBottom() {
  requestAnimationFrame(() => {
    messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
    applyScrollBlur();
  });
}

function applyScrollBlur() {
  const containerTop = messages.getBoundingClientRect().top;
  messages.querySelectorAll('.message').forEach((msg) => {
    const rect      = msg.getBoundingClientRect();
    const distBottom = rect.bottom - containerTop; // distance of bottom edge from container top
    const fadeZone  = 90;
    if (distBottom < fadeZone && distBottom > 0) {
      const t = Math.max(0, distBottom / fadeZone);
      msg.style.opacity = t;
      msg.style.filter  = `blur(${(1 - t) * 5}px)`;
    } else {
      msg.style.opacity = '';
      msg.style.filter  = '';
    }
  });
}

messages.addEventListener('scroll', applyScrollBlur);

// ─── Teardown ─────────────────────────────────────────────────────────────────
function teardown() {
  clearInterval(state.camInterval);
  state.camInterval = null;

  cancelAnimationFrame(state.micAnimId);
  state.micAnimId = null;

  state.micStream?.getTracks().forEach((t) => t.stop());
  state.micStream = null;

  state.videoStream?.getTracks().forEach((t) => t.stop());
  state.videoStream = null;

  state.scriptProcessor?.disconnect();
  state.scriptProcessor = null;

  state.audioCtx?.close().catch(() => {});
  state.audioCtx    = null;
  state.nextPlayTime = 0;

  state.currentUserMsg  = null;
  state.currentModelMsg = null;

  video.srcObject = null;
  camPlaceholder.style.display = '';
  recDot.classList.remove('active');
  micRing.classList.remove('active');
  micBarEls.forEach((b) => (b.style.height = ''));
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function isWsOpen() {
  return state.ws?.readyState === WebSocket.OPEN;
}

function send(obj) {
  if (isWsOpen()) state.ws.send(JSON.stringify(obj));
}

// ─── Button ───────────────────────────────────────────────────────────────────
btnToggle.addEventListener('click', () => {
  if (isWsOpen()) {
    state.ws.close();
  } else {
    btnToggle.disabled = true;
    btnToggle.textContent = 'Connecting…';
    wsConnect();
  }
});
