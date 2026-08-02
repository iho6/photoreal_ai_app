(function (global) {
  "use strict";

  var M = null;

  var EYE_OPEN =
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF =
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.1A10.5 10.5 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1"/><path d="M6.1 6.1C3.9 7.7 2 12 2 12s3.5 7 10 7c1.4 0 2.7-.3 3.9-.8"/></svg>';

  function model() {
    return M || (M = global.TimelineModel);
  }

  function createEditorDom(UI) {
    var root = document.createElement("section");
    root.className = "nle";
    root.setAttribute("aria-label", "Timeline editor");

    var transport = document.createElement("div");
    transport.className = "nle-transport";

    var playBtn = UI.createButton({ label: "Play", id: "nle-play" });
    var toStartBtn = UI.createButton({ label: "|<", id: "nle-tostart" });
    toStartBtn.setAttribute("aria-label", "Go to start");
    var splitBtn = UI.createButton({ label: "Split", id: "nle-split" });
    var importBtn = UI.createButton({ label: "Import", id: "nle-import" });
    var timeEl = document.createElement("div");
    timeEl.className = "nle-time";
    timeEl.textContent = "00:00.00";

    var zoomOutBtn = UI.createButton({ label: "−", id: "nle-zoom-out" });
    zoomOutBtn.setAttribute("aria-label", "Zoom out");
    var zoomInBtn = UI.createButton({ label: "+", id: "nle-zoom-in" });
    zoomInBtn.setAttribute("aria-label", "Zoom in");
    var snapBtn = UI.createButton({ label: "Snap", id: "nle-snap" });
    snapBtn.setAttribute("aria-pressed", "true");

    var leftTools = document.createElement("div");
    leftTools.className = "nle-transport__left";
    leftTools.appendChild(toStartBtn);
    leftTools.appendChild(playBtn);
    leftTools.appendChild(splitBtn);
    leftTools.appendChild(importBtn);

    var rightTools = document.createElement("div");
    rightTools.className = "nle-transport__right";
    rightTools.appendChild(zoomOutBtn);
    rightTools.appendChild(zoomInBtn);
    rightTools.appendChild(snapBtn);

    transport.appendChild(leftTools);
    transport.appendChild(timeEl);
    transport.appendChild(rightTools);

    var body = document.createElement("div");
    body.className = "nle-body";

    var headersCol = document.createElement("div");
    headersCol.className = "nle-headers";

    var scroll = document.createElement("div");
    scroll.className = "nle-scroll";

    var scrollInner = document.createElement("div");
    scrollInner.className = "nle-scroll-inner";

    var ruler = document.createElement("div");
    ruler.className = "nle-ruler";
    ruler.setAttribute("role", "slider");
    ruler.setAttribute("aria-label", "Time ruler");

    var lanes = document.createElement("div");
    lanes.className = "nle-lanes";

    var playhead = document.createElement("div");
    playhead.className = "nle-playhead";
    playhead.setAttribute("aria-hidden", "true");
    var playheadHandle = document.createElement("div");
    playheadHandle.className = "nle-playhead__handle";
    playhead.appendChild(playheadHandle);

    scrollInner.appendChild(ruler);
    scrollInner.appendChild(lanes);
    scrollInner.appendChild(playhead);
    scroll.appendChild(scrollInner);

    body.appendChild(headersCol);
    body.appendChild(scroll);

    var addWrap = document.createElement("div");
    addWrap.className = "nle-add-track";
    var addTrackBtn = UI.createButton({ label: "+ Track" });
    addWrap.appendChild(addTrackBtn);

    var fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = "video/*,image/*,audio/*";
    fileInput.hidden = true;
    fileInput.className = "nle-file-input";

    root.appendChild(transport);
    root.appendChild(body);
    root.appendChild(addWrap);
    root.appendChild(fileInput);

    return {
      root: root,
      transport: transport,
      playBtn: playBtn,
      toStartBtn: toStartBtn,
      splitBtn: splitBtn,
      importBtn: importBtn,
      timeEl: timeEl,
      zoomOutBtn: zoomOutBtn,
      zoomInBtn: zoomInBtn,
      snapBtn: snapBtn,
      headersCol: headersCol,
      scroll: scroll,
      scrollInner: scrollInner,
      ruler: ruler,
      lanes: lanes,
      playhead: playhead,
      addTrackBtn: addTrackBtn,
      fileInput: fileInput,
    };
  }

  function niceStep(pxPerSec) {
    var candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
    var targetPx = 80;
    var best = 1;
    var bestScore = Infinity;
    for (var i = 0; i < candidates.length; i++) {
      var px = candidates[i] * pxPerSec;
      var score = Math.abs(px - targetPx);
      if (score < bestScore) {
        bestScore = score;
        best = candidates[i];
      }
    }
    return best;
  }

  function renderRuler(dom, state) {
    var m = model();
    var viewport = dom.scroll ? dom.scroll.clientWidth : 0;
    var width = m.timelineWidth(state, viewport);
    dom.scrollInner.style.width = width + "px";
    dom.ruler.style.width = width + "px";
    dom.ruler.innerHTML = "";
    var step = niceStep(state.pxPerSec);
    var endTime = width / state.pxPerSec;
    var edgePad = 64;
    for (var t = 0; t <= endTime + 0.0001; t += step) {
      var x = t * state.pxPerSec;
      if (x > width) break;
      var tick = document.createElement("div");
      tick.className = "nle-ruler__tick";
      tick.style.left = x + "px";
      var label = document.createElement("span");
      label.textContent = m.formatTime(t, state.fps).replace(/\.\d+$/, "");
      if (x > width - edgePad) {
        tick.classList.add("nle-ruler__tick--end");
      }
      tick.appendChild(label);
      dom.ruler.appendChild(tick);
    }
  }

  function renderPlayhead(dom, state) {
    var x = state.playhead * state.pxPerSec;
    dom.playhead.style.transform = "translateX(" + x + "px)";
    dom.timeEl.textContent = model().formatTime(state.playhead, state.fps);
    dom.playBtn.textContent = state.playing ? "Pause" : "Play";
    dom.snapBtn.setAttribute("aria-pressed", state.snap ? "true" : "false");
    if (state.snap) dom.snapBtn.classList.add("is-on");
    else dom.snapBtn.classList.remove("is-on");
  }

  function renderTracks(dom, state) {
    var m = model();
    dom.headersCol.innerHTML = "";
    dom.lanes.innerHTML = "";

    var spacer = document.createElement("div");
    spacer.className = "nle-headers__ruler-spacer";
    dom.headersCol.appendChild(spacer);

    var viewport = dom.scroll ? dom.scroll.clientWidth : 0;
    var width = m.timelineWidth(state, viewport);

    if (!state.tracks.length) {
      var empty = document.createElement("div");
      empty.className = "nle-empty";
      empty.textContent = "No tracks — click + Track, then drop media onto a lane.";
      empty.style.width = width + "px";
      dom.lanes.appendChild(empty);
      return;
    }

    for (var i = 0; i < state.tracks.length; i++) {
      var track = state.tracks[i];

      var header = document.createElement("div");
      header.className = "nle-header";
      header.dataset.trackId = track.id;
      header.style.height = track.height + "px";

      var name = document.createElement("div");
      name.className = "nle-header__name";
      name.textContent = track.name;

      var eyeBtn = document.createElement("button");
      eyeBtn.type = "button";
      eyeBtn.className = "nle-header__eye";
      eyeBtn.dataset.action = "toggle-hidden";
      eyeBtn.dataset.trackId = track.id;
      eyeBtn.setAttribute("aria-pressed", track.hidden ? "true" : "false");
      eyeBtn.setAttribute(
        "aria-label",
        track.hidden ? "Show " + track.name : "Hide " + track.name
      );
      eyeBtn.innerHTML = track.hidden ? EYE_OFF : EYE_OPEN;

      header.appendChild(name);
      header.appendChild(eyeBtn);
      dom.headersCol.appendChild(header);

      var lane = document.createElement("div");
      lane.className = "nle-lane";
      lane.dataset.trackId = track.id;
      lane.style.height = track.height + "px";
      lane.style.width = width + "px";
      if (track.locked) lane.dataset.locked = "true";
      if (track.hidden) lane.dataset.hidden = "true";

      var clips = m.clipsOnTrack(state, track.id);
      for (var j = 0; j < clips.length; j++) {
        lane.appendChild(renderClip(clips[j], state));
      }
      dom.lanes.appendChild(lane);
    }
  }

  function renderClip(clip, state) {
    var el = document.createElement("div");
    el.className = "nle-clip";
    el.dataset.clipId = clip.id;
    el.dataset.trackId = clip.trackId;
    el.dataset.mediaType = clip.mediaType;
    if (clip.role) el.dataset.role = clip.role;
    if (
      clip.role === "reference" &&
      clip.refSlot != null &&
      isFinite(Number(clip.refSlot))
    ) {
      el.dataset.refSlot = String(Math.floor(Number(clip.refSlot)));
    }
    el.style.left = clip.start * state.pxPerSec + "px";
    el.style.width = Math.max(4, clip.duration * state.pxPerSec) + "px";
    if (state.selection && state.selection.clipId === clip.id) {
      el.dataset.selected = "true";
    }

    var badge = document.createElement("span");
    badge.className = "nle-clip__badge";
    if (clip.role === "reference") {
      badge.textContent =
        clip.refSlot != null && isFinite(Number(clip.refSlot))
          ? "ref" + Math.floor(Number(clip.refSlot))
          : "ref";
    } else if (clip.role === "location") {
      badge.textContent = "loc";
    } else {
      badge.textContent = clip.mediaType;
    }

    var label = document.createElement("span");
    label.className = "nle-clip__label";
    label.textContent = clip.name;

    var leftHandle = document.createElement("div");
    leftHandle.className = "nle-clip__handle nle-clip__handle--left";
    leftHandle.dataset.edge = "left";

    var rightHandle = document.createElement("div");
    rightHandle.className = "nle-clip__handle nle-clip__handle--right";
    rightHandle.dataset.edge = "right";

    el.appendChild(leftHandle);
    el.appendChild(badge);
    el.appendChild(label);
    el.appendChild(rightHandle);
    return el;
  }

  function renderAll(dom, state) {
    renderRuler(dom, state);
    renderTracks(dom, state);
    renderPlayhead(dom, state);
  }

  function xToTime(dom, state, clientX) {
    var rect = dom.scrollInner.getBoundingClientRect();
    var x = clientX - rect.left + dom.scroll.scrollLeft;
    return Math.max(0, x / state.pxPerSec);
  }

  function followPlayhead(dom, state) {
    if (!state.playing) return;
    var x = state.playhead * state.pxPerSec;
    var viewLeft = dom.scroll.scrollLeft;
    var viewRight = viewLeft + dom.scroll.clientWidth;
    var margin = 48;
    if (x < viewLeft + margin || x > viewRight - margin) {
      dom.scroll.scrollLeft = Math.max(0, x - dom.scroll.clientWidth * 0.35);
    }
  }

  global.TimelineRender = {
    createEditorDom: createEditorDom,
    renderAll: renderAll,
    renderPlayhead: renderPlayhead,
    renderTracks: renderTracks,
    renderRuler: renderRuler,
    xToTime: xToTime,
    followPlayhead: followPlayhead,
  };
})(window);
