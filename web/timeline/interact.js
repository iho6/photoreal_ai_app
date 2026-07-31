(function (global) {
  "use strict";

  function bindInteractions(dom, state, preview) {
    var M = global.TimelineModel;
    var R = global.TimelineRender;
    var importTrackId = null;

    function patchClipEl(clip) {
      var el = dom.lanes.querySelector('.nle-clip[data-clip-id="' + clip.id + '"]');
      if (!el) return;
      var lane = dom.lanes.querySelector('.nle-lane[data-track-id="' + clip.trackId + '"]');
      if (lane && el.parentElement !== lane) {
        lane.appendChild(el);
      }
      el.style.left = clip.start * state.pxPerSec + "px";
      el.style.width = Math.max(4, clip.duration * state.pxPerSec) + "px";
      el.dataset.trackId = clip.trackId;
    }

    function refresh() {
      R.renderAll(dom, state);
      preview.sync(state);
      R.followPlayhead(dom, state);
    }

    M.onChange(state, function (s) {
      if (s._emitKind === "playhead") {
        R.renderPlayhead(dom, s);
        preview.sync(s);
        R.followPlayhead(dom, s);
        return;
      }
      if (s._emitKind === "drag" && s.selection) {
        var clip = M.findClip(s, s.selection.clipId);
        if (clip) patchClipEl(clip);
        R.renderPlayhead(dom, s);
        preview.sync(s);
        return;
      }
      R.renderAll(dom, s);
      preview.sync(s);
      R.followPlayhead(dom, s);
    });

    dom.addTrackBtn.addEventListener("click", function () {
      M.addTrack(state);
    });

    dom.importBtn.addEventListener("click", function () {
      if (!state.tracks.length) {
        M.addTrack(state);
      }
      importTrackId = state.tracks[0].id;
      dom.fileInput.value = "";
      dom.fileInput.click();
    });

    dom.fileInput.addEventListener("change", function () {
      var trackId = importTrackId || (state.tracks[0] && state.tracks[0].id);
      if (!trackId || !dom.fileInput.files || !dom.fileInput.files.length) return;
      M.addClipsFromFiles(state, trackId, dom.fileInput.files, state.playhead);
      importTrackId = null;
    });

    dom.headersCol.addEventListener("click", function (ev) {
      var btn = ev.target && ev.target.closest && ev.target.closest("[data-action]");
      if (!btn || !btn.dataset) return;
      if (btn.dataset.action === "toggle-hidden") {
        M.toggleHidden(state, btn.dataset.trackId);
      }
    });

    var menuEl = null;
    function dismissMenu() {
      if (menuEl && menuEl.parentNode) menuEl.parentNode.removeChild(menuEl);
      menuEl = null;
    }

    function showTrackMenu(clientX, clientY, trackId) {
      dismissMenu();
      menuEl = document.createElement("div");
      menuEl.className = "nle-menu";
      menuEl.setAttribute("role", "menu");
      var item = document.createElement("button");
      item.type = "button";
      item.className = "nle-menu__item";
      item.setAttribute("role", "menuitem");
      item.textContent = "Delete";
      item.addEventListener("click", function () {
        dismissMenu();
        M.deleteTrack(state, trackId);
      });
      menuEl.appendChild(item);
      document.body.appendChild(menuEl);
      var pad = 4;
      var rect = menuEl.getBoundingClientRect();
      var left = Math.min(clientX, window.innerWidth - rect.width - pad);
      var top = Math.min(clientY, window.innerHeight - rect.height - pad);
      menuEl.style.left = Math.max(pad, left) + "px";
      menuEl.style.top = Math.max(pad, top) + "px";
    }

    function onContextTrack(ev) {
      var header = ev.target.closest && ev.target.closest(".nle-header");
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      var el = header || lane;
      if (!el || !el.dataset.trackId) return;
      if (ev.target.closest && ev.target.closest(".nle-clip")) return;
      ev.preventDefault();
      showTrackMenu(ev.clientX, ev.clientY, el.dataset.trackId);
    }

    dom.headersCol.addEventListener("contextmenu", onContextTrack);
    dom.lanes.addEventListener("contextmenu", onContextTrack);

    document.addEventListener("pointerdown", function (ev) {
      if (menuEl && !menuEl.contains(ev.target)) dismissMenu();
    });
    window.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") dismissMenu();
    });
    window.addEventListener("resize", function () {
      dismissMenu();
      R.renderAll(dom, state);
    });

    dom.playBtn.addEventListener("click", function () {
      state.playing = !state.playing;
      if (state.playing) {
        preview.startClock(state, function () {
          R.renderPlayhead(dom, state);
          R.followPlayhead(dom, state);
          preview.sync(state);
        });
      }
      M.emit(state);
    });

    dom.toStartBtn.addEventListener("click", function () {
      state.playing = false;
      M.setPlayhead(state, 0, { force: true });
    });

    dom.splitBtn.addEventListener("click", function () {
      M.splitAtPlayhead(state);
    });

    dom.zoomInBtn.addEventListener("click", function () {
      M.setPxPerSec(state, state.pxPerSec * 1.25);
    });

    dom.zoomOutBtn.addEventListener("click", function () {
      M.setPxPerSec(state, state.pxPerSec / 1.25);
    });

    dom.snapBtn.addEventListener("click", function () {
      M.setSnap(state, !state.snap);
    });

    dom.scroll.addEventListener(
      "wheel",
      function (ev) {
        if (ev.ctrlKey || ev.metaKey) {
          ev.preventDefault();
          var factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
          M.setPxPerSec(state, state.pxPerSec * factor);
        }
      },
      { passive: false }
    );

    function scrubFromEvent(ev) {
      var t = R.xToTime(dom, state, ev.clientX);
      M.setPlayhead(state, t, { kind: "playhead" });
    }

    var scrubbingRuler = false;
    dom.ruler.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      scrubbingRuler = true;
      state.playing = false;
      preview.setScrubbing(true);
      dom.ruler.setPointerCapture(ev.pointerId);
      scrubFromEvent(ev);
      ev.preventDefault();
    });
    dom.ruler.addEventListener("pointermove", function (ev) {
      if (!scrubbingRuler) return;
      scrubFromEvent(ev);
    });
    function endRulerScrub(ev) {
      if (!scrubbingRuler) return;
      scrubbingRuler = false;
      preview.setScrubbing(false);
      try {
        dom.ruler.releasePointerCapture(ev.pointerId);
      } catch (_) {}
    }
    dom.ruler.addEventListener("pointerup", endRulerScrub);
    dom.ruler.addEventListener("pointercancel", endRulerScrub);

    var playheadDrag = false;
    dom.playhead.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      playheadDrag = true;
      state.playing = false;
      preview.setScrubbing(true);
      dom.playhead.setPointerCapture(ev.pointerId);
      scrubFromEvent(ev);
      ev.preventDefault();
      ev.stopPropagation();
    });
    dom.playhead.addEventListener("pointermove", function (ev) {
      if (!playheadDrag) return;
      scrubFromEvent(ev);
    });
    function endPlayhead(ev) {
      if (!playheadDrag) return;
      playheadDrag = false;
      preview.setScrubbing(false);
      try {
        dom.playhead.releasePointerCapture(ev.pointerId);
      } catch (_) {}
    }
    dom.playhead.addEventListener("pointerup", endPlayhead);
    dom.playhead.addEventListener("pointercancel", endPlayhead);

    var drag = null;

    dom.lanes.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      var target = ev.target;
      if (!target) return;

      var handle = target.closest && target.closest(".nle-clip__handle");
      var clipEl = target.closest && target.closest(".nle-clip");
      var lane = target.closest && target.closest(".nle-lane");

      if (handle && clipEl) {
        var clip = M.findClip(state, clipEl.dataset.clipId);
        if (!clip) return;
        var track = M.findTrack(state, clip.trackId);
        if (track && track.locked) return;
        M.selectClip(state, clip.id);
        M.pushUndo(state);
        drag = {
          mode: "trim",
          edge: handle.dataset.edge,
          clipId: clip.id,
          pointerId: ev.pointerId,
        };
        preview.setScrubbing(true);
        state.playing = false;
        clipEl.setPointerCapture(ev.pointerId);
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }

      if (clipEl) {
        var c = M.findClip(state, clipEl.dataset.clipId);
        if (!c) return;
        var tr = M.findTrack(state, c.trackId);
        if (tr && tr.locked) return;
        M.selectClip(state, c.id);
        M.pushUndo(state);
        drag = {
          mode: "move",
          clipId: c.id,
          offsetX: R.xToTime(dom, state, ev.clientX) - c.start,
          pointerId: ev.pointerId,
          startY: ev.clientY,
        };
        preview.setScrubbing(true);
        state.playing = false;
        clipEl.setPointerCapture(ev.pointerId);
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }

      if (lane) {
        M.selectClip(state, null);
        state.playing = false;
        M.setPlayhead(state, R.xToTime(dom, state, ev.clientX));
      }
    });

    dom.lanes.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      var clip = M.findClip(state, drag.clipId);
      if (!clip) return;

      if (drag.mode === "move") {
        var rawStart = R.xToTime(dom, state, ev.clientX) - drag.offsetX;
        var snapped = M.snapTime(state, rawStart, clip.id);
        if (state.snap) {
          var endSnap = M.snapTime(state, rawStart + clip.duration, clip.id) - clip.duration;
          if (Math.abs(endSnap - rawStart) < Math.abs(snapped - rawStart)) snapped = endSnap;
        }
        var trackId = clip.trackId;
        var laneEl = document.elementFromPoint(ev.clientX, ev.clientY);
        var lane = laneEl && laneEl.closest && laneEl.closest(".nle-lane");
        if (lane && lane.dataset.trackId) trackId = lane.dataset.trackId;
        var trackChanged = trackId !== clip.trackId;
        M.moveClip(state, clip.id, Math.max(0, snapped), trackId, false, {
          silent: true,
        });
        patchClipEl(clip);
        preview.sync(state);
      } else if (drag.mode === "trim") {
        var t = R.xToTime(dom, state, ev.clientX);
        t = M.snapTime(state, t, clip.id);
        M.trimClip(state, clip.id, drag.edge, t, false, { silent: true });
        patchClipEl(clip);
        preview.sync(state);
      }
    });

    function endDrag(ev) {
      if (!drag) return;
      var clipEl = dom.lanes.querySelector('[data-clip-id="' + drag.clipId + '"]');
      try {
        if (clipEl) clipEl.releasePointerCapture(drag.pointerId);
      } catch (_) {}
      var moved = M.findClip(state, drag.clipId);
      drag = null;
      preview.setScrubbing(false);
      // Full render after drag (track moves / width / undo snapshot already taken)
      M.emit(state, "full");
      if (moved) patchClipEl(moved);
    }
    dom.lanes.addEventListener("pointerup", endDrag);
    dom.lanes.addEventListener("pointercancel", endDrag);

    // Sync header column vertical scroll with lane scroll
    dom.scroll.addEventListener("scroll", function () {
      var rows = dom.headersCol.querySelectorAll(".nle-header");
      for (var i = 0; i < rows.length; i++) {
        rows[i].style.transform = "translateY(" + -dom.scroll.scrollTop + "px)";
      }
    });

    // Drag-drop files onto lanes
    dom.lanes.addEventListener("dragover", function (ev) {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "copy";
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      if (lane) lane.classList.add("is-drop");
    });
    dom.lanes.addEventListener("dragleave", function (ev) {
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      if (lane) lane.classList.remove("is-drop");
    });
    dom.lanes.addEventListener("drop", function (ev) {
      ev.preventDefault();
      var lane = ev.target.closest && ev.target.closest(".nle-lane");
      dom.lanes.querySelectorAll(".is-drop").forEach(function (el) {
        el.classList.remove("is-drop");
      });
      if (!lane) return;
      var trackId = lane.dataset.trackId;
      var at = R.xToTime(dom, state, ev.clientX);
      var files = ev.dataTransfer && ev.dataTransfer.files;
      if (files && files.length) {
        M.addClipsFromFiles(state, trackId, files, at);
      }
    });

    // Also allow drop on empty state / body to create track
    dom.root.addEventListener("dragover", function (ev) {
      if (ev.dataTransfer && ev.dataTransfer.types.indexOf("Files") >= 0) {
        ev.preventDefault();
      }
    });
    dom.root.addEventListener("drop", function (ev) {
      if (!ev.dataTransfer || !ev.dataTransfer.files || !ev.dataTransfer.files.length) return;
      if (ev.target.closest && ev.target.closest(".nle-lane")) return;
      ev.preventDefault();
      if (!state.tracks.length) M.addTrack(state);
      var trackId = state.tracks[state.tracks.length - 1].id;
      M.addClipsFromFiles(state, trackId, ev.dataTransfer.files, state.playhead);
    });

    window.addEventListener("keydown", function (ev) {
      var tag = (ev.target && ev.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      if (ev.code === "Space") {
        ev.preventDefault();
        state.playing = !state.playing;
        if (state.playing) {
          preview.startClock(state, function () {
            R.renderPlayhead(dom, state);
            R.followPlayhead(dom, state);
            preview.sync(state);
          });
        }
        M.emit(state);
        return;
      }
      if (ev.key === "Delete" || ev.key === "Backspace") {
        if (M.deleteSelection(state)) ev.preventDefault();
        return;
      }
      if (ev.key === "s" || ev.key === "S") {
        if (!ev.ctrlKey && !ev.metaKey) {
          if (M.splitAtPlayhead(state)) ev.preventDefault();
        }
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") {
        ev.preventDefault();
        if (ev.shiftKey) M.redo(state);
        else M.undo(state);
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") {
        ev.preventDefault();
        M.redo(state);
      }
    });

    preview.startClock(state, function () {
      R.renderPlayhead(dom, state);
      R.followPlayhead(dom, state);
      preview.sync(state);
    });

    refresh();
  }

  global.TimelineInteract = {
    bindInteractions: bindInteractions,
  };
})(window);
