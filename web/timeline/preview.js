(function (global) {
  "use strict";

  function createPreview(previewEl) {
    previewEl.innerHTML = "";
    previewEl.classList.add("tl-preview--live");

    var placeholder = document.createElement("div");
    placeholder.className = "tl-preview__placeholder";
    placeholder.textContent = "Preview";

    var video = document.createElement("video");
    video.className = "tl-preview__video";
    video.playsInline = true;
    video.muted = false;
    video.preload = "auto";

    var img = document.createElement("img");
    img.className = "tl-preview__img";
    img.alt = "";

    previewEl.appendChild(placeholder);
    previewEl.appendChild(video);
    previewEl.appendChild(img);

    var audioPool = {};
    var lastPictureId = null;
    var scrubbing = false;
    var raf = 0;
    var lastTs = 0;
    var stateRef = null;
    var onTick = null;

    function showPlaceholder() {
      placeholder.hidden = false;
      video.hidden = true;
      img.hidden = true;
      try {
        video.pause();
      } catch (_) {}
      lastPictureId = null;
    }

    function stopAllAudio() {
      Object.keys(audioPool).forEach(function (id) {
        var a = audioPool[id];
        try {
          a.pause();
        } catch (_) {}
      });
    }

    function getAudio(clip) {
      var a = audioPool[clip.id];
      if (!a) {
        a = new Audio();
        a.preload = "auto";
        a.src = clip.src;
        audioPool[clip.id] = a;
      }
      return a;
    }

    function syncPicture(state, playing) {
      var M = global.TimelineModel;
      var clip = M.pictureClipAt(state, state.playhead);
      if (!clip) {
        showPlaceholder();
        return;
      }
      placeholder.hidden = true;
      var localT = state.playhead - clip.start + clip.inPoint;

      if (clip.mediaType === "image") {
        video.hidden = true;
        try {
          video.pause();
        } catch (_) {}
        img.hidden = false;
        if (img.src !== clip.src) img.src = clip.src;
        lastPictureId = clip.id;
        return;
      }

      img.hidden = true;
      video.hidden = false;
      if (lastPictureId !== clip.id || video.src !== clip.src) {
        video.src = clip.src;
        lastPictureId = clip.id;
      }
      if (Math.abs((video.currentTime || 0) - localT) > 0.12 || scrubbing || !playing) {
        try {
          if (Math.abs((video.currentTime || 0) - localT) > 0.04) {
            video.currentTime = Math.max(0, localT);
          }
        } catch (_) {}
      }
      if (playing) {
        var p = video.play();
        if (p && p.catch) p.catch(function () {});
      } else {
        try {
          video.pause();
        } catch (_) {}
      }
    }

    function syncAudio(state, playing) {
      var M = global.TimelineModel;
      var active = M.audioClipsAt(state, state.playhead);
      var activeIds = {};
      for (var i = 0; i < active.length; i++) {
        var clip = active[i];
        activeIds[clip.id] = true;
        var a = getAudio(clip);
        var localT = state.playhead - clip.start + clip.inPoint;
        if (Math.abs((a.currentTime || 0) - localT) > 0.12 || scrubbing || !playing) {
          try {
            a.currentTime = Math.max(0, localT);
          } catch (_) {}
        }
        if (playing && !scrubbing) {
          var p = a.play();
          if (p && p.catch) p.catch(function () {});
        } else {
          try {
            a.pause();
          } catch (_) {}
        }
      }
      Object.keys(audioPool).forEach(function (id) {
        if (!activeIds[id]) {
          try {
            audioPool[id].pause();
          } catch (_) {}
        }
      });
    }

    function sync(state) {
      stateRef = state;
      syncPicture(state, !!state.playing && !scrubbing);
      syncAudio(state, !!state.playing && !scrubbing);
    }

    function setScrubbing(on) {
      scrubbing = !!on;
      if (scrubbing) {
        try {
          video.pause();
        } catch (_) {}
        stopAllAudio();
      }
      if (stateRef) sync(stateRef);
    }

    function loop(ts) {
      raf = requestAnimationFrame(loop);
      if (!stateRef || !stateRef.playing) {
        lastTs = ts;
        return;
      }
      if (!lastTs) lastTs = ts;
      var dt = (ts - lastTs) / 1000;
      lastTs = ts;
      if (dt > 0.1) dt = 0.1;
      var M = global.TimelineModel;
      var next = stateRef.playhead + dt;
      var max = M.projectDuration(stateRef);
      if (next >= max) {
        stateRef.playing = false;
        M.setPlayhead(stateRef, max, { force: true, kind: "playhead" });
        lastTs = 0;
        return;
      }
      stateRef.playhead = next;
      if (onTick) onTick(stateRef);
    }

    function startClock(state, tickCb) {
      stateRef = state;
      onTick = tickCb;
      if (!raf) {
        lastTs = 0;
        raf = requestAnimationFrame(loop);
      }
    }

    function stopClock() {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      lastTs = 0;
      try {
        video.pause();
      } catch (_) {}
      stopAllAudio();
    }

    showPlaceholder();

    return {
      sync: sync,
      setScrubbing: setScrubbing,
      startClock: startClock,
      stopClock: stopClock,
      video: video,
      img: img,
    };
  }

  global.TimelinePreview = {
    createPreview: createPreview,
  };
})(window);
