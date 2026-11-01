import { createAvatarView } from './avatar-view';
import { viewSettings } from './settings';
import type { MeshAvatar, LiveExpression } from 'mesh-avatar';
import './companion.css';

// ---------------------------------------------------------------------------
// 1. Starfield Background Canvas
// ---------------------------------------------------------------------------
const starCanvas = document.querySelector<HTMLCanvasElement>('#starfield')!;
const starCtx = starCanvas.getContext('2d')!;

interface Star {
  x: number;
  y: number;
  baseBr: number;
  speed: number;
  size: number;
  gold: boolean;
}

let stars: Star[] = [];

function initStars() {
  const w = (starCanvas.width = starCanvas.clientWidth || window.innerWidth);
  const h = (starCanvas.height = starCanvas.clientHeight || window.innerHeight);
  const count = Math.max(30, Math.floor((w * h) / 10000));
  stars = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: Math.random() * w,
      y: Math.random() * h,
      baseBr: 0.4 + Math.random() * 0.6,
      speed: 1.5 + Math.random() * 2.5,
      size: Math.random() > 0.85 ? 2 : 1,
      gold: Math.random() > 0.4,
    });
  }
}

window.addEventListener('resize', initStars);
initStars();

let isTabHidden = false;
document.addEventListener('visibilitychange', () => {
  isTabHidden = document.hidden;
});

function renderStars(nowMs: number) {
  if (isTabHidden) {
    requestAnimationFrame(renderStars);
    return;
  }
  const w = starCanvas.width;
  const h = starCanvas.height;
  starCtx.clearRect(0, 0, w, h);

  // Time-of-day dynamic ambient lighting
  const hour = new Date().getHours();
  // Late night (22:00 - 05:00): Cool moonlight / deep cyan-indigo
  // Evening / Dusk (18:00 - 21:59): Warm sunset amber & lavender gold
  // Daytime (05:00 - 17:59): Radiant cosmic gold & sapphire
  const isLateNight = hour >= 22 || hour < 5;
  const isEvening = hour >= 18 && hour < 22;

  // Subtle ambient backdrop tint
  if (isLateNight) {
    const nightGrad = starCtx.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, Math.max(w, h));
    nightGrad.addColorStop(0, 'rgba(8, 16, 36, 0.25)');
    nightGrad.addColorStop(1, 'rgba(3, 6, 18, 0.45)');
    starCtx.fillStyle = nightGrad;
    starCtx.fillRect(0, 0, w, h);
  } else if (isEvening) {
    const eveGrad = starCtx.createRadialGradient(w / 2, h / 2, 10, w / 2, h / 2, Math.max(w, h));
    eveGrad.addColorStop(0, 'rgba(28, 12, 28, 0.2)');
    eveGrad.addColorStop(1, 'rgba(10, 4, 18, 0.4)');
    starCtx.fillStyle = eveGrad;
    starCtx.fillRect(0, 0, w, h);
  }

  const t = nowMs / 1000;
  for (const s of stars) {
    const twinkle = s.baseBr * (0.7 + 0.3 * Math.sin(t * s.speed + s.x));
    const alpha = Math.max(0.1, Math.min(1.0, twinkle));
    if (isLateNight) {
      starCtx.fillStyle = s.gold
        ? `rgba(160, 220, 255, ${alpha * 0.9})` // moonlit icy glow
        : `rgba(90, 150, 255, ${alpha * 0.95})`; // deep twilight blue
    } else if (isEvening) {
      starCtx.fillStyle = s.gold
        ? `rgba(255, 195, 140, ${alpha})` // sunset gold
        : `rgba(215, 175, 255, ${alpha})`; // dusk lavender
    } else {
      starCtx.fillStyle = s.gold
        ? `rgba(255, 244, 184, ${alpha})`
        : `rgba(184, 244, 255, ${alpha})`;
    }
    if (s.size === 1) {
      starCtx.fillRect(s.x, s.y, 1, 1);
    } else {
      starCtx.fillRect(s.x, s.y, 2, 2);
    }
  }
  requestAnimationFrame(renderStars);
}
requestAnimationFrame(renderStars);

// ---------------------------------------------------------------------------
// 2. 60 FPS WebGL 2.5D Model
// ---------------------------------------------------------------------------
export type ViewMode = 'split' | 'focus' | 'chat';
let currentViewMode: ViewMode = (() => {
  const saved = localStorage.getItem('roxy-view-mode') || localStorage.getItem('roxy-layout');
  if (saved === 'focus' || saved === 'chat' || saved === 'split') return saved;
  if (saved === 'overlay' || saved === 'mini') return 'focus';
  return 'split';
})();
let currentLayout = currentViewMode;

let focusZoom = parseFloat(localStorage.getItem('focus.zoom') || localStorage.getItem('roxy_focus_zoom') || '1.0');
if (isNaN(focusZoom) || focusZoom < 0.8 || focusZoom > 1.6) focusZoom = 1.0;

let focusOffsetY = parseFloat(localStorage.getItem('focus.offset_y') || localStorage.getItem('roxy_focus_offset_y') || '0');
if (isNaN(focusOffsetY)) focusOffsetY = 0;

const avatarCanvas = document.querySelector<HTMLCanvasElement>('#avatar')!;
const search = new URLSearchParams(location.search);
if (!search.has('project')) search.set('project', 'roxy');
if (!search.has('fit')) search.set('fit', currentViewMode === 'focus' ? 'contain-height' : 'contain');
if (!search.has('bg')) search.set('bg', 'transparent');

const settings = viewSettings('?' + search.toString());
let avatar: MeshAvatar | null = null;

function updateAvatarFraming() {
  if (!avatar || !avatar.setFraming) return;
  if (currentViewMode === 'focus') {
    avatar.setFraming({
      fit: 'contain-height',
      zoom: focusZoom,
      offsetY: focusOffsetY,
      topMargin: 0.05,
    });
  } else {
    avatar.setFraming({
      fit: 'contain',
      zoom: 1.0,
      offsetY: 0,
      topMargin: 0.05,
    });
  }
}

function saveFocusFraming() {
  localStorage.setItem('focus.zoom', String(focusZoom));
  localStorage.setItem('focus.offset_y', String(focusOffsetY));
  localStorage.setItem('roxy_focus_zoom', String(focusZoom));
  localStorage.setItem('roxy_focus_offset_y', String(focusOffsetY));
  updateAvatarFraming();
}

// Mouse tracking
let mouseX = 0;
let mouseY = 0;
let mouseActive = false;
let mouseTimeout = 0;

window.addEventListener('mousemove', e => {
  const cx = window.innerWidth / 2;
  const cy = window.innerHeight / 2;
  mouseX = (e.clientX - cx) / cx;
  mouseY = (e.clientY - cy) / cy;
  mouseActive = true;
  clearTimeout(mouseTimeout);
  mouseTimeout = window.setTimeout(() => {
    mouseActive = false;
  }, 3000);
});

// FPS Counter
const fpsVal = document.getElementById('fps-val')!;
let frameCount = 0;
let lastFpsTime = performance.now();

let currentEyebrows: 'off' | 'subtle' = (localStorage.getItem('roxy_eyebrows') as 'off' | 'subtle') || 'subtle';
if (localStorage.getItem('roxy_eyebrows') === 'off') {
  currentEyebrows = 'subtle';
  localStorage.setItem('roxy_eyebrows', 'subtle');
}

function applyEyebrows(mode: 'off' | 'subtle') {
  currentEyebrows = mode;
  localStorage.setItem('roxy_eyebrows', mode);
  if (avatar && avatar.setLayerVisible) {
    const visible = mode === 'subtle';
    avatar.setLayerVisible('eye0_crease', visible);
    avatar.setLayerVisible('eye1_crease', visible);
  }
}

void createAvatarView(avatarCanvas, settings, (inst) => {
  if (isTabHidden) return; // Pause avatar deform when tab is hidden

  frameCount++;
  const now = performance.now();
  if (now - lastFpsTime >= 1000) {
    const fps = Math.round((frameCount * 1000) / (now - lastFpsTime));
    fpsVal.textContent = String(fps);
    frameCount = 0;
    lastFpsTime = now;
  }

  if (mouseActive) {
    inst.setAutoMotion(false);
    inst.setParameters(
      {
        angleX: mouseX * 22,
        angleY: -mouseY * 16,
        angleZ: mouseX * 8,
        gazeX: Math.max(-1, Math.min(1, mouseX * 1.4)),
        gazeY: Math.max(-1, Math.min(1, -mouseY * 1.4)),
        bodyAngleX: mouseX * 6,
      },
      0.85
    );
  } else {
    inst.setAutoMotion(true);
    inst.setAutoIdle(true);
  }
}).then(view => {
  avatar = view.avatar;
  (window as any).avatar = avatar;
  avatar.setExpression('neutral');
  avatar.setSwayGain(2.5); // Boost dynamic hair sway physics
  applyEyebrows(currentEyebrows);
  updateAvatarFraming();
  console.log(`[Companion] Roxy 60 FPS WebGL Model Initialized! Eyebrows: ${currentEyebrows}`);
});

// Interactive Head-Pat on Avatar Canvas
avatarCanvas.addEventListener('click', (e) => {
  const rect = avatarCanvas.getBoundingClientRect();
  const relY = (e.clientY - rect.top) / rect.height;
  if (relY < 0.45 && avatar) {
    const reactions = ['smile', 'shy', 'wink'] as const;
    const picked = reactions[Math.floor(Math.random() * reactions.length)];
    avatar.setExpression(picked);
    moodVal.textContent = picked;
    appendLog('roxy', 'roxy>', `[emotion:${picked}] Fufu, ${currentPreferredName}! Are you patting my head?`);
  }
});

// ---------------------------------------------------------------------------
// 3. Theming & Layout State Management
// ---------------------------------------------------------------------------
const appEl = document.getElementById('companion-app')!;
const layoutIndicator = document.getElementById('layout-indicator')!;
const logScroll = document.getElementById('log-scroll')!;
const promptInput = document.getElementById('prompt-input') as HTMLInputElement;
const moodVal = document.getElementById('mood-val')!;
const yandereVal = document.getElementById('yandere-val');
const affVal = document.getElementById('aff-val')!;
const affBar = document.getElementById('aff-bar')!;
const micVal = document.getElementById('mic-val')!;
const micBtn = document.getElementById('mic-btn') as HTMLButtonElement;
const micLevelFill = document.getElementById('mic-level-fill') as HTMLElement;
const grantMicBtn = document.getElementById('grant-mic-btn') as HTMLButtonElement;
const enableAudioBtn = document.getElementById('enable-audio-btn') as HTMLButtonElement;
const taskVal = document.getElementById('task-val')!;
const stopBtn = document.getElementById('stop-btn') as HTMLButtonElement;
const slashPalette = document.getElementById('slash-palette')!;

if (stopBtn) {
  stopBtn.addEventListener('click', () => {
    fetch(`${ROXY_API}/api/stop`, { method: 'POST' }).catch(() => {});
    appendLog('system', '[stop]', 'Stopping current agent task...');
    taskVal.textContent = 'Cancelled';
  });
}

let micSource: 'browser' | 'backend' = (localStorage.getItem('roxy-mic-source') as 'browser' | 'backend') || 'backend';
let screenAwarenessEnabled: boolean = localStorage.getItem('roxy-screen-tool') === 'true';
let pttMode: 'hold' | 'toggle' = (localStorage.getItem('roxy-mic-mode') as 'hold' | 'toggle') || 'hold';
let sttConfirm: 'off' | 'preview' = (localStorage.getItem('roxy-stt-confirm') as 'off' | 'preview') || 'off';
let previewTimeoutId: number | null = null;

function fuzzyCorrectRoxy(text: string): string {
  if (!text) return text;
  return text.replace(/\b(?:o[hx]y|rock\s*see|rock\s*sea|roxie|roxi|rocksey|roxey|rock-see|oxey)\b/gi, 'Roxy');
}

function dispatchTranscription(rawText: string) {
  const text = fuzzyCorrectRoxy(rawText);
  if (!text || !text.trim()) {
    taskVal.textContent = 'Idle';
    appendLog('system', '[info]', 'No speech detected.');
    return;
  }
  if (sttConfirm === 'preview') {
    promptInput.value = text;
    appendLog('system', '[stt-preview]', `Transcribed: "${text}" — Auto-sending in 1.5s (Esc to edit/cancel, Enter to send)`);
    if (previewTimeoutId) clearTimeout(previewTimeoutId);
    previewTimeoutId = window.setTimeout(() => {
      previewTimeoutId = null;
      const txt = promptInput.value.trim();
      promptInput.value = '';
      if (txt) void processPrompt(txt);
    }, 1500);
  } else {
    void processPrompt(text);
  }
}

function setMicSource(source: 'browser' | 'backend') {
  micSource = source;
  localStorage.setItem('roxy-mic-source', source);
  micVal.textContent = `Idle (Space/F2) [${source}]`;
}

function setScreenAwareness(enabled: boolean) {
  screenAwarenessEnabled = enabled;
  localStorage.setItem('roxy-screen-tool', enabled ? 'true' : 'false');
}

let yandereIntensity: number = parseInt(localStorage.getItem('roxy-yandere') || '4', 10);

function setYandereIntensity(val: number, broadcast = true) {
  yandereIntensity = Math.max(0, Math.min(10, val));
  localStorage.setItem('roxy-yandere', yandereIntensity.toString());
  if (yandereVal) {
    yandereVal.textContent = yandereIntensity === 0 ? '0/10 (Relax)' : `${yandereIntensity}/10`;
  }
  if (broadcast) {
    fetch(`${ROXY_API}/api/yandere`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intensity: yandereIntensity }),
    }).catch(() => {});
  }
}
setYandereIntensity(yandereIntensity, false);

const viewToggleBtn = document.getElementById('view-toggle-btn');
const avatarSubtitleEl = document.getElementById('avatar-subtitle');
const chatDrawer = document.getElementById('chat-drawer');
const drawerCloseBtn = document.getElementById('drawer-close-btn');
const drawerToggleBtn = document.getElementById('drawer-toggle-btn');
const drawerScroll = document.getElementById('drawer-scroll');
let subtitleFadeTimer: number | null = null;

function setViewMode(mode: ViewMode) {
  currentViewMode = mode;
  currentLayout = mode;
  localStorage.setItem('roxy-view-mode', mode);
  localStorage.setItem('roxy-layout', mode);
  appEl.classList.remove('mode-split', 'mode-focus', 'mode-chat', 'mode-overlay', 'mode-mini');
  appEl.classList.add(`mode-${mode}`);
  if (layoutIndicator) layoutIndicator.textContent = `[${mode}]`;
  if (viewToggleBtn) viewToggleBtn.textContent = `[View: ${mode}]`;
  updateAvatarFraming();
  setTimeout(() => {
    initStars();
    if (mode === 'focus') {
      promptInput.focus();
    }
  }, 50);
}

function cycleViewMode() {
  const modes: ViewMode[] = ['split', 'focus', 'chat'];
  const nextIdx = (modes.indexOf(currentViewMode) + 1) % modes.length;
  setViewMode(modes[nextIdx]);
}

const setLayout = setViewMode;
setViewMode(currentViewMode);

function openChatDrawer() {
  if (chatDrawer) {
    chatDrawer.classList.remove('closed');
    if (drawerScroll) drawerScroll.scrollTop = drawerScroll.scrollHeight;
  }
}

function closeChatDrawer() {
  if (chatDrawer) {
    chatDrawer.classList.add('closed');
    if (currentViewMode === 'focus') {
      promptInput.focus();
    }
  }
}

function toggleChatDrawer() {
  if (chatDrawer) {
    if (chatDrawer.classList.contains('closed')) {
      openChatDrawer();
    } else {
      closeChatDrawer();
    }
  }
}

if (drawerToggleBtn) {
  drawerToggleBtn.addEventListener('click', (e) => {
    e.preventDefault();
    toggleChatDrawer();
  });
}
if (drawerCloseBtn) {
  drawerCloseBtn.addEventListener('click', (e) => {
    e.preventDefault();
    closeChatDrawer();
  });
}
if (viewToggleBtn) {
  viewToggleBtn.addEventListener('click', (e) => {
    e.preventDefault();
    cycleViewMode();
  });
}
if (layoutIndicator) {
  layoutIndicator.addEventListener('click', (e) => {
    e.preventDefault();
    cycleViewMode();
  });
}

// Themes: 'foot-dark' | 'catppuccin' | 'gruvbox' | 'light'
let currentTheme = localStorage.getItem('roxy-theme') || 'foot-dark';
function setTheme(name: string) {
  currentTheme = name;
  localStorage.setItem('roxy-theme', name);
  document.documentElement.setAttribute('data-theme', name);
}
setTheme(currentTheme);

// CRT scanlines
let crtEnabled = localStorage.getItem('roxy-crt') === 'true';
function setCRT(enable: boolean) {
  crtEnabled = enable;
  localStorage.setItem('roxy-crt', String(enable));
  if (enable) {
    appEl.classList.add('crt-effect');
  } else {
    appEl.classList.remove('crt-effect');
  }
}
setCRT(crtEnabled);

// Affection & Mood
let affection = 56.0;
function updateAffectionDisplay(val: number) {
  affection = Math.min(100.0, Math.max(0.0, val));
  affVal.textContent = affection.toFixed(1) + '%';
  const total = 6;
  const filled = Math.min(total, Math.floor((affection / 100) * total));
  affBar.textContent = '█'.repeat(filled) + '░'.repeat(total - filled);
}

// ---------------------------------------------------------------------------
// 4. Terminal Log Output & Typewriter Streaming
// ---------------------------------------------------------------------------
function appendLog(className: string, prefixText: string, message: string) {
  const row = document.createElement('div');
  row.className = `log-row ${className}`;
  if (prefixText) {
    const prefixSpan = document.createElement('span');
    prefixSpan.className = 'prefix';
    prefixSpan.textContent = prefixText + ' ';
    row.appendChild(prefixSpan);
  }
  const contentSpan = document.createElement('span');
  contentSpan.className = 'content';
  contentSpan.textContent = message;
  row.appendChild(contentSpan);

  logScroll.appendChild(row);
  logScroll.scrollTop = logScroll.scrollHeight;

  if (drawerScroll) {
    const drawerRow = row.cloneNode(true) as HTMLElement;
    drawerScroll.appendChild(drawerRow);
    drawerScroll.scrollTop = drawerScroll.scrollHeight;
  }

  return contentSpan;
}

function streamRoxyReply(rawMessage: string, onDone?: () => void) {
  // Strip [emotion:xxx] tags from display
  const emotionMatch = rawMessage.match(/\[emotion:([a-zA-Z]+)\]/i);
  if (emotionMatch && avatar) {
    const expr = emotionMatch[1].toLowerCase() as LiveExpression;
    avatar.setExpression(expr);
    moodVal.textContent = expr;
  }
  const cleanText = rawMessage.replace(/\[emotion:[a-zA-Z]+\]/gi, '').trim();

  const contentSpan = appendLog('roxy', 'roxy>', '');
  let charIdx = 0;
  const len = cleanText.length;
  const speed = Math.max(12, Math.min(25, 1200 / Math.max(len, 1)));

  function step() {
    if (charIdx < len) {
      contentSpan.textContent = cleanText.slice(0, charIdx + 1);
      charIdx++;
      logScroll.scrollTop = logScroll.scrollHeight;
      setTimeout(step, speed);
    } else {
      contentSpan.textContent = cleanText;
      logScroll.scrollTop = logScroll.scrollHeight;
      onDone?.();
    }
  }
  step();
}

function showToast(message: string, type: 'info' | 'success' | 'error' = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const chip = document.createElement('div');
  chip.className = `toast-chip ${type}`;
  const icon = type === 'error' ? '⚠️' : type === 'success' ? '✓' : '⚡';
  const spanIcon = document.createElement('span');
  spanIcon.textContent = icon;
  const spanMsg = document.createElement('span');
  spanMsg.textContent = message;
  chip.appendChild(spanIcon);
  chip.appendChild(spanMsg);
  container.appendChild(chip);
  setTimeout(() => {
    if (chip.parentNode) chip.parentNode.removeChild(chip);
  }, 2500);
}

function appendToolActivity(summary: string, details: string) {
  const isErr = /fail|error|denied|reject/i.test(summary);
  const isSuccess = /success|ok|confirmed|started|finished/i.test(summary);
  showToast(summary, isErr ? 'error' : isSuccess ? 'success' : 'info');

  const row = document.createElement('div');
  row.className = 'log-row tool-entry';

  const header = document.createElement('div');
  header.className = 'tool-header';
  header.textContent = `● ${summary} (click to toggle)`;

  const body = document.createElement('div');
  body.className = 'tool-body collapsed';
  body.textContent = details;

  header.addEventListener('click', () => {
    body.classList.toggle('collapsed');
  });

  row.appendChild(header);
  row.appendChild(body);
  logScroll.appendChild(row);
  logScroll.scrollTop = logScroll.scrollHeight;

  if (drawerScroll) {
    const drawerRow = row.cloneNode(true) as HTMLElement;
    const dHeader = drawerRow.querySelector('.tool-header');
    const dBody = drawerRow.querySelector('.tool-body');
    if (dHeader && dBody) {
      dHeader.addEventListener('click', () => dBody.classList.toggle('collapsed'));
    }
    drawerScroll.appendChild(drawerRow);
    drawerScroll.scrollTop = drawerScroll.scrollHeight;
  }
}

// Centered Overlay Security & Permission Confirmation Modal
const confirmOverlay = document.getElementById('confirm-overlay');
const confirmModalTitle = document.getElementById('confirm-modal-title');
const confirmModalReason = document.getElementById('confirm-modal-reason');
const confirmModalCommand = document.getElementById('confirm-modal-command');
const confirmTypedWrapper = document.getElementById('confirm-typed-wrapper');
const confirmTypedInput = document.getElementById('confirm-typed-input') as HTMLInputElement | null;
const confirmAllowBtn = document.getElementById('confirm-allow-btn') as HTMLButtonElement | null;
const confirmDenyBtn = document.getElementById('confirm-deny-btn') as HTMLButtonElement | null;

let pendingConfirmation: ((allowed: boolean) => void) | null = null;
let isDangerousAction = false;

function resolveConfirmation(allowed: boolean) {
  if (confirmOverlay) confirmOverlay.classList.add('hidden');
  const cb = pendingConfirmation;
  pendingConfirmation = null;
  cb?.(allowed);
}

if (confirmAllowBtn) {
  confirmAllowBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (isDangerousAction) {
      if (confirmTypedInput && confirmTypedInput.value.trim().toLowerCase() !== 'confirm') {
        return;
      }
    }
    resolveConfirmation(true);
  });
}

if (confirmDenyBtn) {
  confirmDenyBtn.addEventListener('click', (e) => {
    e.preventDefault();
    resolveConfirmation(false);
  });
}

if (confirmTypedInput) {
  confirmTypedInput.addEventListener('input', () => {
    if (confirmAllowBtn) {
      const isTyped = confirmTypedInput.value.trim().toLowerCase() === 'confirm';
      if (isTyped) {
        confirmAllowBtn.removeAttribute('disabled');
        confirmAllowBtn.style.opacity = '1';
      } else {
        confirmAllowBtn.setAttribute('disabled', 'true');
        confirmAllowBtn.style.opacity = '0.5';
      }
    }
  });

  confirmTypedInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (confirmTypedInput.value.trim().toLowerCase() === 'confirm') {
        resolveConfirmation(true);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      resolveConfirmation(false);
    }
  });
}

function requestConfirmation(command: string, callback: (allowed: boolean) => void, dangerous = false) {
  pendingConfirmation = callback;
  isDangerousAction = dangerous || /rm\s+-rf|sudo\b|mkfs|dd\s+if|drop\s+database|format\b|kill\s+-9/i.test(command);

  if (confirmOverlay && confirmModalCommand && confirmModalReason && confirmModalTitle) {
    confirmModalCommand.textContent = command;
    if (isDangerousAction) {
      confirmModalTitle.textContent = '⚠️ Dangerous Action Confirmation';
      confirmModalReason.textContent = 'HIGH RISK ACTION: This command could alter critical system state. Type "confirm" to authorize execution.';
      if (confirmTypedWrapper) confirmTypedWrapper.classList.remove('hidden');
      if (confirmTypedInput) {
        confirmTypedInput.value = '';
        setTimeout(() => confirmTypedInput.focus(), 50);
      }
      if (confirmAllowBtn) {
        confirmAllowBtn.setAttribute('disabled', 'true');
        confirmAllowBtn.style.opacity = '0.5';
      }
    } else {
      confirmModalTitle.textContent = '🛡️ Permission Required';
      confirmModalReason.textContent = 'Action requires user permission before proceeding:';
      if (confirmTypedWrapper) confirmTypedWrapper.classList.add('hidden');
      if (confirmAllowBtn) {
        confirmAllowBtn.removeAttribute('disabled');
        confirmAllowBtn.style.opacity = '1';
        setTimeout(() => confirmAllowBtn.focus(), 50);
      }
    }
    confirmOverlay.classList.remove('hidden');
  }

  // Also append to terminal log and chat drawer
  const box = document.createElement('div');
  box.className = 'confirm-box';

  const action = document.createElement('div');
  action.className = 'confirm-action';
  action.textContent = `Action: ${command}`;

  const query = document.createElement('div');
  query.className = 'confirm-query';
  query.innerHTML = isDangerousAction
    ? `Dangerous action! Type <span class="highlight">confirm</span> or confirm in overlay.`
    : `Allow execution? [<span class="key-hint">y</span>/<span class="key-hint">N</span>] (or confirm in overlay)`;

  box.appendChild(action);
  box.appendChild(query);
  logScroll.appendChild(box);
  logScroll.scrollTop = logScroll.scrollHeight;

  if (drawerScroll) {
    const cloneBox = box.cloneNode(true) as HTMLElement;
    drawerScroll.appendChild(cloneBox);
    drawerScroll.scrollTop = drawerScroll.scrollHeight;
  }
}
(window as any).requestConfirmation = requestConfirmation;

// ---------------------------------------------------------------------------
// Settings Modal & Interactive Configuration UI
// ---------------------------------------------------------------------------
const settingsOverlay = document.getElementById('settings-overlay');
const settingsBtn = document.getElementById('settings-btn') as HTMLButtonElement | null;
const focusSettingsBtn = document.getElementById('focus-settings-btn') as HTMLButtonElement | null;
const settingsCloseBtn = document.getElementById('settings-close-btn') as HTMLButtonElement | null;
const settingsCloseFooterBtn = document.getElementById('settings-close-footer-btn') as HTMLButtonElement | null;
const settingNameInput = document.getElementById('setting-name-input') as HTMLInputElement | null;
const settingNameSaveBtn = document.getElementById('setting-name-save-btn') as HTMLButtonElement | null;
const settingVoiceSelect = document.getElementById('setting-voice-select') as HTMLSelectElement | null;
const settingVoiceTestBtn = document.getElementById('setting-voice-test-btn') as HTMLButtonElement | null;
const settingSpeedSlider = document.getElementById('setting-speed-slider') as HTMLInputElement | null;
const settingSpeedVal = document.getElementById('setting-speed-val');
const settingDevotionSlider = document.getElementById('setting-devotion-slider') as HTMLInputElement | null;
const settingDevotionVal = document.getElementById('setting-devotion-val');
const settingDevotionDesc = document.getElementById('setting-devotion-desc');
const settingFeedback = document.getElementById('setting-feedback');
const presetChips = document.querySelectorAll<HTMLButtonElement>('.preset-chip');

let currentVoiceSpeed: number = 1.15;

function showSettingFeedback(msg: string, isError = false) {
  if (!settingFeedback) return;
  settingFeedback.textContent = msg;
  settingFeedback.classList.toggle('error', isError);
  settingFeedback.classList.remove('hidden');
  setTimeout(() => {
    settingFeedback?.classList.add('hidden');
  }, 3500);
}

function openSettingsModal() {
  if (!settingsOverlay) return;
  fetch(`${ROXY_API}/api/settings`)
    .then(async res => {
      const d = await res.json();
      if (d.preferred_name && settingNameInput) {
        currentPreferredName = d.preferred_name;
        settingNameInput.value = d.preferred_name;
      }
      if (d.voice && settingVoiceSelect) {
        currentVoiceModel = d.voice;
        settingVoiceSelect.value = d.voice;
      }
      if (d.speed !== undefined && settingSpeedSlider && settingSpeedVal) {
        currentVoiceSpeed = d.speed;
        settingSpeedSlider.value = String(d.speed);
        settingSpeedVal.textContent = d.speed.toFixed(2) + 'x';
        presetChips.forEach(chip => {
          chip.classList.toggle('active', parseFloat(chip.dataset.speed || '0') === d.speed);
        });
      }
      if (d.yandere_intensity !== undefined && settingDevotionSlider && settingDevotionVal && settingDevotionDesc) {
        settingDevotionSlider.value = String(d.yandere_intensity);
        settingDevotionVal.textContent = `${d.yandere_intensity}/10`;
        const tierNames: Record<number, string> = {
          0: 'Professional Mentor (Relax Mode)',
          1: 'Gentle Protective Companion',
          2: 'Gentle Protective Companion',
          3: 'Gentle Protective Companion',
          4: 'Devoted Possessive Partner (Default)',
          5: 'Devoted Possessive Partner',
          6: 'Devoted Possessive Partner',
          7: 'Deeply Obsessive & Doting',
          8: 'Deeply Obsessive & Doting',
          9: 'Total Attachment',
          10: 'Total Attachment',
        };
        settingDevotionDesc.textContent = tierNames[d.yandere_intensity] || 'Companion';
      }
    })
    .catch(() => {});

  if (settingNameInput) settingNameInput.value = currentPreferredName;
  if (settingVoiceSelect) settingVoiceSelect.value = currentVoiceModel;
  settingsOverlay.classList.remove('hidden');
}

function closeSettingsModal() {
  if (settingsOverlay) settingsOverlay.classList.add('hidden');
}

if (settingsBtn) settingsBtn.addEventListener('click', openSettingsModal);
if (focusSettingsBtn) focusSettingsBtn.addEventListener('click', openSettingsModal);
if (settingsCloseBtn) settingsCloseBtn.addEventListener('click', closeSettingsModal);
if (settingsCloseFooterBtn) settingsCloseFooterBtn.addEventListener('click', closeSettingsModal);

if (settingsOverlay) {
  settingsOverlay.addEventListener('click', (e) => {
    if (e.target === settingsOverlay) closeSettingsModal();
  });
}

if (settingNameSaveBtn && settingNameInput) {
  settingNameSaveBtn.addEventListener('click', () => {
    const newName = settingNameInput.value.trim();
    if (!newName) return;
    fetch(`${ROXY_API}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName }),
    })
      .then(async res => {
        const d = await res.json();
        currentPreferredName = d.preferred_name || newName;
        showSettingFeedback(`Saved! Roxy will address you as "${currentPreferredName}".`);
        appendLog('system', '[settings]', `Preferred name updated to [${currentPreferredName}].`);
      })
      .catch(err => showSettingFeedback(`Error: ${err.message}`, true));
  });
}

if (settingVoiceSelect) {
  settingVoiceSelect.addEventListener('change', () => {
    const chosenVoice = settingVoiceSelect.value;
    fetch(`${ROXY_API}/api/voice/set`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice: chosenVoice }),
    })
      .then(async res => {
        const d = await res.json();
        currentVoiceModel = d.voice;
        currentVoiceProvider = d.provider;
        updateVoiceBadge(d.status_label);
        showSettingFeedback(`Voice switched to "${d.voice}" (${d.provider})!`);
        appendLog('system', '[settings]', `Voice model changed to [${d.voice}].`);
      })
      .catch(err => showSettingFeedback(`Error: ${err.message}`, true));
  });
}

if (settingVoiceTestBtn) {
  settingVoiceTestBtn.addEventListener('click', () => {
    const testPhrase = `Hello ${currentPreferredName}! How does my voice sound?`;
    fetch(`${ROXY_API}/api/tts?text=${encodeURIComponent(testPhrase)}&meta=true`)
      .then(async res => {
        const d = await res.json();
        if (d.audio_b64) {
          const snd = new Audio(`data:audio/wav;base64,${d.audio_b64}`);
          snd.play().catch(() => {});
        }
      })
      .catch(err => showSettingFeedback(`Failed to play test audio: ${err.message}`, true));
  });
}

if (settingSpeedSlider && settingSpeedVal) {
  settingSpeedSlider.addEventListener('input', () => {
    const val = parseFloat(settingSpeedSlider.value);
    settingSpeedVal.textContent = val.toFixed(2) + 'x';
    presetChips.forEach(chip => {
      chip.classList.toggle('active', parseFloat(chip.dataset.speed || '0') === val);
    });
  });
  settingSpeedSlider.addEventListener('change', () => {
    const val = parseFloat(settingSpeedSlider.value);
    fetch(`${ROXY_API}/api/voice/speed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed: val }),
    })
      .then(async res => {
        const d = await res.json();
        currentVoiceSpeed = d.speed;
        showSettingFeedback(`Voice speed set to ${d.speed.toFixed(2)}x.`);
      })
      .catch(err => showSettingFeedback(`Error: ${err.message}`, true));
  });
}

presetChips.forEach(chip => {
  chip.addEventListener('click', () => {
    const speed = parseFloat(chip.dataset.speed || '1.15');
    if (settingSpeedSlider) settingSpeedSlider.value = String(speed);
    if (settingSpeedVal) settingSpeedVal.textContent = speed.toFixed(2) + 'x';
    presetChips.forEach(c => c.classList.toggle('active', c === chip));
    fetch(`${ROXY_API}/api/voice/speed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed }),
    })
      .then(async res => {
        const d = await res.json();
        currentVoiceSpeed = d.speed;
        showSettingFeedback(`Voice speed set to ${d.speed.toFixed(2)}x.`);
      })
      .catch(err => showSettingFeedback(`Error: ${err.message}`, true));
  });
});

if (settingDevotionSlider && settingDevotionVal && settingDevotionDesc) {
  settingDevotionSlider.addEventListener('input', () => {
    const val = parseInt(settingDevotionSlider.value, 10);
    settingDevotionVal.textContent = `${val}/10`;
    const tierNames: Record<number, string> = {
      0: 'Professional Mentor (Relax Mode)',
      1: 'Gentle Protective Companion',
      2: 'Gentle Protective Companion',
      3: 'Gentle Protective Companion',
      4: 'Devoted Possessive Partner (Default)',
      5: 'Devoted Possessive Partner',
      6: 'Devoted Possessive Partner',
      7: 'Deeply Obsessive & Doting',
      8: 'Deeply Obsessive & Doting',
      9: 'Total Attachment',
      10: 'Total Attachment',
    };
    settingDevotionDesc.textContent = tierNames[val] || 'Companion';
  });
  settingDevotionSlider.addEventListener('change', () => {
    const val = parseInt(settingDevotionSlider.value, 10);
    setYandereIntensity(val);
    fetch(`${ROXY_API}/api/yandere`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intensity: val }),
    })
      .then(async res => {
        const d = await res.json();
        showSettingFeedback(`Devotion set to ${val}/10.`);
      })
      .catch(err => showSettingFeedback(`Error: ${err.message}`, true));
  });
}

// Focus Overlay Controls Bar & Music Player Chip
const focusMicBtn = document.getElementById('focus-mic-btn');
const focusVoiceBtn = document.getElementById('focus-voice-btn');
const focusStopBtn = document.getElementById('focus-stop-btn');
const npChip = document.getElementById('now-playing-chip');
const npTitle = document.getElementById('now-playing-title');
const npPauseBtn = document.getElementById('np-pause-btn');
const npStopBtn = document.getElementById('np-stop-btn');

function updateNowPlayingChip(title: string | null, isPlaying = true) {
  if (!npChip) return;
  if (!title) {
    npChip.classList.add('hidden');
  } else {
    npChip.classList.remove('hidden');
    if (npTitle) npTitle.textContent = title;
    if (npPauseBtn) npPauseBtn.textContent = isPlaying ? '⏸' : '▶';
  }
}

async function syncMusicStatus() {
  try {
    const res = await fetch(`${ROXY_API}/api/music/status`);
    if (!res.ok) return;
    const data = await res.json();
    const track = data.track;
    if (track && track.title) {
      updateNowPlayingChip(`${track.title} · ${track.channel}`, !data.paused);
    } else {
      updateNowPlayingChip(null);
    }
  } catch {}
}
setInterval(syncMusicStatus, 3000);
syncMusicStatus();

function duckMusic(duck: boolean) {
  fetch(`${ROXY_API}/api/music/duck`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duck }),
  }).catch(() => {});
}

if (npPauseBtn) {
  npPauseBtn.addEventListener('click', (e) => {
    e.preventDefault();
    fetch(`${ROXY_API}/api/music/toggle`, { method: 'POST' }).catch(() => {});
  });
}

if (npStopBtn) {
  npStopBtn.addEventListener('click', (e) => {
    e.preventDefault();
    fetch(`${ROXY_API}/api/music/stop`, { method: 'POST' }).catch(() => {});
    updateNowPlayingChip(null);
  });
}

if (focusStopBtn) {
  focusStopBtn.addEventListener('click', (e) => {
    e.preventDefault();
    fetch(`${ROXY_API}/api/stop`, { method: 'POST' }).catch(() => {});
    appendLog('system', '[stop]', 'Stopped active agent task.');
    taskVal.textContent = 'Cancelled';
    if (avatarSubtitleEl) {
      avatarSubtitleEl.classList.remove('visible');
      avatarSubtitleEl.textContent = '';
    }
  });
}

if (focusVoiceBtn) {
  focusVoiceBtn.addEventListener('click', (e) => {
    e.preventDefault();
    setVoiceMute(!voiceMuted);
    appendLog('system', '[voice]', `Voice speech ${voiceMuted ? 'muted' : 'unmuted'}.`);
  });
}

if (focusMicBtn) {
  focusMicBtn.addEventListener('click', (e) => {
    e.preventDefault();
    bargeIn();
    if (isListening) void stopVoiceInput();
    else void startVoiceInput();
  });
}

// ---------------------------------------------------------------------------
// 5. Audio Playback & Real-Time Lip-Sync
// ---------------------------------------------------------------------------
const ROXY_API = 'http://127.0.0.1:5174';
let currentAudio: HTMLAudioElement | null = null;
let audioCtx: AudioContext | null = null;
let lipSyncRaf = 0;

interface WordTiming {
  word: string;
  start: number;
  end: number;
  duration?: number;
}

interface VisemeCue {
  time: number;
  end: number;
  viseme: string;
}

interface AudioChunkItem {
  index: number;
  url: string;
  text: string;
  audio: HTMLAudioElement;
  wordTimings?: WordTiming[];
  visemes?: VisemeCue[];
  provider?: string;
  statusLabel?: string;
}

let audioQueue: AudioChunkItem[] = [];
let isQueuePlaying = false;
let syncTextToVoice: boolean = localStorage.getItem('roxy-sync-text') === 'true';
let voiceMuted: boolean = localStorage.getItem('roxy-voice-muted') === 'true';
let lipsyncOffsetMs: number = parseFloat(localStorage.getItem('roxy_lipsync_offset_ms') || '0.0');
let currentVoiceProvider: string = 'local';
let currentVoiceModel: string = 'jf_alpha';
let currentPreferredName: string = 'Sir';

let liveStreamingSpan: HTMLElement | null = null;
let previousChunksText: string = '';

const voiceMuteBtn = document.getElementById('voice-mute-btn') as HTMLButtonElement | null;
const voiceModeBtn = document.getElementById('voice-mode-btn') as HTMLButtonElement | null;
const voiceModeVal = document.getElementById('voice-mode-val') as HTMLElement | null;

function updateVoiceBadge(label: string) {
  if (voiceModeVal) {
    voiceModeVal.textContent = label;
    if (label.toLowerCase().includes('cloud')) {
      voiceModeVal.className = 'magenta';
    } else {
      voiceModeVal.className = 'cyan';
    }
  }
}

// Fetch initial voice provider & settings
fetch(`${ROXY_API}/api/settings`)
  .then(async res => {
    const d = await res.json();
    currentVoiceProvider = d.provider || 'local';
    currentVoiceModel = d.voice || 'jf_alpha';
    if (d.preferred_name) {
      currentPreferredName = d.preferred_name;
    }
    updateVoiceBadge(d.status_label || `[Voice: ${currentVoiceProvider}]`);
  })
  .catch(() => {
    fetch(`${ROXY_API}/api/voice/provider`)
      .then(async res => {
        const d = await res.json();
        currentVoiceProvider = d.provider || 'local';
        updateVoiceBadge(d.status_label || `[Voice: ${currentVoiceProvider}]`);
      })
      .catch(() => {});
  });

if (voiceModeBtn) {
  voiceModeBtn.addEventListener('click', () => {
    const nextProv = currentVoiceProvider === 'local' ? 'edge' : 'local';
    fetch(`${ROXY_API}/api/voice/provider`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: nextProv }),
    })
      .then(async res => {
        const d = await res.json();
        currentVoiceProvider = d.provider;
        updateVoiceBadge(d.status_label);
        appendLog('system', '[voice]', `Switched voice provider to ${d.provider} (${d.status_label}).`);
      })
      .catch(err => appendLog('system', '[error]', `Failed to toggle voice provider: ${err.message}`));
  });
}

function setVoiceMute(muted: boolean) {
  voiceMuted = muted;
  localStorage.setItem('roxy-voice-muted', muted ? 'true' : 'false');
  if (voiceMuteBtn) {
    voiceMuteBtn.textContent = muted ? '🔇 Voice: MUTED' : '🔊 Voice: ON';
    voiceMuteBtn.classList.toggle('muted', muted);
  }
  const focusVoiceBtn = document.getElementById('focus-voice-btn');
  if (focusVoiceBtn) {
    focusVoiceBtn.textContent = muted ? '🔇' : '🔊';
    focusVoiceBtn.title = muted ? 'Voice: MUTED (F3 to unmute)' : 'Voice: ON (F3 to mute)';
  }
  if (muted && currentAudio) {
    bargeIn();
  }
}

if (voiceMuteBtn) {
  setVoiceMute(voiceMuted);
  voiceMuteBtn.addEventListener('click', () => {
    setVoiceMute(!voiceMuted);
    appendLog('system', '[voice]', `Voice speech ${voiceMuted ? 'muted' : 'unmuted'}. (F3)`);
  });
}

function bargeIn() {
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.currentTime = 0;
    } catch {}
    currentAudio = null;
  }
  audioQueue = [];
  isQueuePlaying = false;
  cancelAnimationFrame(lipSyncRaf);
  if (avatar) {
    avatar.setSpeaking(false);
    avatar.stopLipSync();
    avatar.holdMouth('n');
  }
  if (taskVal.textContent === 'Speaking') {
    taskVal.textContent = 'Idle';
  }
}

function queueAudioChunk(
  chunkIndex: number,
  audioUrl: string,
  text: string,
  wordTimings?: WordTiming[],
  visemes?: VisemeCue[],
  provider?: string,
  statusLabel?: string,
) {
  if (statusLabel) {
    updateVoiceBadge(statusLabel);
    if (provider) currentVoiceProvider = provider;
  }
  if (voiceMuted) return;

  const audio = new Audio(audioUrl);
  audio.crossOrigin = 'anonymous';
  audio.preload = 'auto';

  audioQueue.push({
    index: chunkIndex,
    url: audioUrl,
    text,
    audio,
    wordTimings,
    visemes,
    provider,
    statusLabel,
  });
  if (!isQueuePlaying) {
    playNextAudioQueueItem();
  }
}

function playNextAudioQueueItem() {
  if (!audioQueue.length) {
    isQueuePlaying = false;
    if (avatar) {
      avatar.setSpeaking(false);
      avatar.stopLipSync();
      avatar.holdMouth('n');
    }
    taskVal.textContent = 'Idle';
    return;
  }

  isQueuePlaying = true;
  const item = audioQueue.shift()!;
  playSingleAudioWithLipSync(item, () => {
    playNextAudioQueueItem();
  });
}

function playSingleAudioWithLipSync(item: AudioChunkItem, onEnded?: () => void) {
  const audio = item.audio;
  const fallbackText = item.text;
  if (currentAudio && currentAudio !== audio) {
    currentAudio.pause();
  }
  currentAudio = audio;
  cancelAnimationFrame(lipSyncRaf);

  try {
    if (!audioCtx) {
      const AudioCtxClass = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioCtxClass) audioCtx = new AudioCtxClass();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      void audioCtx.resume();
    }

    if (audioCtx) {
      try {
        const source = audioCtx.createMediaElementSource(audio);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        analyser.connect(audioCtx.destination);

        const buffer = new Uint8Array(analyser.frequencyBinCount);
        const vowels: Array<'a' | 'o' | 'i' | 'u' | 'e'> = ['a', 'o', 'i', 'u', 'e'];
        let vIndex = 0;
        const words = fallbackText.split(/\s+/).filter(Boolean);

        const track = () => {
          if (!currentAudio || currentAudio.paused || currentAudio.ended) {
            if (avatar) {
              avatar.setSpeaking(false);
              avatar.stopLipSync();
              avatar.holdMouth('n');
            }
            return;
          }

          const curTime = audio.currentTime + (lipsyncOffsetMs / 1000.0);

          // 1. Viseme Mouth Synchronization (Rhubarb or WordBoundary phonemes)
          let mouthAssigned = false;
          if (item.visemes && item.visemes.length > 0) {
            const cue = item.visemes.find(v => curTime >= v.time && curTime < v.end);
            if (cue) {
              const rawShape = cue.viseme.toLowerCase();
              const vShape = rawShape === 'closed' ? 'n' : rawShape;
              if (['a', 'i', 'u', 'e', 'o', 'n'].includes(vShape)) {
                if (avatar) {
                  avatar.setSpeaking(vShape !== 'n');
                  avatar.holdMouth(vShape as any);
                  mouthAssigned = true;
                }
              }
            }
          }

          // 2. Amplitude-based fallback / envelope tracking
          analyser.getByteFrequencyData(buffer);
          let sum = 0;
          for (let i = 0; i < buffer.length; i++) sum += buffer[i];
          const avg = sum / buffer.length;
          const vol = Math.min(1.0, avg / 110.0);

          if (avatar) {
            avatar.setVoiceLevel(vol);
            if (!mouthAssigned) {
              if (vol > 0.08) {
                avatar.setSpeaking(true);
                vIndex = (vIndex + 1) % vowels.length;
                avatar.holdMouth(vowels[vIndex]);
              } else {
                avatar.holdMouth('n');
              }
            }
          }

          // 3. Word-by-word streaming text reveal against audio clock
          let currentSubtitle = '';
          if (item.wordTimings && item.wordTimings.length > 0) {
            const activeWords = item.wordTimings
              .filter(w => curTime >= w.start)
              .map(w => w.word);
            currentSubtitle = activeWords.join(' ');
          } else if (words.length > 0) {
            // Sentence-level proportional reveal fallback
            const progress = Math.min(1.0, audio.currentTime / (audio.duration || 1.0));
            const wordCount = Math.min(words.length, Math.ceil(progress * words.length));
            currentSubtitle = words.slice(0, wordCount).join(' ');
          } else {
            currentSubtitle = fallbackText;
          }

          if (syncTextToVoice && liveStreamingSpan && currentSubtitle) {
            liveStreamingSpan.textContent = previousChunksText + (previousChunksText ? ' ' : '') + currentSubtitle;
            logScroll.scrollTop = logScroll.scrollHeight;
          }

          if (avatarSubtitleEl && currentSubtitle) {
            avatarSubtitleEl.textContent = currentSubtitle;
            avatarSubtitleEl.classList.add('visible');
          }

          lipSyncRaf = requestAnimationFrame(track);
        };

        audio.onplay = () => {
          duckMusic(true);
          if (avatar) avatar.setSpeaking(true);
          if (avatarSubtitleEl && fallbackText) {
            avatarSubtitleEl.textContent = fallbackText;
            avatarSubtitleEl.classList.add('visible');
          }
          track();
        };
      } catch (err) {
        // Fallback if media element already connected or cross-origin restrictions
      }
    }

    audio.onended = () => {
      duckMusic(false);
      cancelAnimationFrame(lipSyncRaf);
      if (syncTextToVoice && liveStreamingSpan) {
        previousChunksText += (previousChunksText ? ' ' : '') + fallbackText;
        liveStreamingSpan.textContent = previousChunksText;
      }
      if (avatarSubtitleEl) {
        if (subtitleFadeTimer) clearTimeout(subtitleFadeTimer);
        subtitleFadeTimer = window.setTimeout(() => {
          if (avatarSubtitleEl) avatarSubtitleEl.classList.remove('visible');
        }, 1200);
      }
      onEnded?.();
    };

    audio.onerror = () => {
      duckMusic(false);
      onEnded?.();
    };

    audio.play().catch(e => {
      duckMusic(false);
      if (enableAudioBtn) enableAudioBtn.classList.remove('hidden');
      onEnded?.();
    });
  } catch (err) {
    duckMusic(false);
    onEnded?.();
  }
}

function speakWithLipSync(
  audioUrl: string,
  fallbackText: string,
  wordTimings?: WordTiming[],
  visemes?: VisemeCue[],
  provider?: string,
  statusLabel?: string,
) {
  queueAudioChunk(0, audioUrl, fallbackText, wordTimings, visemes, provider, statusLabel);
}

if (enableAudioBtn) {
  enableAudioBtn.addEventListener('click', () => {
    enableAudioBtn.classList.add('hidden');
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    ctx.resume();
    appendLog('system', '[audio]', 'Audio playback unlocked by user gesture.');
  });
}

function speakFallback(text: string) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const clean = text.replace(/\[emotion:[a-zA-Z]+\]/gi, '').trim();
  const utt = new SpeechSynthesisUtterance(clean);
  utt.pitch = 1.45;
  utt.rate = 1.05;

  const voices = window.speechSynthesis.getVoices();
  const cute = voices.find(v => /female|girl|zira|samantha|kyoko/i.test(v.name));
  if (cute) utt.voice = cute;

  if (avatar) avatar.setSpeaking(true);
  let step = 0;
  const vowels: Array<'a' | 'o' | 'i' | 'u' | 'e'> = ['a', 'o', 'i', 'u', 'e'];
  const interval = setInterval(() => {
    if (!avatar || !window.speechSynthesis.speaking) {
      clearInterval(interval);
      if (avatar) {
        avatar.setSpeaking(false);
        avatar.stopLipSync();
        avatar.holdMouth('n');
      }
      return;
    }
    avatar.holdMouth(vowels[step % vowels.length]);
    step++;
  }, 110);

  utt.onend = () => {
    clearInterval(interval);
    if (avatar) {
      avatar.setSpeaking(false);
      avatar.stopLipSync();
      avatar.holdMouth('n');
    }
    taskVal.textContent = 'Idle';
  };
  window.speechSynthesis.speak(utt);
}

// ---------------------------------------------------------------------------
// 6. Interaction Pipeline & Backend Connection
// ---------------------------------------------------------------------------
async function processPrompt(message: string) {
  const val = message.trim();
  if (!val) return;

  // Handle pending security confirmation
  if (pendingConfirmation) {
    const cb = pendingConfirmation;
    pendingConfirmation = null;
    if (/^y(es)?$/i.test(val)) {
      appendLog('system', '[ok]', `Command confirmed and approved.`);
      cb(true);
    } else {
      appendLog('system', '[info]', `Command canceled.`);
      cb(false);
    }
    return;
  }

  // Handle Slash Commands
  if (val.startsWith('/')) {
    handleSlashCommand(val);
    return;
  }

  // Handle Screen Awareness tool query (Off by default, requires explicit confirmation)
  if (/(what('s| is)|describe|look at) (on )?(my |the )?screen/i.test(val)) {
    if (!screenAwarenessEnabled) {
      appendLog('you', 'you>', val);
      const msg = "Screen awareness is currently disabled. You can enable it by typing /screen on to let me inspect your display.";
      streamRoxyReply(msg);
      speakFallback(msg);
      taskVal.textContent = 'Idle';
      return;
    }

    requestConfirmation("Allow screen capture to inspect your display? [y/N]", async (approved) => {
      if (!approved) {
        appendLog('roxy', 'roxy>', "Understood. I will not capture your screen without your approval.");
        taskVal.textContent = 'Idle';
        return;
      }

      appendLog('tool', '●', 'Capturing screen display (grim / X11)...');
      taskVal.textContent = 'Capturing screen...';
      try {
        const capRes = await fetch(`${ROXY_API}/api/screen/capture`, { method: 'POST' });
        if (!capRes.ok) {
          const errD = await capRes.json().catch(() => ({}));
          throw new Error(errD.error || `HTTP ${capRes.status}`);
        }
        const capData = await capRes.json();
        appendLog('system', '[screenshot]', `Display captured: ${capData.url}`);

        taskVal.textContent = 'Thinking (Vision)...';
        const anaRes = await fetch(`${ROXY_API}/api/screen/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: val }),
        });
        if (!anaRes.ok) {
          const errData = await anaRes.json().catch(() => ({}));
          throw new Error(errData.error || `HTTP ${anaRes.status}`);
        }
        const anaData = await anaRes.json();
        taskVal.textContent = 'Speaking';
        if (avatar) avatar.setExpression(anaData.emotion as LiveExpression);
        moodVal.textContent = anaData.emotion;
        streamRoxyReply(anaData.reply);
        speakWithLipSync(anaData.audio_url, anaData.reply);
      } catch (e: any) {
        appendLog('system', '[error]', `Screen awareness error: ${e.message}`);
        taskVal.textContent = e.message;
        if (avatar) avatar.setExpression('halfLidded');
        moodVal.textContent = 'halfLidded';
      }
    });
    return;
  }

  // Barge-in: interrupt previous speech immediately on new user input
  bargeIn();

  // Display user prompt in terminal log
  appendLog('you', 'you>', val);
  taskVal.textContent = 'Thinking...';
  if (avatar) avatar.setExpression('halfLidded');
  moodVal.textContent = 'Thinking';

  try {
    const res = await fetch(`${ROXY_API}/api/chat?stream=true`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify({ message: val, lang: 'en' }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    if (!res.body) throw new Error('Response body empty');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // Create live roxy streaming log row
    let roxyRow: HTMLElement | null = null;
    let contentSpan: HTMLElement | null = null;
    let fullReply = '';

    function ensureRoxyRow() {
      if (!roxyRow) {
        roxyRow = document.createElement('div');
        roxyRow.className = 'log-row roxy-entry';
        const prefixSpan = document.createElement('span');
        prefixSpan.className = 'log-prefix';
        prefixSpan.textContent = 'roxy> ';
        contentSpan = document.createElement('span');
        contentSpan.className = 'log-content';
        roxyRow.appendChild(prefixSpan);
        roxyRow.appendChild(contentSpan);
        logScroll.appendChild(roxyRow);
        liveStreamingSpan = contentSpan;
        previousChunksText = '';
      }
    }

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data: ')) continue;
        const jsonStr = trimmed.slice(6);
        try {
          const evt = JSON.parse(jsonStr);

          if (evt.type === 'token') {
            fullReply += evt.token;
            // Clean emotion tags & tool tags from live text
            const displayClean = fullReply
              .replace(/\[emotion:[^\]]*\]/gi, '')
              .replace(/<tool_call(?:\s+[^>]*)?>[\s\S]*?(?:<\/tool_call>|$)/gi, '')
              .replace(/```(?:json)?\s*\{[\s\S]*?\}\s*```/gi, '')
              .trimStart();
            ensureRoxyRow();
            const targetSpan = contentSpan as HTMLElement | null;
            if (!syncTextToVoice && targetSpan) {
              targetSpan.textContent = displayClean;
              logScroll.scrollTop = logScroll.scrollHeight;
            }
          } else if (evt.type === 'emotion') {
            if (avatar) avatar.setExpression(evt.emotion as LiveExpression);
            moodVal.textContent = evt.emotion;
          } else if (evt.type === 'tool_start') {
            taskVal.textContent = `Running ${evt.tool}...`;
            appendToolActivity(`Running tool: ${evt.tool}`, JSON.stringify(evt.args, null, 2));
          } else if (evt.type === 'tool_end') {
            taskVal.textContent = 'Thinking...';
            const statusStr = evt.success ? 'Success' : 'Failed';
            appendToolActivity(`Ran ${evt.tool} (${statusStr})`, evt.output);
          } else if (evt.type === 'confirm_required') {
            taskVal.textContent = 'Confirmation Required';
            if (evt.objection) {
              appendLog('roxy', 'roxy>', evt.objection);
            }
            requestConfirmation(`${evt.tool}(${JSON.stringify(evt.args)})`, async (allowed) => {
              if (allowed) {
                appendLog('system', '[confirm]', `Approved execution of ${evt.tool}.`);
                taskVal.textContent = `Running ${evt.tool}...`;
                try {
                  const confRes = await fetch(`${ROXY_API}/api/confirm`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action_id: evt.action_id, approved: true }),
                  });
                  const confData = await confRes.json();
                  appendToolActivity(`Ran ${confData.tool} (Confirmed)`, confData.output);
                } catch (ce: any) {
                  appendLog('system', '[error]', `Confirmation error: ${ce.message}`);
                }
              } else {
                appendLog('system', '[confirm]', `Cancelled execution of ${evt.tool}.`);
                fetch(`${ROXY_API}/api/confirm`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ action_id: evt.action_id, approved: false }),
                }).catch(() => {});
              }
              taskVal.textContent = 'Idle';
            });
          } else if (evt.type === 'audio_chunk') {
            if (!voiceMuted) {
              queueAudioChunk(
                evt.chunk_index,
                evt.audio_url,
                evt.text,
                evt.word_timings,
                evt.visemes,
                evt.provider,
                evt.status_label,
              );
            }
          } else if (evt.type === 'stop') {
            bargeIn();
            appendLog('system', '[stop]', evt.message || 'Execution stopped.');
            taskVal.textContent = 'Cancelled';
          } else if (evt.type === 'done') {
            taskVal.textContent = isQueuePlaying ? 'Speaking' : 'Idle';
            if (evt.status_label) updateVoiceBadge(evt.status_label);
            if (evt.affection) updateAffectionDisplay(evt.affection);
            if (evt.preferred_name) {
              currentPreferredName = evt.preferred_name;
            } else {
              const mName = /\b(?:call me|my name is|address me as)\s+([A-Za-z0-9_\-\s]{2,25}?)(?:\s*[,.!?]|$)/i.exec(val);
              if (mName && !['back', 'later', 'tomorrow', 'tonight', 'soon', 'now', 'maybe', 'what', 'how'].includes(mName[1].trim().toLowerCase())) {
                currentPreferredName = mName[1].trim();
              }
            }
            if (evt.emotion && avatar) avatar.setExpression(evt.emotion as LiveExpression);
            if (evt.emotion) moodVal.textContent = evt.emotion;
            // Fallback for short non-chunked replies
            if (!isQueuePlaying && !audioQueue.length && evt.audio_url && !voiceMuted) {
              speakWithLipSync(
                evt.audio_url,
                evt.reply,
                evt.word_timings,
                evt.visemes,
                evt.provider,
                evt.status_label,
              );
            }
            if (!syncTextToVoice || voiceMuted) {
              ensureRoxyRow();
              const spanTarget = contentSpan as HTMLElement | null;
              if (spanTarget) spanTarget.textContent = evt.reply;
            }
          } else if (evt.type === 'error') {
            throw new Error(evt.error);
          }
        } catch (pe) {
          // JSON parsing error or application error
        }
      }
    }
  } catch (err: any) {
    console.error('[Roxy LLM Error]', err);
    const errText = err.message || 'LLM error';
    taskVal.textContent = errText;
    appendLog('system', '[error]', errText);
    if (avatar) avatar.setExpression('halfLidded');
    moodVal.textContent = 'halfLidded';
    // NEVER substitute a fake or canned reply!
  }
}

// ---------------------------------------------------------------------------
// 7. Slash Commands Palette & Execution
// ---------------------------------------------------------------------------
const COMMANDS = [
  { cmd: '/view', desc: 'Toggle or set view mode: split | focus | chat (F4 to cycle)' },
  { cmd: '/layout', desc: 'Toggle or set layout mode (alias to /view)' },
  { cmd: '/music', desc: 'Control background music: /music [play <song> | pause | resume | stop | next | prev | vol <0-100>]' },
  { cmd: '/tasks', desc: 'List active background companion tasks' },
  { cmd: '/doctor', desc: 'Run environment and system diagnostic health check' },
  { cmd: '/settings', desc: 'System settings: /settings [voice <id> | name <name> | speed <x>]' },
  { cmd: '/name', desc: 'Set or view consistent address name: /name <preferred_name>' },
  { cmd: '/theme', desc: 'Switch color theme: foot-dark | catppuccin | gruvbox | light' },
  { cmd: '/status', desc: 'Show character stats, affection, devotion & system info' },
  { cmd: '/yandere', desc: 'Set devotion & possessiveness intensity (0-10): /yandere <0-10>' },
  { cmd: '/relax', desc: 'Safe word: drops devotion to 0 (Professional Mentor mode)' },
  { cmd: '/emotion', desc: 'Set expression: smile, shy, surprise, halfLidded, neutral' },
  { cmd: '/avatar', desc: 'Inspect & toggle mesh layers or eyebrows: /avatar [layers|eyebrows]' },
  { cmd: '/debug', desc: 'Inspect prompt and raw response: /debug last' },
  { cmd: '/mic', desc: 'Microphone controls: /mic [play|test|devices|mode hold/toggle|source]' },
  { cmd: '/stt', desc: 'Speech recognition settings: /stt confirm [off|preview]' },
  { cmd: '/screen', desc: 'Toggle screen awareness tool: /screen [on|off]' },
  { cmd: '/idle', desc: 'Toggle proactive idle check-ins: /idle [on|off]' },
  { cmd: '/voice', desc: 'Voice controls: /voice [list | set <id> | provider local|edge | speed <x>]' },
  { cmd: '/lipsync', desc: 'Lip-sync controls: /lipsync calibrate <offset_ms>' },
  { cmd: '/crt', desc: 'Toggle retro CRT scanline effect on / off' },
  { cmd: '/memory', desc: 'View relationship memory & affinity milestones' },
  { cmd: '/clear', desc: 'Clear the terminal log screen (Ctrl+L)' },
  { cmd: '/stop', desc: 'Immediately cancel running agent tool execution' },
  { cmd: '/perm', desc: 'Set dangerous action policy: /perm [ask|allow|block]' },
  { cmd: '/perf', desc: 'Report performance, audio latency, and avatar display scaling telemetry' },
  { cmd: '/zoom', desc: 'Set or inspect focus view avatar zoom (0.8 - 1.6): /zoom [val]' },
  { cmd: '/offset', desc: 'Set or inspect focus view vertical offset: /offset [pixels]' },
  { cmd: '/boss', desc: 'Quick boss key / hide avatar pane' },
];

let activePaletteIndex = 0;

function updateSlashPalette(filter: string) {
  const matches = COMMANDS.filter(c => c.cmd.startsWith(filter.toLowerCase()));
  if (!matches.length) {
    slashPalette.classList.add('hidden');
    return;
  }

  slashPalette.innerHTML = '';
  activePaletteIndex = Math.min(activePaletteIndex, matches.length - 1);

  matches.forEach((item, idx) => {
    const el = document.createElement('div');
    el.className = `palette-item ${idx === activePaletteIndex ? 'active' : ''}`;

    const cmdSpan = document.createElement('span');
    cmdSpan.className = 'palette-cmd';
    cmdSpan.textContent = item.cmd;

    const descSpan = document.createElement('span');
    descSpan.className = 'palette-desc';
    descSpan.textContent = item.desc;

    el.appendChild(cmdSpan);
    el.appendChild(descSpan);

    el.addEventListener('mousedown', e => {
      e.preventDefault();
      promptInput.value = item.cmd + ' ';
      slashPalette.classList.add('hidden');
      promptInput.focus();
    });

    slashPalette.appendChild(el);
  });

  slashPalette.classList.remove('hidden');
}

function handleSlashCommand(raw: string) {
  const [cmd, ...args] = raw.trim().split(/\s+/);
  appendLog('system', '[cmd]', raw);

  switch (cmd.toLowerCase()) {
    case '/view': {
      const mode = args[0]?.toLowerCase() as ViewMode;
      if (['split', 'focus', 'chat'].includes(mode)) {
        setViewMode(mode);
        appendLog('system', '[view]', `View mode set to [${mode.toUpperCase()}].`);
      } else if (!args[0]) {
        cycleViewMode();
        appendLog('system', '[view]', `View mode cycled to [${currentViewMode.toUpperCase()}].`);
      } else {
        appendLog('system', '[view]', `Current view mode: [${currentViewMode.toUpperCase()}]. Usage: /view split | focus | chat`);
      }
      break;
    }
    case '/layout': {
      const mode = args[0]?.toLowerCase();
      if (['split', 'focus', 'chat'].includes(mode)) {
        setViewMode(mode as ViewMode);
        appendLog('system', '[view]', `View mode set to [${mode.toUpperCase()}].`);
      } else {
        cycleViewMode();
        appendLog('system', '[view]', `View mode cycled to [${currentViewMode.toUpperCase()}].`);
      }
      break;
    }
    case '/doctor': {
      appendLog('system', '[doctor]', 'Running system diagnostics...');
      fetch(`${ROXY_API}/api/doctor`)
        .then(async res => {
          const d = await res.json();
          appendLog('system', '[doctor]', `Diagnostic Results (${d.passed ? 'ALL PASSED' : 'ISSUES DETECTED'}):`);
          for (const item of (d.checks || [])) {
            const mark = item.ok ? '✓ PASS' : '✗ FAIL';
            appendLog('system', `[${item.name}]`, `${mark}: ${item.detail}${item.fix ? ' (Fix: ' + item.fix + ')' : ''}`);
          }
        })
        .catch(err => {
          appendLog('system', '[doctor]', `Doctor check failed: ${err.message}`);
        });
      break;
    }
    case '/music': {
      const sub = args[0]?.toLowerCase() || 'status';
      const val = args.slice(1).join(' ');
      if (sub === 'play') {
        appendLog('system', '[music]', `Resolving and streaming music query: "${val || 'lofi hip hop'}"...`);
        fetch(`${ROXY_API}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: `/music play ${val}` }),
        }).then(async r => {
          const d = await r.json();
          appendLog('roxy', 'roxy>', d.reply || 'Playing requested music.');
          syncMusicStatus();
        }).catch(err => appendLog('system', '[error]', `Music error: ${err.message}`));
      } else if (sub === 'stop' || sub === 'off') {
        fetch(`${ROXY_API}/api/music/stop`, { method: 'POST' })
          .then(() => {
            appendLog('system', '[music]', 'Music playback stopped.');
            syncMusicStatus();
          }).catch(err => appendLog('system', '[error]', err.message));
      } else if (sub === 'pause') {
        fetch(`${ROXY_API}/api/music/control`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'pause' }),
        }).then(() => {
          appendLog('system', '[music]', 'Music paused.');
          syncMusicStatus();
        }).catch(err => appendLog('system', '[error]', err.message));
      } else if (sub === 'resume') {
        fetch(`${ROXY_API}/api/music/control`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'resume' }),
        }).then(() => {
          appendLog('system', '[music]', 'Music resumed.');
          syncMusicStatus();
        }).catch(err => appendLog('system', '[error]', err.message));
      } else if (sub === 'next' || sub === 'prev') {
        fetch(`${ROXY_API}/api/music/control`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: sub }),
        }).then(() => syncMusicStatus()).catch(err => appendLog('system', '[error]', err.message));
      } else if (sub === 'vol' || sub === 'volume') {
        fetch(`${ROXY_API}/api/music/control`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'volume', value: val }),
        }).then(async r => {
          const d = await r.json();
          appendLog('system', '[music]', `Volume set to ${d.volume || val}%.`);
        }).catch(err => appendLog('system', '[error]', err.message));
      } else {
        fetch(`${ROXY_API}/api/music/status`)
          .then(async r => {
            const d = await r.json();
            const t = d.track;
            if (t) {
              appendLog('system', '[music]', `Currently playing: '${t.title}' by ${t.channel} (Volume: ${d.volume}%, Paused: ${d.paused})`);
            } else {
              appendLog('system', '[music]', 'No music is currently playing. Usage: /music play <query> | pause | resume | stop | next | prev | vol <0-100>');
            }
          }).catch(err => appendLog('system', '[error]', err.message));
      }
      break;
    }
    case '/tasks': {
      fetch(`${ROXY_API}/api/tasks`)
        .then(async r => {
          const d = await r.json();
          const tasks = d.tasks || [];
          if (!tasks.length) {
            appendLog('system', '[tasks]', 'No active background tasks.');
          } else {
            appendLog('system', '[tasks]', `Active background tasks (${tasks.length}):`);
            for (const t of tasks) {
              appendLog('system', `[${t.task_id}]`, `● ${t.name} (Type: ${t.type}, PID: ${t.pid}, Status: ${t.status})`);
            }
          }
        }).catch(err => appendLog('system', '[error]', err.message));
      break;
    }
    case '/settings':
    case '/setting': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'name') {
        const newName = args.slice(1).join(' ').trim();
        if (newName) {
          fetch(`${ROXY_API}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName }),
          })
            .then(async res => {
              const d = await res.json();
              currentPreferredName = d.preferred_name || newName;
              if (settingNameInput) settingNameInput.value = currentPreferredName;
              appendLog('system', '[settings]', `Preferred name updated to: [${currentPreferredName}]. Roxy will address you as ${currentPreferredName}.`);
            })
            .catch(err => appendLog('system', '[error]', `Failed to update name: ${err.message}`));
        } else {
          appendLog('system', '[settings]', `Current preferred name: [${currentPreferredName}]. Usage: /settings name <preferred_name>`);
        }
      } else if (sub === 'voice') {
        const targetVoice = args[1]?.trim();
        if (targetVoice) {
          fetch(`${ROXY_API}/api/voice/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ voice: targetVoice }),
          })
            .then(async res => {
              const d = await res.json();
              currentVoiceModel = d.voice;
              currentVoiceProvider = d.provider;
              updateVoiceBadge(d.status_label);
              if (settingVoiceSelect) settingVoiceSelect.value = d.voice;
              appendLog('system', '[settings]', `Voice model changed to: [${d.voice}] (${d.provider} engine). Applied immediately!`);
            })
            .catch(err => appendLog('system', '[error]', `Failed to change voice: ${err.message}`));
        } else {
          appendLog('system', '[settings]', `Current voice: [${currentVoiceModel}] (${currentVoiceProvider}). Usage: /settings voice <voice_id> (Type /voice list to see options)`);
        }
      } else if (sub === 'speed') {
        const val = parseFloat(args[1]);
        if (!isNaN(val)) {
          fetch(`${ROXY_API}/api/voice/speed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ speed: val }),
          })
            .then(async res => {
              const d = await res.json();
              if (settingSpeedSlider && settingSpeedVal) {
                settingSpeedSlider.value = String(d.speed);
                settingSpeedVal.textContent = d.speed.toFixed(2) + 'x';
              }
              appendLog('system', '[settings]', `Voice speed set to: [${d.speed.toFixed(2)}x] (${d.rate} native rate).`);
            })
            .catch(err => appendLog('system', '[error]', `Failed to set speed: ${err.message}`));
        } else {
          appendLog('system', '[settings]', `Usage: /settings speed <0.9 - 1.5>`);
        }
      } else {
        openSettingsModal();
        fetch(`${ROXY_API}/api/settings`)
          .then(async res => {
            const d = await res.json();
            currentPreferredName = d.preferred_name || currentPreferredName;
            currentVoiceModel = d.voice || currentVoiceModel;
            currentVoiceProvider = d.provider || currentVoiceProvider;
            appendLog('system', '[settings]', '── Roxy Companion Settings ────────────────────────');
            appendLog('system', '[settings]', `Preferred Name : [${d.preferred_name}] (change: /settings name <name>)`);
            appendLog('system', '[settings]', `Voice Model    : [${d.voice}] (${d.provider} engine) (change: /settings voice <id> or /voice set <id>)`);
            appendLog('system', '[settings]', `Voice Speed    : [${d.speed ? d.speed.toFixed(2) : '1.15'}x] (change: /settings speed <0.9-1.5>)`);
            appendLog('system', '[settings]', `Pitch Shift    : [${d.pitch >= 0 ? '+' : ''}${d.pitch}Hz] (change: /voice pitch <-50 to 50>)`);
            appendLog('system', '[settings]', `LLM Engine     : [${d.llm_model || 'qwen2.5:3b'}] (${d.llm_provider || 'ollama'})`);
            appendLog('system', '[settings]', `Devotion Tier  : [${d.yandere_intensity}/10] (change: /yandere <0-10>)`);
            appendLog('system', '[settings]', 'Interactive settings dialog opened (or click ⚙️ Settings).');
          })
          .catch(err => appendLog('system', '[error]', `Failed to retrieve settings: ${err.message}`));
      }
      break;
    }
    case '/help':
    case '/?': {
      appendLog('system', '[help]', '── Available Commands ──────────────────────────────');
      appendLog('system', '[help]', '⚙️ Settings Modal  : Click the "⚙️ Settings" button or type /settings');
      appendLog('system', '[help]', '💬 Preferred Name  : /settings name <name> or /name <name> (e.g. /name Sir)');
      appendLog('system', '[help]', '🔊 Voice Selection : /voice list | /voice set <id> (e.g. /voice set af_whisper)');
      appendLog('system', '[help]', '⚡ Speech Speed    : /settings speed <0.9-1.5> (e.g. /settings speed 1.15)');
      appendLog('system', '[help]', '💖 Devotion Tier   : /yandere <0-10> (e.g. /yandere 4)');
      appendLog('system', '[help]', '🎵 Music Player    : /music play <query> | /music pause | /music stop');
      appendLog('system', '[help]', '👁️ View Mode       : /view split | focus | chat');
      appendLog('system', '[help]', '🧹 Clear Terminal  : /clear');
      break;
    }
    case '/name': {
      const chosenName = args.join(' ').trim();
      if (chosenName) {
        fetch(`${ROXY_API}/api/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: chosenName }),
        })
          .then(async res => {
            const d = await res.json();
            currentPreferredName = d.preferred_name || chosenName;
            appendLog('system', '[name]', `Preferred name updated to: [${currentPreferredName}]. Roxy will address you as ${currentPreferredName}.`);
          })
          .catch(err => appendLog('system', '[error]', `Failed to set name: ${err.message}`));
      } else {
        appendLog('system', '[name]', `Current preferred name: [${currentPreferredName}]. Usage: /name <preferred_name>`);
      }
      break;
    }
    case '/theme': {
      const th = args[0]?.toLowerCase();
      if (['foot-dark', 'catppuccin', 'gruvbox', 'light'].includes(th)) {
        setTheme(th);
        appendLog('system', '[info]', `Theme changed to ${th}.`);
      } else {
        appendLog('system', '[info]', `Available themes: foot-dark, catppuccin, gruvbox, light. Current: ${currentTheme}`);
      }
      break;
    }
    case '/status': {
      fetch(`${ROXY_API}/api/status`).then(async r => {
        const d = await r.json();
        appendLog('system', '[status]', `── ${d.character} (${d.title}) ─────────────`);
        appendLog('system', '[status]', `Mood: [${String(d.emotion || 'neutral').toUpperCase()}] | Affection: [${d.affection}%]`);
        appendLog('system', '[status]', `Devotion: [${d.yandere_intensity}/10] (${d.yandere_tier})`);
        appendLog('system', '[status]', `Voice Engine: ${d.voice_status_label || '[Voice: ' + d.voice_provider + ']'} | Preset: [${d.voice_preset}] (${d.voice_model}, speed ${d.voice_speed}x, lip-sync offset ${d.lipsync_offset_ms}ms)`);
        appendLog('system', '[status]', `LLM Engine: ${d.llm_provider} (${d.llm_model})`);
        appendLog('system', '[status]', `Dangerous Action Policy: [${String(d.dangerous_policy).toUpperCase()}]`);
        appendLog('system', '[status]', `Layout: ${currentLayout} | Theme: ${currentTheme} | CRT: ${crtEnabled ? 'ON' : 'OFF'}`);
      }).catch(() => {
        appendLog('system', '[status]', `Character: Roxy Migurdia | Affection: ${affection.toFixed(1)}% | Devotion: ${yandereIntensity}/10`);
      });
      break;
    }
    case '/yandere': {
      const valStr = args[0];
      if (valStr !== undefined && !isNaN(parseInt(valStr, 10))) {
        const val = parseInt(valStr, 10);
        setYandereIntensity(val);
        fetch(`${ROXY_API}/api/yandere`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ intensity: val }),
        }).then(async r => {
          const d = await r.json();
          appendLog('system', '[yandere]', d.message || `Devotion set to ${val}/10.`);
        }).catch(err => appendLog('system', '[error]', `Failed to set devotion: ${err.message}`));
      } else {
        fetch(`${ROXY_API}/api/yandere`).then(async r => {
          const d = await r.json();
          appendLog('system', '[yandere]', `Current Devotion: [${d.intensity}/10] - ${d.tier}`);
          appendLog('system', '[yandere]', `Tiers: 0=Relax/Mentor, 1-3=Gentle, 4-6=Possessive Partner (Default), 7-10=Obsessive Doting`);
          appendLog('system', '[yandere]', `Usage: /yandere <0-10> | /relax`);
        }).catch(() => appendLog('system', '[yandere]', `Current devotion: ${yandereIntensity}/10. Usage: /yandere <0-10>`));
      }
      break;
    }
    case '/relax': {
      setYandereIntensity(0);
      fetch(`${ROXY_API}/api/relax`, { method: 'POST' }).then(async r => {
        const d = await r.json();
        appendLog('system', '[relax]', d.message || 'Safe word triggered: Intensity dropped to 0/10 (Professional Mentor).');
      }).catch(() => appendLog('system', '[relax]', 'Safe word triggered: Intensity set to 0/10.'));
      break;
    }
    case '/avatar': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'eyebrows' || sub === 'eyebrow' || sub === 'brows') {
        const mode = args[1]?.toLowerCase();
        if (mode === 'off' || mode === 'subtle') {
          applyEyebrows(mode);
          appendLog('system', '[avatar]', `Eyebrows config set to [${mode.toUpperCase()}].`);
        } else {
          appendLog('system', '[avatar]', `Current eyebrows: [${currentEyebrows.toUpperCase()}]. Usage: /avatar eyebrows [off|subtle]`);
        }
      } else if (sub === 'layers' || sub === 'layer') {
        const targetLayer = args[1]?.toLowerCase();
        const state = args[2]?.toLowerCase();
        if (!avatar || !avatar.getLayers) {
          appendLog('system', '[info]', 'Avatar model not yet loaded.');
          break;
        }
        const layers = avatar.getLayers();
        if (targetLayer) {
          const match = layers.find(l => l.name.toLowerCase() === targetLayer);
          if (!match) {
            appendLog('system', '[error]', `Layer "${targetLayer}" not found. Available: ${layers.map(l => l.name).join(', ')}`);
          } else {
            const newVis = state === 'on' ? true : state === 'off' ? false : !match.visible;
            if (avatar.setLayerVisible) avatar.setLayerVisible(match.name, newVis);
            appendLog('system', '[info]', `Layer ${match.name} set to [${newVis ? 'ON' : 'OFF'}].`);
          }
        } else {
          appendLog('system', '[layers]', '── Avatar Mesh Layers ─────────────────────────');
          layers.forEach(l => {
            appendLog('system', '[layer]', `  ${l.visible ? '● [ON ]' : '○ [OFF]'} ${l.name}`);
          });
          appendLog('system', '[info]', 'Usage: /avatar layers <name> [on|off]');
        }
      } else {
        appendLog('system', '[info]', 'Usage: /avatar [layers|eyebrows] [args]');
      }
      break;
    }
    case '/debug': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'last') {
        fetch(`${ROXY_API}/api/debug/last`).then(async res => {
          const data = await res.json();
          appendLog('system', '[debug]', '── EXACT PROMPT SENT ────────────────────────');
          appendLog('system', '', data.prompt);
          appendLog('system', '[debug]', '── RAW RESPONSE ─────────────────────────────');
          appendLog('system', '', data.raw_response || '(None)');
          if (data.error) {
            appendLog('system', '[debug-error]', `Last Error: ${data.error}`);
          }
        }).catch(e => {
          appendLog('system', '[error]', `Failed to fetch debug info: ${e.message}`);
        });
      } else {
        appendLog('system', '[info]', 'Usage: /debug last');
      }
      break;
    }
    case '/mic': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'play') {
        appendLog('system', '[mic]', 'Playing back last recorded microphone capture...');
        const audio = new Audio(`${ROXY_API}/api/mic/last_recording?t=${Date.now()}`);
        audio.play().catch(() => {});
        fetch(`${ROXY_API}/api/mic/play`, { method: 'POST' }).then(async r => {
          const d = await r.json();
          if (d.status === 'playing') {
            appendLog('system', '[mic]', `Playing via host audio: ${d.player} (${d.size_bytes} bytes).`);
          } else if (d.error) {
            appendLog('system', '[mic]', `Host playback info: ${d.error}`);
          }
        }).catch(err => {
          appendLog('system', '[mic]', `Host play: ${err.message}`);
        });
      } else if (sub === 'devices') {
        fetch(`${ROXY_API}/api/mic/devices`).then(async res => {
          const data = await res.json();
          appendLog('system', '[mic]', '── Audio Input Devices ─────────────────────');
          data.devices.forEach((d: any) => {
            const def = d.is_default ? ' [DEFAULT]' : '';
            appendLog('system', '[device]', `  ${d.id}: ${d.name}${def}`);
          });
          appendLog('system', '[info]', `Active source: ${micSource} (toggle with /mic source [browser|backend])`);
        }).catch(e => {
          appendLog('system', '[error]', `Failed to query mic devices: ${e.message}`);
        });
      } else if (sub === 'test') {
        appendLog('system', '[mic]', 'Sampling microphone level for 1.5s...');
        fetch(`${ROXY_API}/api/mic/test`, { method: 'POST' }).then(async res => {
          const data = await res.json();
          appendLog('system', '[mic]', `Peak audio level: ${data.peak} (${data.audible ? 'Audio Detected ✓' : 'Silent / Low Level'}) [Device: ${data.device || 'Default'}]`);
        }).catch(e => {
          appendLog('system', '[error]', `Mic test failed: ${e.message}`);
        });
      } else if (sub === 'mode') {
        const m = args[1]?.toLowerCase();
        if (m === 'hold' || m === 'toggle') {
          pttMode = m;
          localStorage.setItem('roxy-mic-mode', m);
          appendLog('system', '[mic]', `PTT mode set to: [${m.toUpperCase()}]. (${m === 'hold' ? 'Hold F2/Space, release to send' : 'Tap F2/Space to start, tap again to send'})`);
        } else {
          appendLog('system', '[mic]', `Current PTT mode: [${pttMode.toUpperCase()}]. Usage: /mic mode hold|toggle`);
        }
      } else if (sub === 'source') {
        const src = args[1]?.toLowerCase();
        if (src === 'browser' || src === 'backend') {
          setMicSource(src);
          appendLog('system', '[info]', `Microphone source set to: ${src}.`);
        } else {
          appendLog('system', '[info]', `Current mic source: ${micSource}. Usage: /mic source [browser|backend]`);
        }
      } else if (sub === 'on') {
        if (!isListening) void startVoiceInput();
        appendLog('system', '[mic]', 'Microphone listening started.');
      } else if (sub === 'off') {
        if (isListening) void stopVoiceInput(true);
        appendLog('system', '[mic]', 'Microphone listening stopped.');
      } else {
        appendLog('system', '[info]', 'Usage: /mic [play | test | devices | mode hold|toggle | source browser|backend | on | off]');
      }
      break;
    }
    case '/stt': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'confirm') {
        const m = args[1]?.toLowerCase();
        if (m === 'off' || m === 'preview') {
          sttConfirm = m;
          localStorage.setItem('roxy-stt-confirm', m);
          appendLog('system', '[stt]', `STT confirmation set to: [${m.toUpperCase()}]. (${m === 'preview' ? '1.5s countdown preview before sending' : 'Immediate send'})`);
        } else {
          appendLog('system', '[stt]', `Current STT confirm mode: [${sttConfirm.toUpperCase()}]. Usage: /stt confirm off|preview`);
        }
      } else {
        appendLog('system', '[stt]', 'Usage: /stt confirm [off | preview]');
      }
      break;
    }
    case '/screen': {
      const state = args[0]?.toLowerCase();
      if (state === 'on') {
        setScreenAwareness(true);
        appendLog('system', '[info]', 'Screen awareness enabled. Ask "what do I see on my screen" to inspect display.');
      } else if (state === 'off') {
        setScreenAwareness(false);
        appendLog('system', '[info]', 'Screen awareness disabled.');
      } else {
        setScreenAwareness(!screenAwarenessEnabled);
        appendLog('system', '[info]', `Screen awareness toggled ${screenAwarenessEnabled ? 'ON' : 'OFF'}.`);
      }
      break;
    }
    case '/emotion': {
      const em = args[0]?.toLowerCase() as LiveExpression;
      if (['smile', 'shy', 'surprise', 'halfLidded', 'neutral', 'angry', 'sad', 'wink', 'pout', 'smug', 'dizzy'].includes(em)) {
        if (avatar) avatar.setExpression(em);
        moodVal.textContent = em;
        appendLog('system', '[info]', `Roxy's expression set to ${em}.`);
      } else {
        appendLog('system', '[info]', `Usage: /emotion [smile|shy|surprise|halfLidded|neutral|wink|pout|smug|dizzy]`);
      }
      break;
    }
    case '/mind':
    case '/thoughts': {
      fetch('http://127.0.0.1:5174/api/mind')
        .then(res => res.json())
        .then(d => {
          appendLog('roxy', 'subconscious>', `[Inner State]: ${d.blend}\n[Thoughts]: "${d.inner_monologue}"\n[Pose]: ${d.recommended_pose} | [Expr]: ${d.recommended_expression}`);
          if (avatar && d.recommended_expression) {
            avatar.setExpression(d.recommended_expression as LiveExpression);
            moodVal.textContent = d.recommended_expression;
          }
        })
        .catch(() => {
          appendLog('system', '[error]', 'Could not reach local emotional cognition service.');
        });
      break;
    }
    case '/idle': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'on') {
        idleCheckinEnabled = true;
        localStorage.setItem('roxy-idle-checkin', 'true');
        appendLog('system', '[idle]', 'Proactive idle companion check-ins turned ON.');
      } else if (sub === 'off') {
        idleCheckinEnabled = false;
        localStorage.setItem('roxy-idle-checkin', 'false');
        appendLog('system', '[idle]', 'Proactive idle companion check-ins turned OFF.');
      } else {
        appendLog('system', '[idle]', `Proactive idle check-ins: [${idleCheckinEnabled ? 'ON' : 'OFF'}]. Usage: /idle [on|off]`);
      }
      break;
    }
    case '/voice': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'list') {
        fetch(`${ROXY_API}/api/voice/list`)
          .then(async res => {
            const d = await res.json();
            appendLog('system', '[voice]', '── Available Voices ──────────────────────────────');
            appendLog('system', '[voice]', 'Local Neural Kokoro (consented open-source, offline, ultra-fast):');
            (d.voices || [])
              .filter((v: any) => v.provider === 'local')
              .forEach((v: any) => {
                const isCur = v.id === currentVoiceModel ? ' ● [ACTIVE] ' : ' ○ ';
                appendLog('system', '[voice]', `  ${isCur}${v.id} - ${v.name} (${v.description})`);
              });
            appendLog('system', '[voice]', 'Cloud Edge Neural (online):');
            (d.voices || [])
              .filter((v: any) => v.provider === 'edge')
              .forEach((v: any) => {
                const isCur = v.id === currentVoiceModel ? ' ● [ACTIVE] ' : ' ○ ';
                appendLog('system', '[voice]', `  ${isCur}${v.id} - ${v.name} (${v.description})`);
              });
            appendLog('system', '[voice]', 'Usage: /voice set <voice_id> or /settings voice <voice_id>');
          })
          .catch(err => appendLog('system', '[error]', `Failed to list voices: ${err.message}`));
      } else if (sub === 'set') {
        const targetVoice = args[1]?.trim();
        if (targetVoice) {
          fetch(`${ROXY_API}/api/voice/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ voice: targetVoice }),
          })
            .then(async res => {
              const d = await res.json();
              currentVoiceModel = d.voice;
              currentVoiceProvider = d.provider;
              updateVoiceBadge(d.status_label);
              appendLog('system', '[voice]', `Voice set to: [${d.voice}] (${d.provider} engine). Applied instantly!`);
            })
            .catch(err => appendLog('system', '[error]', `Failed to set voice: ${err.message}`));
        } else {
          appendLog('system', '[voice]', `Current voice: [${currentVoiceModel}]. Usage: /voice set <voice_id>. Type /voice list for options.`);
        }
      } else if (sub === 'sync') {
        const val = args[1]?.toLowerCase();
        if (val === 'on' || val === 'off') {
          syncTextToVoice = (val === 'on');
          localStorage.setItem('roxy-sync-text', syncTextToVoice ? 'true' : 'false');
          appendLog('system', '[voice]', `Text-to-voice sync locked to: [${val.toUpperCase()}].`);
        } else {
          appendLog('system', '[voice]', `Current sync state: [${syncTextToVoice ? 'ON' : 'OFF'}]. Usage: /voice sync on|off`);
        }
      } else if (sub === 'mute') {
        setVoiceMute(true);
        appendLog('system', '[voice]', 'Voice speech muted (text logs continue).');
      } else if (sub === 'unmute') {
        setVoiceMute(false);
        appendLog('system', '[voice]', 'Voice speech unmuted.');
      } else if (sub === 'off') {
        setVoiceMute(true);
        if (isListening) void stopVoiceInput();
        appendLog('system', '[voice]', 'Voice speech and microphone listening turned OFF.');
      } else if (sub === 'on') {
        setVoiceMute(false);
        appendLog('system', '[voice]', 'Voice speech turned ON.');
      } else if (sub === 'speed') {
        const val = parseFloat(args[1]);
        if (!isNaN(val)) {
          fetch(`${ROXY_API}/api/voice/speed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ speed: val }),
          }).then(async res => {
            const d = await res.json();
            appendLog('system', '[voice]', `Voice speed set to: [${d.speed.toFixed(2)}x] (${d.rate} native rate). Applied instantly.`);
          }).catch(err => appendLog('system', '[error]', `Failed to update voice speed: ${err.message}`));
        } else {
          fetch(`${ROXY_API}/api/voice/speed`).then(async res => {
            const d = await res.json();
            appendLog('system', '[voice]', `Current speed: [${d.speed.toFixed(2)}x] (${d.rate}). Usage: /voice speed <0.9 - 1.5>`);
          }).catch(err => appendLog('system', '[error]', `Failed to query voice speed: ${err.message}`));
        }
      } else if (sub === 'save') {
        const preset = args[1] || 'mature_mommy_fast';
        fetch(`${ROXY_API}/api/voice/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preset }),
        }).then(async res => {
          const d = await res.json();
          appendLog('system', '[voice]', `Voice settings saved to preset: [${d.preset}].`);
        }).catch(err => appendLog('system', '[error]', `Failed to save voice preset: ${err.message}`));
      } else if (sub === 'provider') {
        const prov = args[1]?.toLowerCase();
        if (prov === 'edge' || prov === 'cloud' || prov === 'local') {
          fetch(`${ROXY_API}/api/voice/provider`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: prov }),
          }).then(async res => {
            const d = await res.json();
            currentVoiceProvider = d.provider;
            updateVoiceBadge(d.status_label);
            appendLog('system', '[voice]', `Voice provider set to: [${d.provider}] (${d.status_label}).`);
          }).catch(err => appendLog('system', '[error]', `Failed to set provider: ${err.message}`));
        } else {
          fetch(`${ROXY_API}/api/voice/provider`).then(async res => {
            const d = await res.json();
            appendLog('system', '[voice]', `Active provider: [${d.provider}] (${d.status_label}). Usage: /voice provider local|edge`);
          }).catch(err => appendLog('system', '[error]', `Failed to query provider: ${err.message}`));
        }
      } else if (sub === 'audition') {
        appendLog('system', '[voice]', '── Voice Pace & Rhythm Audition Report ─────────');
        fetch(`${ROXY_API}/api/voice/audition`).then(async res => {
          const d = await res.json();
          appendLog('system', '[voice]', `Active Preset: [${d.current_preset.toUpperCase()}] (${d.voice})`);
          appendLog('system', '[voice]', `Current Pace: [${d.speed ? d.speed.toFixed(2) : '1.20'}x] (${d.base_rate}% native rate, pitch ${d.base_pitch}Hz)`);
          appendLog('system', '[voice]', 'Speeds Evaluated: 1.00x (+0%), 1.15x (+15%), 1.25x (+25% ⭐ Recommended), 1.35x (+35%)');
          appendLog('system', '[voice]', 'Full report: voice_audition/audition_report.md');
        }).catch(err => appendLog('system', '[error]', `Failed to query audition: ${err.message}`));
      } else {
        appendLog('system', '[voice]', `Voice: [${voiceMuted ? 'MUTED' : 'ON'}] | Provider: [${currentVoiceProvider}] | Sync: [${syncTextToVoice ? 'ON' : 'OFF'}]. Options: /voice provider <local|edge> | speed <x> | save <preset> | audition | mute | unmute | sync on|off`);
      }
      break;
    }
    case '/lipsync': {
      const sub = args[0]?.toLowerCase();
      if (sub === 'calibrate') {
        const val = parseFloat(args[1]);
        if (!isNaN(val)) {
          lipsyncOffsetMs = val;
          localStorage.setItem('roxy_lipsync_offset_ms', String(val));
          fetch(`${ROXY_API}/api/voice/lipsync`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ offset_ms: val }),
          }).then(async res => {
            const d = await res.json();
            appendLog('system', '[lipsync]', `Lip-sync offset calibrated to: [${d.offset_ms.toFixed(1)} ms].`);
          }).catch(err => appendLog('system', '[error]', `Failed to calibrate lip-sync: ${err.message}`));
        } else {
          fetch(`${ROXY_API}/api/voice/lipsync`).then(async res => {
            const d = await res.json();
            appendLog('system', '[lipsync]', `Current lip-sync offset: [${d.offset_ms.toFixed(1)} ms]. Usage: /lipsync calibrate <-100 to 100>`);
          }).catch(() => {
            appendLog('system', '[lipsync]', `Current lip-sync offset: [${lipsyncOffsetMs.toFixed(1)} ms]. Usage: /lipsync calibrate <-100 to 100>`);
          });
        }
      } else {
        appendLog('system', '[lipsync]', `Lip-sync offset: [${lipsyncOffsetMs.toFixed(1)} ms]. Usage: /lipsync calibrate <offset_ms>`);
      }
      break;
    }
    case '/crt': {
      setCRT(!crtEnabled);
      appendLog('system', '[info]', `CRT scanlines ${crtEnabled ? 'enabled' : 'disabled'}.`);
      break;
    }
    case '/memory': {
      appendLog('system', '[memory]', `Memory Store: 42 dialogues logged.`);
      appendLog('system', '[memory]', `Favorite spells: Water Ball, Cumulonimbus, Icicle Lance.`);
      appendLog('system', '[memory]', `Affection stage: "Devoted Master & Companion" (${affection.toFixed(1)}%)`);
      break;
    }
    case '/clear': {
      logScroll.innerHTML = '';
      appendLog('system', '', 'Terminal log cleared.');
      break;
    }
    case '/perf': {
      fetch(`${ROXY_API}/api/perf`).then(async res => {
        const d = await res.json();
        const lines = (d.report || '').replace(/\[\/?bold[^\]]*\]/g, '').replace(/\[\/?cyan[^\]]*\]/g, '').replace(/\[\/?green[^\]]*\]/g, '').replace(/\[\/?dim[^\]]*\]/g, '').split('\n');
        for (const line of lines) {
          if (line.trim()) appendLog('system', '[perf]', line);
        }
      }).catch(err => appendLog('system', '[error]', `Failed to fetch perf: ${err.message}`));

      if (avatar && avatar.getFraming) {
        const f = avatar.getFraming();
        appendLog('system', '[perf]', '--- Avatar Display & Framing Telemetry ---');
        appendLog('system', '[perf]', `Native Art Size: ${f.nativeWidth}x${f.nativeHeight} px`);
        appendLog('system', '[perf]', `Displayed Size: ${f.displayedWidth}x${f.displayedHeight} px (CSS: ${Math.round(f.displayedWidth / f.dpr)}x${Math.round(f.displayedHeight / f.dpr)} px, DPR: ${f.dpr})`);
        appendLog('system', '[perf]', `Scale Factor: ${f.pxScale.toFixed(3)}x (Fit: ${f.fit}, Zoom: ${f.zoom.toFixed(2)}, Offset Y: ${f.offsetY}px)`);
        appendLog('system', '[perf]', `Resampling Quality: WebGL Mipmaps (LINEAR_MIPMAP_LINEAR) + Anisotropic Filtering (DPR aware: ${f.dpr})`);
        if (f.pxScale > 1.5) {
          appendLog('system', '[perf]', `⚠️ Warning: Layer scale factor ${f.pxScale.toFixed(3)}x exceeds 1.5x native resolution!`);
        }
      }
      break;
    }
    case '/zoom': {
      const val = parseFloat(args[0]);
      if (!isNaN(val)) {
        focusZoom = Math.min(1.6, Math.max(0.8, Math.round(val * 100) / 100));
        saveFocusFraming();
        appendLog('system', '[zoom]', `Focus zoom set to ${focusZoom.toFixed(2)}x (range: 0.8 - 1.6)`);
      } else {
        appendLog('system', '[zoom]', `Current focus zoom: ${focusZoom.toFixed(2)}x. Usage: /zoom <0.8 - 1.6> or use [ ] keys`);
      }
      break;
    }
    case '/offset': {
      const val = parseFloat(args[0]);
      if (!isNaN(val)) {
        focusOffsetY = Math.round(val * 10) / 10;
        saveFocusFraming();
        appendLog('system', '[offset]', `Focus offset_y set to ${focusOffsetY}px`);
      } else {
        appendLog('system', '[offset]', `Current focus offset_y: ${focusOffsetY}px. Usage: /offset <pixels> or Shift+wheel`);
      }
      break;
    }
    case '/stop': {
      fetch(`${ROXY_API}/api/stop`, { method: 'POST' }).catch(() => {});
      appendLog('system', '[stop]', 'Stopped active agent task.');
      taskVal.textContent = 'Cancelled';
      break;
    }
    case '/perm': {
      const mode = args[0]?.toLowerCase();
      if (mode === 'ask' || mode === 'allow' || mode === 'block') {
        fetch(`${ROXY_API}/api/perm`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ policy: mode }),
        }).then(async r => {
          const d = await r.json();
          appendLog('system', '[perm]', d.message || `Policy set to [${mode.toUpperCase()}].`);
        }).catch(err => appendLog('system', '[error]', `Failed to set policy: ${err.message}`));
      } else {
        fetch(`${ROXY_API}/api/perm`).then(async r => {
          const d = await r.json();
          appendLog('system', '[perm]', `Current dangerous actions policy: [${String(d.policy || 'ask').toUpperCase()}]. Options: /perm ask | allow | block`);
        }).catch(() => appendLog('system', '[perm]', 'Usage: /perm <ask | allow | block>'));
      }
      break;
    }
    case '/boss': {
      const isHidden = appEl.classList.toggle('mode-mini');
      appendLog('system', '[boss]', `Avatar toggled ${isHidden ? 'mini' : 'standard'}.`);
      break;
    }
    default:
      appendLog('system', '[error]', `Unknown command: ${cmd}. Type / to view available commands.`);
  }
}

// ---------------------------------------------------------------------------
// 8. Terminal Keyboard Input & History Navigation
// ---------------------------------------------------------------------------
const history: string[] = [];
let historyIndex = -1;

promptInput.addEventListener('input', () => {
  const val = promptInput.value;
  if (val.startsWith('/')) {
    updateSlashPalette(val);
  } else {
    slashPalette.classList.add('hidden');
  }
});

promptInput.addEventListener('keydown', e => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const visibleItems = slashPalette.querySelectorAll('.palette-item');
    if (!slashPalette.classList.contains('hidden') && visibleItems.length) {
      const active = visibleItems[activePaletteIndex] || visibleItems[0];
      const cmd = active.querySelector('.palette-cmd')?.textContent;
      if (cmd) {
        promptInput.value = cmd + ' ';
        slashPalette.classList.add('hidden');
      }
    }
    return;
  }

  if (e.key === 'ArrowUp') {
    if (!slashPalette.classList.contains('hidden')) {
      e.preventDefault();
      activePaletteIndex = Math.max(0, activePaletteIndex - 1);
      updateSlashPalette(promptInput.value);
      return;
    }
    if (history.length && historyIndex < history.length - 1) {
      e.preventDefault();
      historyIndex++;
      promptInput.value = history[history.length - 1 - historyIndex];
    }
    return;
  }

  if (e.key === 'ArrowDown') {
    if (!slashPalette.classList.contains('hidden')) {
      e.preventDefault();
      activePaletteIndex++;
      updateSlashPalette(promptInput.value);
      return;
    }
    if (historyIndex > 0) {
      e.preventDefault();
      historyIndex--;
      promptInput.value = history[history.length - 1 - historyIndex];
    } else if (historyIndex === 0) {
      e.preventDefault();
      historyIndex = -1;
      promptInput.value = '';
    }
    return;
  }

  if (e.key === 'Enter') {
    e.preventDefault();
    if (previewTimeoutId) {
      clearTimeout(previewTimeoutId);
      previewTimeoutId = null;
    }
    slashPalette.classList.add('hidden');
    const val = promptInput.value;
    if (val.trim()) {
      history.push(val);
      historyIndex = -1;
      promptInput.value = '';
      void processPrompt(val);
    }
    return;
  }

  if (e.key === 'Escape') {
    if (previewTimeoutId) {
      clearTimeout(previewTimeoutId);
      previewTimeoutId = null;
      appendLog('system', '[stt-preview]', 'Transcription auto-send cancelled. Edit text and press Enter.');
      return;
    }
    slashPalette.classList.add('hidden');
    promptInput.value = '';
    return;
  }

  // Ctrl+L to clear screen
  if (e.ctrlKey && (e.key === 'l' || e.key === 'L')) {
    e.preventDefault();
    logScroll.innerHTML = '';
    appendLog('system', '', 'Terminal log cleared.');
    return;
  }

  // F3: Toggle Voice Mute
  if (e.key === 'F3') {
    e.preventDefault();
    setVoiceMute(!voiceMuted);
    appendLog('system', '[voice]', `Voice speech ${voiceMuted ? 'muted' : 'unmuted'}. (F3)`);
    return;
  }

  // F2 (hold to record in hold mode, or tap to toggle in toggle mode)
  if (e.key === 'F2') {
    e.preventDefault();
    bargeIn();
    if (!e.repeat) {
      if (pttMode === 'toggle') {
        if (isListening) void stopVoiceInput();
        else void startVoiceInput();
      } else {
        if (!isListening) void startVoiceInput();
      }
    }
    return;
  }

  // Space for Push-to-Talk ONLY when promptInput is completely empty
  if (e.key === ' ' && promptInput.value === '') {
    e.preventDefault();
    bargeIn();
    if (!e.repeat) {
      if (pttMode === 'toggle') {
        if (isListening) void stopVoiceInput();
        else void startVoiceInput();
      } else {
        if (!isListening) void startVoiceInput();
      }
    }
    return;
  }
});

// Release F2 or Space to stop recording and send (in hold mode only)
promptInput.addEventListener('keyup', e => {
  if (pttMode === 'hold' && (e.key === 'F2' || e.key === ' ') && isListening) {
    e.preventDefault();
    void stopVoiceInput();
  }
});

window.addEventListener('keyup', e => {
  if (pttMode === 'hold' && (e.key === 'F2' || e.key === ' ') && isListening) {
    void stopVoiceInput();
  }
});

// Clickable Mic Button in Status Bar
if (micBtn) {
  micBtn.addEventListener('click', e => {
    e.preventDefault();
    if (isListening) {
      void stopVoiceInput();
    } else {
      void startVoiceInput();
    }
  });
}

// "Grant Microphone" button for Brave / Chromium in App mode
if (grantMicBtn) {
  grantMicBtn.addEventListener('click', async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
      grantMicBtn.classList.add('hidden');
      appendLog('system', '[mic]', 'Browser microphone permission successfully granted!');
      setMicSource('browser');
    } catch (err: any) {
      appendLog('system', '[mic-error]', `Microphone permission request failed: ${err.name}`);
      appendLog('system', '[brave-help]', 'For Brave Browser / App Mode (--app):');
      appendLog('system', '[brave-help]', '1. Click the site settings icon (padlock/tune) in Brave address bar for 127.0.0.1.');
      appendLog('system', '[brave-help]', '2. Under "Permissions", set "Microphone" to "Allow" (or open brave://settings/content/microphone).');
      appendLog('system', '[brave-help]', '3. Ensure Brave Shields is disabled for 127.0.0.1 if blocking scripts or devices.');
      appendLog('system', '[brave-help]', '4. Note: Backend capture works immediately without browser permissions: /mic source backend');
    }
  });
}

// Global window key handlers for F4, Ctrl+H, Esc, and permission modal shortcuts
window.addEventListener('keydown', e => {
  if (e.key === 'F4') {
    e.preventDefault();
    cycleViewMode();
    return;
  }

  if ((e.ctrlKey || e.metaKey) && (e.key === 'h' || e.key === 'H')) {
    e.preventDefault();
    toggleChatDrawer();
    return;
  }

  if (e.key === 'Escape') {
    if (settingsOverlay && !settingsOverlay.classList.contains('hidden')) {
      e.preventDefault();
      closeSettingsModal();
      return;
    }
    if (confirmOverlay && !confirmOverlay.classList.contains('hidden')) {
      e.preventDefault();
      resolveConfirmation(false);
      return;
    }
    if (chatDrawer && !chatDrawer.classList.contains('closed')) {
      e.preventDefault();
      closeChatDrawer();
      return;
    }
  }

  // Focus framing keyboard shortcuts ([ and ] for zoom, { and } for offset_y)
  if (currentViewMode === 'focus' && (document.activeElement !== promptInput || promptInput.value === '')) {
    if (e.key === '[') {
      e.preventDefault();
      focusZoom = Math.max(0.8, Math.round((focusZoom - 0.05) * 100) / 100);
      saveFocusFraming();
      showToast(`Zoom: ${focusZoom.toFixed(2)}x (0.8 - 1.6)`, 'info');
      return;
    }
    if (e.key === ']') {
      e.preventDefault();
      focusZoom = Math.min(1.6, Math.round((focusZoom + 0.05) * 100) / 100);
      saveFocusFraming();
      showToast(`Zoom: ${focusZoom.toFixed(2)}x (0.8 - 1.6)`, 'info');
      return;
    }
    if (e.key === '{') {
      e.preventDefault();
      focusOffsetY = Math.round((focusOffsetY - 10) * 10) / 10;
      saveFocusFraming();
      showToast(`Offset Y: ${focusOffsetY}px`, 'info');
      return;
    }
    if (e.key === '}') {
      e.preventDefault();
      focusOffsetY = Math.round((focusOffsetY + 10) * 10) / 10;
      saveFocusFraming();
      showToast(`Offset Y: ${focusOffsetY}px`, 'info');
      return;
    }
  }

  // Quick keyboard shortcuts when permission modal is shown (unless dangerous typed confirmation is required)
  if (confirmOverlay && !confirmOverlay.classList.contains('hidden') && !isDangerousAction) {
    if (e.key === 'y' || e.key === 'Y') {
      if (document.activeElement !== promptInput) {
        e.preventDefault();
        resolveConfirmation(true);
        return;
      }
    } else if (e.key === 'n' || e.key === 'N') {
      if (document.activeElement !== promptInput) {
        e.preventDefault();
        resolveConfirmation(false);
        return;
      }
    }
  }
});

// Always keep prompt focused unless clicking interactive buttons, modal, or selection
document.addEventListener('click', e => {
  const target = e.target as HTMLElement;
  if (!window.getSelection()?.toString() && !target.closest('.tool-header, .status-btn, .confirm-modal, .chat-drawer, .focus-btn, .np-btn, input, pre, button')) {
    promptInput.focus();
  }
});

// Focus framing mouse wheel handler (wheel: zoom, shift+wheel: offset_y)
function handleAvatarWheel(e: WheelEvent) {
  if (currentViewMode !== 'focus') return;
  e.preventDefault();
  if (e.shiftKey) {
    const deltaY = e.deltaY > 0 ? 10 : -10;
    focusOffsetY = Math.round((focusOffsetY + deltaY) * 10) / 10;
    saveFocusFraming();
    showToast(`Offset Y: ${focusOffsetY}px`, 'info');
  } else {
    const deltaZ = e.deltaY < 0 ? 0.05 : -0.05;
    focusZoom = Math.min(1.6, Math.max(0.8, Math.round((focusZoom + deltaZ) * 100) / 100));
    saveFocusFraming();
    showToast(`Zoom: ${focusZoom.toFixed(2)}x (0.8 - 1.6)`, 'info');
  }
}
avatarCanvas.addEventListener('wheel', handleAvatarWheel, { passive: false });
const avatarPane = document.getElementById('avatar-pane');
if (avatarPane) {
  avatarPane.addEventListener('wheel', handleAvatarWheel, { passive: false });
}

// ---------------------------------------------------------------------------
// 9. Speech-to-Text (STT) Push-to-Talk & Backend Fallback
// ---------------------------------------------------------------------------
const SpeechRec = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
let recognition: any = null;
let isListening = false;
let micLevelInterval: number | null = null;
let browserAudioCtx: AudioContext | null = null;
let browserAnalyser: AnalyserNode | null = null;
let browserStream: MediaStream | null = null;
let browserLevelRaf: number | null = null;

if (SpeechRec) {
  recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  recognition.onstart = () => {
    micVal.textContent = 'Listening... [browser]';
    micBtn.classList.add('recording');
    taskVal.textContent = 'Listening';
  };

  recognition.onresult = (event: any) => {
    let transcript = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    if (event.results[event.results.length - 1].isFinal && transcript.trim()) {
      isListening = false;
      recognition.stop();
      cleanupMicMeter();
      micVal.textContent = `Idle (Space/F2) [${micSource}]`;
      micBtn.classList.remove('recording');
      dispatchTranscription(transcript);
    }
  };

  recognition.onerror = (event: any) => {
    handleMicError(event);
  };

  recognition.onend = () => {
    if (isListening) {
      isListening = false;
      cleanupMicMeter();
      micVal.textContent = `Idle (Space/F2) [${micSource}]`;
      micBtn.classList.remove('recording');
      taskVal.textContent = 'Idle';
    }
  };
}

function handleMicError(err: any) {
  const errName = err.name || err.error || 'MicError';
  let fix = 'Check your microphone hardware and permissions.';
  if (errName === 'NotAllowedError' || errName === 'not-allowed') {
    fix = 'Permission denied. Click "Grant Mic" button or allow microphone in Brave site settings.';
    if (grantMicBtn) grantMicBtn.classList.remove('hidden');
  } else if (errName === 'NotFoundError') {
    fix = 'No microphone device was detected on your computer.';
  } else if (errName === 'NotReadableError') {
    fix = 'Microphone hardware is busy or in use by another program.';
  } else if (errName === 'SecurityError') {
    fix = 'Media capture restricted by security context.';
  }

  micVal.textContent = `Mic: Error (${errName})`;
  micBtn.classList.remove('recording');
  cleanupMicMeter();
  taskVal.textContent = 'Idle';

  appendLog('system', '[mic-error]', `${errName}: ${fix}`);

  // Query navigator.permissions for detailed microphone state
  if (navigator.permissions && (navigator.permissions as any).query) {
    (navigator.permissions as any).query({ name: 'microphone' }).then((status: any) => {
      appendLog('system', '[permissions]', `Microphone permission state: "${status.state}"`);
    }).catch(() => {});
  }

  // Automatic Fallback to Linux Backend Capture (sounddevice / PipeWire)
  if (micSource !== 'backend') {
    appendLog('system', '[info]', 'Automatically switching to Linux backend microphone capture (sounddevice/PipeWire). No browser permission required.');
    setMicSource('backend');
  }
}

function cleanupMicMeter() {
  if (micLevelFill) micLevelFill.style.width = '0%';
  if (micLevelInterval) {
    clearInterval(micLevelInterval);
    micLevelInterval = null;
  }
  if (browserLevelRaf) {
    cancelAnimationFrame(browserLevelRaf);
    browserLevelRaf = null;
  }
  if (browserStream) {
    browserStream.getTracks().forEach(t => t.stop());
    browserStream = null;
  }
}

async function startVoiceInput() {
  if (isListening) return;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }

  isListening = true;
  duckMusic(true);
  micBtn.classList.add('recording');
  if (focusMicBtn) {
    focusMicBtn.classList.add('recording');
    focusMicBtn.textContent = '🔴';
  }
  taskVal.textContent = 'Recording...';
  micVal.textContent = `Recording... [${micSource}]`;

  if (micSource === 'backend') {
    // Backend Recording (sounddevice / PipeWire)
    try {
      const res = await fetch(`${ROXY_API}/api/mic/start`, { method: 'POST' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || `HTTP ${res.status}`);
      }

      // Live VU Level Meter polling
      micLevelInterval = window.setInterval(async () => {
        if (!isListening) return;
        try {
          const lRes = await fetch(`${ROXY_API}/api/mic/level`);
          const lData = await lRes.json();
          const pct = Math.min(100, Math.round((lData.level || 0) * 200));
          if (micLevelFill) micLevelFill.style.width = `${pct}%`;
        } catch {}
      }, 70);
    } catch (e: any) {
      appendLog('system', '[mic-error]', `Backend mic start failed: ${e.message}`);
      await stopVoiceInput(true);
    }
  } else {
    // Browser Recording
    if (!SpeechRec) {
      appendLog('system', '[info]', 'Browser SpeechRecognition unavailable. Switching to backend mic capture.');
      setMicSource('backend');
      await startVoiceInput();
      return;
    }

    try {
      if (!browserAudioCtx) {
        browserAudioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      }
      if (browserAudioCtx.state === 'suspended') {
        await browserAudioCtx.resume();
      }
      browserStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      browserAnalyser = browserAudioCtx.createAnalyser();
      browserAnalyser.fftSize = 256;
      const srcNode = browserAudioCtx.createMediaStreamSource(browserStream);
      srcNode.connect(browserAnalyser);

      const dataArray = new Uint8Array(browserAnalyser.frequencyBinCount);
      const trackBrowserLevel = () => {
        if (!isListening || !browserAnalyser) return;
        browserAnalyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const avg = sum / dataArray.length;
        const pct = Math.min(100, Math.round((avg / 128) * 100));
        if (micLevelFill) micLevelFill.style.width = `${pct}%`;
        browserLevelRaf = requestAnimationFrame(trackBrowserLevel);
      };
      trackBrowserLevel();

      recognition.start();
    } catch (err: any) {
      handleMicError(err);
      await stopVoiceInput(true);
    }
  }
}

async function stopVoiceInput(abort = false) {
  duckMusic(false);
  if (!isListening) return;
  isListening = false;
  micBtn.classList.remove('recording');
  if (focusMicBtn) {
    focusMicBtn.classList.remove('recording');
    focusMicBtn.textContent = '🎤';
  }
  cleanupMicMeter();

  if (abort) {
    micVal.textContent = `Idle (Space/F2) [${micSource}]`;
    taskVal.textContent = 'Idle';
    return;
  }

  if (micSource === 'backend') {
    micVal.textContent = 'Transcribing... [backend]';
    taskVal.textContent = 'Transcribing';
    try {
      const res = await fetch(`${ROXY_API}/api/mic/stop`, { method: 'POST' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.error || `HTTP ${res.status}`);
      }
      const data = await res.json();
      micVal.textContent = `Idle (Space/F2) [${micSource}]`;

      // In-character reaction when audio was unclear / dead air / very low confidence
      if (data.unclear) {
        taskVal.textContent = 'Confused';
        const reply = data.in_character_reply || "Could you repeat that? I didn't quite catch that.";
        appendLog('roxy', 'roxy>', `[emotion:confused] ${reply}`);
        if (avatar) avatar.setExpression('surprise');
        moodVal.textContent = 'confused';
        void queueAudioChunk(0, `${ROXY_API}/api/tts?text=${encodeURIComponent(reply)}&lang=en`, reply);
        taskVal.textContent = 'Idle';
        return;
      }

      // Low confidence gate: route to preview/repeat gate, never straight to LLM
      if (data.low_confidence) {
        taskVal.textContent = 'Reviewing';
        promptInput.value = data.text;
        promptInput.focus();
        appendLog('system', '[stt-preview]', `Low confidence transcript (${Math.round((data.confidence || 0) * 100)}%): "${data.text}". Review before sending (Enter to send, Esc to cancel).`);
        showToast(`Review speech transcript (${Math.round((data.confidence || 0) * 100)}%)`, 'info');
        return;
      }

      if (data.text && data.text.trim()) {
        dispatchTranscription(data.text);
      } else {
        taskVal.textContent = 'Idle';
        appendLog('system', '[info]', 'No speech detected.');
      }
    } catch (e: any) {
      appendLog('system', '[mic-error]', `Backend transcription error: ${e.message}`);
      micVal.textContent = `Error: ${e.message}`;
      taskVal.textContent = 'Idle';
    }
  } else {
    micVal.textContent = 'Transcribing... [browser]';
    taskVal.textContent = 'Transcribing';
    try {
      if (recognition) recognition.stop();
    } catch {}
  }
}

// ---------------------------------------------------------------------------
// 12. Proactive Idle Companion Check-ins
// ---------------------------------------------------------------------------
let lastUserActivityTime = Date.now();
let idleCheckinEnabled = localStorage.getItem('roxy-idle-checkin') !== 'false';
let lastIdleCheckinTime = 0;

function recordUserActivity() {
  lastUserActivityTime = Date.now();
}

window.addEventListener('keydown', recordUserActivity, { passive: true });
window.addEventListener('click', recordUserActivity, { passive: true });
window.addEventListener('mousemove', recordUserActivity, { passive: true });

setInterval(async () => {
  if (!idleCheckinEnabled || isQueuePlaying || isListening || isTabHidden) return;
  if (taskVal.textContent !== 'Idle') return;

  const now = Date.now();
  const idleSec = (now - lastUserActivityTime) / 1000;
  // Trigger after 180s (3 min) of silence, at most once every 5 minutes
  if (idleSec >= 180 && now - lastIdleCheckinTime > 300000) {
    lastIdleCheckinTime = now;
    try {
      const res = await fetch(`${ROXY_API}/api/idle`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.reply) return;

      appendLog('roxy', 'roxy>', data.raw_text || data.reply);
      if (avatar && data.emotion) {
        avatar.setExpression(data.emotion as LiveExpression);
        moodVal.textContent = data.emotion;
      }
      if (data.affection) {
        updateAffectionDisplay(data.affection);
      }
      if (!voiceMuted && data.audio_url) {
        queueAudioChunk(
          0,
          data.audio_url,
          data.reply,
          data.word_timings,
          data.visemes,
          data.provider,
          data.status_label,
        );
      }
    } catch {
      // Ignore background check-in network failure
    }
  }
}, 10000);
