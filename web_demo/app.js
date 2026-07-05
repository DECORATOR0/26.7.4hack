const PUBLIC_URL = "http://39.105.210.249/";

const typeList = document.querySelector("#typeList");
const eventList = document.querySelector("#eventList");
const video = document.querySelector("#eventVideo");
const statEvents = document.querySelector("#statEvents");
const statGoals = document.querySelector("#statGoals");
const eventSubtitle = document.querySelector("#eventSubtitle");
const publicLink = document.querySelector("#publicLink");
const versionBadge = document.querySelector("#versionBadge");
const languageSelect = document.querySelector("#languageSelect");
const styleSelect = document.querySelector("#styleSelect");
const playerPanel = document.querySelector(".player-panel");
const railLinks = Array.from(document.querySelectorAll(".page-rail__link"));
const railTargets = railLinks
  .map((link) => document.getElementById(link.dataset.scrollTarget))
  .filter(Boolean);

let demoData = null;
let activeType = null;
let activeEventId = null;
let selectedLanguage = localStorage.getItem("demoLanguage") || "zh-CN";
let selectedStyle = localStorage.getItem("demoStyle") || "passionate";

if (publicLink) {
  publicLink.href = PUBLIC_URL;
  publicLink.textContent = PUBLIC_URL;
}

function syncDeviceClass() {
  const isMobile =
    window.matchMedia("(max-width: 960px)").matches ||
    window.matchMedia("(hover: none) and (pointer: coarse)").matches;
  document.documentElement.dataset.device = isMobile ? "mobile" : "desktop";
  document.body.classList.toggle("is-mobile-device", isMobile);
  document.body.classList.toggle("is-desktop-device", !isMobile);
}

syncDeviceClass();
window.addEventListener("resize", syncDeviceClass);

function easeInOutCubic(value) {
  return value < 0.5 ? 4 * value * value * value : 1 - Math.pow(-2 * value + 2, 3) / 2;
}

function animateScrollTo(targetY, duration = 760) {
  const startY = window.scrollY;
  const distance = targetY - startY;
  const startedAt = performance.now();

  function tick(now) {
    const elapsed = Math.min(1, (now - startedAt) / duration);
    window.scrollTo(0, startY + distance * easeInOutCubic(elapsed));
    if (elapsed < 1) {
      requestAnimationFrame(tick);
    }
  }

  requestAnimationFrame(tick);
}

function setActiveRail(targetId) {
  for (const link of railLinks) {
    link.classList.toggle("is-active", link.dataset.scrollTarget === targetId);
  }
}

function scrollToSection(targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const targetY = Math.max(0, window.scrollY + target.getBoundingClientRect().top - 22);
  setActiveRail(targetId);
  history.replaceState(null, "", `#${targetId}`);
  animateScrollTo(targetY);
}

for (const link of railLinks) {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    scrollToSection(link.dataset.scrollTarget);
  });
}

if (railTargets.length) {
  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) {
        setActiveRail(visible.target.id);
      }
    },
    {
      rootMargin: "-34% 0px -46% 0px",
      threshold: [0.12, 0.28, 0.5, 0.72],
    }
  );
  for (const target of railTargets) {
    observer.observe(target);
  }
}

function byType(type) {
  return demoData.categories.find((category) => category.type === type);
}

function syncVariantControls() {
  const languageValues = languageSelect ? Array.from(languageSelect.options).map((option) => option.value) : [];
  const styleValues = styleSelect ? Array.from(styleSelect.options).map((option) => option.value) : [];
  if (languageValues.length && !languageValues.includes(selectedLanguage)) selectedLanguage = "zh-CN";
  if (styleValues.length && !styleValues.includes(selectedStyle)) selectedStyle = "passionate";
  if (languageSelect) languageSelect.value = selectedLanguage;
  if (styleSelect) styleSelect.value = selectedStyle;
}

function pickCopyVariant(item) {
  const sources = [item.copyVariants, item.variants, item.localizedCopy].filter(Boolean);
  for (const source of sources) {
    const languageBlock = source[selectedLanguage] || source[selectedLanguage.split("-")[0]];
    if (!languageBlock) continue;
    if (typeof languageBlock === "string") return { script: languageBlock };
    const styleBlock =
      languageBlock[selectedStyle] ||
      languageBlock.default ||
      languageBlock.steady ||
      languageBlock.passionate;
    if (!styleBlock) continue;
    if (typeof styleBlock === "string") return { script: styleBlock };
    return styleBlock;
  }
  return null;
}

function variantField(item, field, fallback) {
  const variant = pickCopyVariant(item);
  if (!variant) return fallback;
  return variant[field] || fallback;
}

function currentTitle(item) {
  return variantField(item, "title", item.title || "");
}

function currentScript(item) {
  return normalizeSubtitleText(variantField(item, "script", item.script || "暂无解说文案。"));
}

function fitSubtitleText() {
  if (!eventSubtitle) return;
  if (!eventSubtitle.textContent.trim()) return;

  const isMobile = window.matchMedia("(max-width: 960px)").matches;
  const maxSize = isMobile ? 18 : 22;
  const minSize = isMobile ? 8 : 10;
  const lineHeightRatio = 1.28;

  eventSubtitle.style.setProperty("--caption-font-size", `${maxSize}px`);
  eventSubtitle.style.lineHeight = String(lineHeightRatio);

  const maxHeight = eventSubtitle.clientHeight || Number.parseFloat(window.getComputedStyle(eventSubtitle).maxHeight) || 96;
  for (let size = maxSize; size >= minSize; size -= 1) {
    eventSubtitle.style.setProperty("--caption-font-size", `${size}px`);
    const measuredStyle = window.getComputedStyle(eventSubtitle);
    const verticalPadding = Number.parseFloat(measuredStyle.paddingTop) + Number.parseFloat(measuredStyle.paddingBottom);
    const lineHeight = size * lineHeightRatio;
    const fitsHeight = eventSubtitle.scrollHeight <= maxHeight + 1;
    const fitsWidth = eventSubtitle.scrollWidth <= eventSubtitle.clientWidth + 1;
    const lines = Math.ceil(Math.max(0, eventSubtitle.scrollHeight - verticalPadding) / lineHeight);
    if (fitsHeight && fitsWidth && lines <= 3) {
      return;
    }
  }

  eventSubtitle.style.setProperty("--caption-font-size", `${minSize}px`);
}

function normalizeSubtitleText(text) {
  let value = String(text || "");
  if (!selectedLanguage.startsWith("zh")) {
    value = value
      .replace(/第\s*(\d+)\s*分\s*(\d+)\s*秒/g, (_, minute, second) => `${Number(minute)}:${String(Number(second)).padStart(2, "0")}`)
      .replace(/第\s*(\d+)\s*分钟/g, (_, minute) => `${Number(minute)}'`)
      .replace(/第\s*(\d+)\s*分/g, (_, minute) => `${Number(minute)}'`);
  }
  return value;
}

function compactMatchTime(value) {
  const text = String(value || "");
  const match = text.match(/第(\d+)分(?:(\d+)秒)?/);
  if (!match) return text || "--";
  return `${Number(match[1])}:${String(Number(match[2] || 0)).padStart(2, "0")}`;
}

function compactEventLabel(item, index) {
  const labels = {
    goal: "进",
    shot_chance: "射",
    corner: "角",
    free_kick: "任",
    foul_card_dispute: "争",
    substitution: "换",
  };
  return `${labels[item.type] || item.typeLabel || "项"}${index + 1}`;
}

function compactTeam(item) {
  const text = `${item.team || ""} ${item.title || ""} ${item.evidence || ""}`;
  if (text.includes("库拉索")) return "库拉索";
  if (text.includes("德国")) return "德国";
  return "";
}

function compactTitle(item) {
  const title = item.title || "";
  const team = compactTeam(item);
  const prefix = team ? `${team} ` : "";
  if (item.type === "goal") return `${prefix}${item.scoreAfter ? item.scoreAfter : "进球"}`;
  if (item.type === "shot_chance") {
    if (/扑|救/.test(title)) return `${prefix}射门被扑`;
    if (/挡|封|防守/.test(title)) return `${prefix}射门被挡`;
    return `${prefix}射门机会`;
  }
  if (item.type === "corner") return `${prefix}角球`;
  if (item.type === "free_kick") return `${prefix}${title.includes("前场") ? "前场任意球" : "任意球"}`;
  if (item.type === "foul_card_dispute") return `${prefix}争议判罚`;
  if (item.type === "substitution") return `${prefix}换人调整`;
  return title;
}

function formatMediaTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function installVideoControls(targetVideo) {
  if (!targetVideo || targetVideo.dataset.customControlsInstalled === "true") return;
  targetVideo.dataset.customControlsInstalled = "true";
  targetVideo.controls = false;

  const controls = document.createElement("div");
  controls.className = "custom-video-controls";
  controls.innerHTML = `
    <button class="video-control-button" type="button" data-video-toggle aria-label="播放或暂停视频">播放</button>
    <span class="video-time" data-video-current>00:00</span>
    <div class="video-seek" data-video-seek role="slider" tabindex="0" aria-label="视频进度" aria-valuemin="0" aria-valuemax="1000" aria-valuenow="0">
      <span class="video-seek__fill"></span>
      <span class="video-seek__thumb"></span>
    </div>
    <span class="video-time" data-video-duration>00:00</span>
    <button class="video-control-button video-control-button--compact" type="button" data-video-fullscreen aria-label="全屏播放">全屏</button>
  `;
  const wrap = targetVideo.closest(".video-wrap");
  if (wrap) {
    wrap.insertAdjacentElement("afterend", controls);
  } else {
    targetVideo.insertAdjacentElement("afterend", controls);
  }

  const toggle = controls.querySelector("[data-video-toggle]");
  const seek = controls.querySelector("[data-video-seek]");
  const current = controls.querySelector("[data-video-current]");
  const duration = controls.querySelector("[data-video-duration]");
  const fullscreen = controls.querySelector("[data-video-fullscreen]");
  let seeking = false;
  let pointerSeeking = false;
  let mouseSeeking = false;
  let activeTouchId = null;

  function mediaDuration() {
    return Number.isFinite(targetVideo.duration) && targetVideo.duration > 0 ? targetVideo.duration : 0;
  }

  function setSeekProgress(percent) {
    const safePercent = Math.max(0, Math.min(100, percent));
    seek.style.setProperty("--seek-progress", `${safePercent}%`);
    seek.setAttribute("aria-valuenow", String(Math.round(safePercent * 10)));
    seek.dataset.value = String(Math.round(safePercent * 10));
  }

  function seekValueRatio() {
    return Number(seek.dataset.value || "0") / 1000;
  }

  function syncControls() {
    const total = mediaDuration();
    const elapsed = Number.isFinite(targetVideo.currentTime) ? targetVideo.currentTime : 0;
    const percent = total ? (elapsed / total) * 100 : 0;
    if (!seeking) {
      setSeekProgress(percent);
    }
    seek.classList.toggle("is-disabled", !total);
    seek.setAttribute("aria-disabled", total ? "false" : "true");
    current.textContent = formatMediaTime(elapsed);
    duration.textContent = formatMediaTime(total);
    toggle.textContent = targetVideo.paused ? "播放" : "暂停";
    if (seeking) {
      setSeekProgress(seekValueRatio() * 100);
    }
  }

  function applySeek() {
    const total = mediaDuration();
    if (!total) return;
    const targetTime = seekValueRatio() * total;
    const safeTargetTime = Math.max(0, Math.min(total, targetTime));
    targetVideo.currentTime = safeTargetTime;
    current.textContent = formatMediaTime(safeTargetTime);
    setSeekProgress((safeTargetTime / total) * 100);
  }

  function seekFromClientX(clientX) {
    const rect = seek.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    setSeekProgress(ratio * 100);
    applySeek();
  }

  function togglePlayback() {
    if (targetVideo.paused) {
      const playPromise = targetVideo.play();
      if (playPromise && typeof playPromise.catch === "function") {
        playPromise.catch((error) => {
          console.warn("Video playback was blocked or failed.", error);
        });
      }
      return;
    }
    targetVideo.pause();
  }

  function enterFullscreen() {
    if (targetVideo.requestFullscreen) {
      targetVideo.requestFullscreen();
      return;
    }
    if (targetVideo.webkitEnterFullscreen) {
      targetVideo.webkitEnterFullscreen();
    }
  }

  toggle.addEventListener("click", togglePlayback);
  targetVideo.addEventListener("click", togglePlayback);
  fullscreen.addEventListener("click", enterFullscreen);
  seek.addEventListener("pointerdown", (event) => {
    seeking = true;
    pointerSeeking = true;
    seek.setPointerCapture?.(event.pointerId);
    seekFromClientX(event.clientX);
    event.preventDefault();
  });
  seek.addEventListener("pointermove", (event) => {
    if (!pointerSeeking) return;
    seekFromClientX(event.clientX);
    event.preventDefault();
  });
  seek.addEventListener("pointerup", (event) => {
    if (pointerSeeking) {
      seekFromClientX(event.clientX);
    } else {
      applySeek();
    }
    pointerSeeking = false;
    seeking = false;
  });
  seek.addEventListener("pointercancel", () => {
    pointerSeeking = false;
    seeking = false;
    syncControls();
  });
  seek.addEventListener("mousedown", (event) => {
    seeking = true;
    mouseSeeking = true;
    seekFromClientX(event.clientX);
    event.preventDefault();
  });
  seek.addEventListener("mousemove", (event) => {
    if (event.buttons !== 1) return;
    seeking = true;
    seekFromClientX(event.clientX);
    event.preventDefault();
  });
  seek.addEventListener("mouseup", (event) => {
    seekFromClientX(event.clientX);
    mouseSeeking = false;
    seeking = false;
    event.preventDefault();
  });
  seek.addEventListener("click", (event) => {
    seekFromClientX(event.clientX);
    seeking = false;
    event.preventDefault();
  });
  window.addEventListener("mousemove", (event) => {
    if (!mouseSeeking) return;
    seekFromClientX(event.clientX);
    event.preventDefault();
  });
  window.addEventListener("mouseup", (event) => {
    if (!mouseSeeking) return;
    seekFromClientX(event.clientX);
    mouseSeeking = false;
    seeking = false;
    syncControls();
    event.preventDefault();
  });
  seek.addEventListener(
    "touchstart",
    (event) => {
      const touch = event.changedTouches[0];
      if (!touch) return;
      activeTouchId = touch.identifier;
      seeking = true;
      seekFromClientX(touch.clientX);
      event.preventDefault();
    },
    { passive: false }
  );
  window.addEventListener(
    "touchmove",
    (event) => {
      if (activeTouchId === null) return;
      const touch = Array.from(event.changedTouches).find((item) => item.identifier === activeTouchId);
      if (!touch) return;
      seekFromClientX(touch.clientX);
      event.preventDefault();
    },
    { passive: false }
  );
  window.addEventListener(
    "touchend",
    (event) => {
      if (activeTouchId === null) return;
      const touch = Array.from(event.changedTouches).find((item) => item.identifier === activeTouchId);
      if (touch) {
        seekFromClientX(touch.clientX);
      }
      activeTouchId = null;
      seeking = false;
      event.preventDefault();
    },
    { passive: false }
  );
  window.addEventListener(
    "touchcancel",
    () => {
      activeTouchId = null;
      seeking = false;
      syncControls();
    },
    { passive: false }
  );
  seek.addEventListener("keydown", (event) => {
    const total = mediaDuration();
    if (!total) return;
    let targetTime = targetVideo.currentTime;
    if (event.key === "ArrowLeft") targetTime -= event.shiftKey ? 5 : 1;
    else if (event.key === "ArrowRight") targetTime += event.shiftKey ? 5 : 1;
    else if (event.key === "Home") targetTime = 0;
    else if (event.key === "End") targetTime = total;
    else return;
    const safeTargetTime = Math.max(0, Math.min(total, targetTime));
    targetVideo.currentTime = safeTargetTime;
    current.textContent = formatMediaTime(safeTargetTime);
    setSeekProgress((safeTargetTime / total) * 100);
    event.preventDefault();
  });

  for (const eventName of ["loadedmetadata", "durationchange", "timeupdate", "play", "pause", "ended", "emptied", "seeked"]) {
    targetVideo.addEventListener(eventName, syncControls);
  }
  syncControls();
}

function rerenderActiveEvent() {
  if (!demoData || !activeType || !activeEventId) return;
  renderEvents(byType(activeType).items);
  setActiveEvent(activeEventId);
}

function playSelectedVideo() {
  if (!video || !video.getAttribute("src")) return;
  const playPromise = video.play();
  if (playPromise && typeof playPromise.catch === "function") {
    playPromise.catch((error) => {
      console.warn("Video playback was blocked or failed.", error);
    });
  }
}

function focusPlayer() {
  if (!playerPanel || window.matchMedia("(min-width: 961px)").matches) return;
  playerPanel.scrollIntoView({ block: "start", behavior: "smooth" });
}

function setActiveType(type, options = {}) {
  activeType = type;
  const category = byType(type);
  if (!category) return;
  renderTypes();
  renderEvents(category.items);
  setActiveEvent(category.items[0].id, options);
}

function setActiveEvent(id, options = {}) {
  const item = demoData.events.find((event) => event.id === id);
  if (!item) return;
  activeEventId = id;
  renderEvents(byType(activeType).items);
  if (video.getAttribute("src") !== item.clip) {
    video.src = item.clip;
    video.load();
  }
  if (eventSubtitle) {
    eventSubtitle.textContent = currentScript(item);
    requestAnimationFrame(fitSubtitleText);
  }
  if (options.focusPlayer) {
    focusPlayer();
  }
  if (options.play) {
    playSelectedVideo();
  }
}

function renderTypes() {
  typeList.innerHTML = "";
  for (const category of demoData.categories) {
    const button = document.createElement("button");
    button.className = `type-button${category.type === activeType ? " is-active" : ""}`;
    button.type = "button";
    button.innerHTML = `<span>${category.label}</span><span class="type-count">${category.items.length}</span>`;
    button.addEventListener("click", () => setActiveType(category.type, { play: true, focusPlayer: true }));
    typeList.appendChild(button);
  }
}

function renderEvents(items) {
  eventList.innerHTML = "";
  for (const [index, item] of items.entries()) {
    const button = document.createElement("button");
    button.className = `event-button${item.id === activeEventId ? " is-active" : ""}`;
    button.type = "button";
    button.title = `${item.matchTime} · ${item.title || ""}`;

    const token = document.createElement("span");
    token.className = "event-token";
    token.textContent = compactEventLabel(item, index);

    const body = document.createElement("span");
    body.className = "event-button__body";

    const time = document.createElement("span");
    time.className = "event-button__time";
    time.textContent = compactMatchTime(item.matchTime);

    const summary = document.createElement("span");
    summary.className = "event-button__summary";
    summary.textContent = compactTitle(item);

    body.append(time, summary);
    button.append(token, body);
    button.addEventListener("click", () => setActiveEvent(item.id, { play: true, focusPlayer: true }));
    eventList.appendChild(button);
  }
}

if (languageSelect) {
  languageSelect.addEventListener("change", () => {
    selectedLanguage = languageSelect.value;
    localStorage.setItem("demoLanguage", selectedLanguage);
    rerenderActiveEvent();
  });
}

if (styleSelect) {
  styleSelect.addEventListener("change", () => {
    selectedStyle = styleSelect.value;
    localStorage.setItem("demoStyle", selectedStyle);
    rerenderActiveEvent();
  });
}

installVideoControls(video);
window.addEventListener("resize", fitSubtitleText);
for (const montageVideo of document.querySelectorAll(".montage__video")) {
  installVideoControls(montageVideo);
}

async function init() {
  syncVariantControls();
  const response = await fetch("data/events.json", { cache: "no-store" });
  demoData = await response.json();
  if (versionBadge) {
    versionBadge.textContent = demoData.versionBadge || `${demoData.versionLabel || demoData.version || "V4.5"} · OCR8`;
  }
  statEvents.textContent = demoData.events.length;
  if (statGoals) {
    statGoals.textContent = demoData.scoreboardGoalCount || demoData.events.filter((event) => event.type === "goal").length;
  }
  setActiveType(demoData.categories[0].type);
}

init().catch((error) => {
  if (eventSubtitle) {
    eventSubtitle.textContent = `Demo 数据加载失败：${String(error)}`;
    requestAnimationFrame(fitSubtitleText);
  }
});
