(function (global) {
  "use strict";

  var IMAGE_DEFAULT_DURATION = 5;
  var MIN_CLIP_DURATION = 0.1;
  var PX_PER_SEC_MIN = 20;
  var PX_PER_SEC_MAX = 400;
  var SNAP_PX = 8;

  function uid(prefix) {
    return (prefix || "id") + "_" + Math.random().toString(36).slice(2, 10);
  }

  function cloneClip(c) {
    return {
      id: c.id,
      trackId: c.trackId,
      name: c.name,
      mediaType: c.mediaType,
      src: c.src,
      start: c.start,
      duration: c.duration,
      inPoint: c.inPoint,
      sourceDuration: c.sourceDuration,
    };
  }

  function cloneTrack(t) {
    return {
      id: t.id,
      name: t.name,
      locked: !!t.locked,
      hidden: !!t.hidden,
      height: t.height || 64,
    };
  }

  function snapshot(state) {
    return {
      tracks: state.tracks.map(cloneTrack),
      clips: state.clips.map(cloneClip),
      selection: state.selection
        ? { trackId: state.selection.trackId, clipId: state.selection.clipId }
        : null,
      playhead: state.playhead,
      pxPerSec: state.pxPerSec,
      snap: state.snap,
    };
  }

  function restore(state, snap) {
    state.tracks = snap.tracks.map(cloneTrack);
    state.clips = snap.clips.map(cloneClip);
    state.selection = snap.selection
      ? { trackId: snap.selection.trackId, clipId: snap.selection.clipId }
      : null;
    state.playhead = snap.playhead;
    state.pxPerSec = snap.pxPerSec;
    state.snap = snap.snap;
  }

  function createState() {
    return {
      fps: 30,
      pxPerSec: 80,
      playhead: 0,
      snap: true,
      playing: false,
      selection: null,
      tracks: [],
      clips: [],
      undoStack: [],
      redoStack: [],
      _listeners: [],
      _seq: 0,
    };
  }

  function onChange(state, fn) {
    state._listeners.push(fn);
  }

  function emit(state, kind) {
    state._seq += 1;
    state._emitKind = kind || "full";
    for (var i = 0; i < state._listeners.length; i++) {
      try {
        state._listeners[i](state);
      } catch (_) {}
    }
  }

  function pushUndo(state) {
    state.undoStack.push(snapshot(state));
    if (state.undoStack.length > 80) state.undoStack.shift();
    state.redoStack.length = 0;
  }

  function undo(state) {
    if (!state.undoStack.length) return false;
    state.redoStack.push(snapshot(state));
    restore(state, state.undoStack.pop());
    state.playing = false;
    emit(state);
    return true;
  }

  function redo(state) {
    if (!state.redoStack.length) return false;
    state.undoStack.push(snapshot(state));
    restore(state, state.redoStack.pop());
    state.playing = false;
    emit(state);
    return true;
  }

  function projectDuration(state) {
    var max = 10;
    for (var i = 0; i < state.clips.length; i++) {
      var end = state.clips[i].start + state.clips[i].duration;
      if (end > max) max = end;
    }
    return Math.max(max, state.playhead + 2);
  }

  function timelineWidth(state, viewportPx) {
    var labelPad = 120;
    var content = Math.ceil(projectDuration(state) * state.pxPerSec) + labelPad;
    var view = viewportPx != null ? Math.ceil(viewportPx) : 0;
    return Math.max(content, view, 400);
  }

  function findTrack(state, id) {
    for (var i = 0; i < state.tracks.length; i++) {
      if (state.tracks[i].id === id) return state.tracks[i];
    }
    return null;
  }

  function findClip(state, id) {
    for (var i = 0; i < state.clips.length; i++) {
      if (state.clips[i].id === id) return state.clips[i];
    }
    return null;
  }

  function clipsOnTrack(state, trackId) {
    return state.clips.filter(function (c) {
      return c.trackId === trackId;
    });
  }

  function addTrack(state) {
    pushUndo(state);
    var n = state.tracks.length + 1;
    var track = {
      id: uid("trk"),
      name: "Track " + n,
      locked: false,
      hidden: false,
      height: 64,
    };
    state.tracks.push(track);
    emit(state);
    return track;
  }

  function setPlayhead(state, t, opts) {
    var v = Math.max(0, t);
    if (state.playhead === v && !(opts && opts.force)) return;
    state.playhead = v;
    if (opts && opts.silent) return;
    emit(state, (opts && opts.kind) || "playhead");
  }

  function setPxPerSec(state, px, anchorTime) {
    var next = Math.max(PX_PER_SEC_MIN, Math.min(PX_PER_SEC_MAX, px));
    if (next === state.pxPerSec) return;
    state.pxPerSec = next;
    emit(state);
    return anchorTime;
  }

  function setSnap(state, on) {
    state.snap = !!on;
    emit(state);
  }

  function selectClip(state, clipId) {
    var clip = clipId ? findClip(state, clipId) : null;
    state.selection = clip ? { trackId: clip.trackId, clipId: clip.id } : null;
    emit(state);
  }

  function mediaTypeFromFile(file) {
    var t = (file.type || "").toLowerCase();
    if (t.indexOf("video/") === 0) return "video";
    if (t.indexOf("audio/") === 0) return "audio";
    if (t.indexOf("image/") === 0) return "image";
    var name = (file.name || "").toLowerCase();
    if (/\.(mp4|webm|mov|mkv|m4v)$/.test(name)) return "video";
    if (/\.(mp3|wav|ogg|m4a|aac|flac)$/.test(name)) return "audio";
    if (/\.(png|jpe?g|gif|webp|bmp|svg)$/.test(name)) return "image";
    return null;
  }

  function probeMediaDuration(file, mediaType) {
    return new Promise(function (resolve) {
      if (mediaType === "image") {
        resolve(IMAGE_DEFAULT_DURATION);
        return;
      }
      var url = URL.createObjectURL(file);
      var el = document.createElement(mediaType === "audio" ? "audio" : "video");
      el.preload = "metadata";
      var done = false;
      function finish(d) {
        if (done) return;
        done = true;
        URL.revokeObjectURL(url);
        resolve(Math.max(MIN_CLIP_DURATION, d || IMAGE_DEFAULT_DURATION));
      }
      el.onloadedmetadata = function () {
        finish(el.duration);
      };
      el.onerror = function () {
        finish(IMAGE_DEFAULT_DURATION);
      };
      setTimeout(function () {
        finish(el.duration || IMAGE_DEFAULT_DURATION);
      }, 4000);
      el.src = url;
    });
  }

  function addClipsFromFiles(state, trackId, files, atTime) {
    var track = findTrack(state, trackId);
    if (!track || track.locked) return Promise.resolve([]);

    var list = Array.prototype.slice.call(files || []);
    var jobs = [];
    for (var i = 0; i < list.length; i++) {
      var file = list[i];
      var mt = mediaTypeFromFile(file);
      if (!mt) continue;
      jobs.push(
        (function (f, mediaType) {
          return probeMediaDuration(f, mediaType).then(function (dur) {
            return {
              file: f,
              mediaType: mediaType,
              sourceDuration: dur,
              src: URL.createObjectURL(f),
              name: f.name || mediaType,
            };
          });
        })(file, mt)
      );
    }
    if (!jobs.length) return Promise.resolve([]);

    return Promise.all(jobs).then(function (items) {
      pushUndo(state);
      var t = Math.max(0, atTime == null ? state.playhead : atTime);
      var created = [];
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var clip = {
          id: uid("clip"),
          trackId: trackId,
          name: it.name,
          mediaType: it.mediaType,
          src: it.src,
          start: t,
          duration: it.sourceDuration,
          inPoint: 0,
          sourceDuration: it.sourceDuration,
        };
        state.clips.push(clip);
        created.push(clip);
        t += it.sourceDuration;
      }
      if (created.length) {
        state.selection = {
          trackId: created[created.length - 1].trackId,
          clipId: created[created.length - 1].id,
        };
      }
      emit(state);
      return created;
    });
  }

  function deleteSelection(state) {
    if (!state.selection) return false;
    var clip = findClip(state, state.selection.clipId);
    if (!clip) return false;
    var track = findTrack(state, clip.trackId);
    if (track && track.locked) return false;
    pushUndo(state);
    state.clips = state.clips.filter(function (c) {
      return c.id !== clip.id;
    });
    state.selection = null;
    emit(state);
    return true;
  }

  function snapTargets(state, excludeClipId) {
    var targets = [0, state.playhead];
    for (var i = 0; i < state.clips.length; i++) {
      var c = state.clips[i];
      if (c.id === excludeClipId) continue;
      targets.push(c.start);
      targets.push(c.start + c.duration);
    }
    return targets;
  }

  function snapTime(state, t, excludeClipId) {
    if (!state.snap) return t;
    var thresh = SNAP_PX / state.pxPerSec;
    var targets = snapTargets(state, excludeClipId);
    var best = t;
    var bestD = thresh;
    for (var i = 0; i < targets.length; i++) {
      var d = Math.abs(targets[i] - t);
      if (d <= bestD) {
        bestD = d;
        best = targets[i];
      }
    }
    return Math.max(0, best);
  }

  function moveClip(state, clipId, newStart, newTrackId, recordUndo, opts) {
    var clip = findClip(state, clipId);
    if (!clip) return false;
    var fromTrack = findTrack(state, clip.trackId);
    if (fromTrack && fromTrack.locked) return false;
    var trackId = newTrackId || clip.trackId;
    var toTrack = findTrack(state, trackId);
    if (!toTrack || toTrack.locked) return false;
    if (recordUndo) pushUndo(state);
    clip.start = Math.max(0, newStart);
    clip.trackId = trackId;
    if (state.selection && state.selection.clipId === clipId) {
      state.selection.trackId = trackId;
    }
    if (opts && opts.silent) return true;
    emit(state, (opts && opts.kind) || "full");
    return true;
  }

  function trimClip(state, clipId, edge, newTime, recordUndo, opts) {
    var clip = findClip(state, clipId);
    if (!clip) return false;
    var track = findTrack(state, clip.trackId);
    if (track && track.locked) return false;
    if (recordUndo) pushUndo(state);

    var start = clip.start;
    var end = clip.start + clip.duration;
    var inPoint = clip.inPoint;
    var srcDur = clip.sourceDuration;

    if (edge === "left") {
      var maxStart = end - MIN_CLIP_DURATION;
      var minStart = start - inPoint;
      var ns = Math.max(minStart, Math.min(maxStart, newTime));
      var delta = ns - start;
      clip.start = ns;
      clip.inPoint = inPoint + delta;
      clip.duration = end - ns;
    } else {
      var maxEnd = start + (srcDur - inPoint);
      var minEnd = start + MIN_CLIP_DURATION;
      var ne = Math.max(minEnd, Math.min(maxEnd, newTime));
      clip.duration = ne - start;
    }
    if (opts && opts.silent) return true;
    emit(state, (opts && opts.kind) || "full");
    return true;
  }

  function splitAtPlayhead(state) {
    if (!state.selection) return false;
    var clip = findClip(state, state.selection.clipId);
    if (!clip) return false;
    var track = findTrack(state, clip.trackId);
    if (track && track.locked) return false;
    var t = state.playhead;
    if (t <= clip.start + MIN_CLIP_DURATION || t >= clip.start + clip.duration - MIN_CLIP_DURATION) {
      return false;
    }
    pushUndo(state);
    var leftDur = t - clip.start;
    var rightDur = clip.duration - leftDur;
    var right = cloneClip(clip);
    right.id = uid("clip");
    right.start = t;
    right.duration = rightDur;
    right.inPoint = clip.inPoint + leftDur;
    clip.duration = leftDur;
    state.clips.push(right);
    state.selection = { trackId: right.trackId, clipId: right.id };
    emit(state);
    return true;
  }

  function toggleLock(state, trackId) {
    var track = findTrack(state, trackId);
    if (!track) return;
    track.locked = !track.locked;
    emit(state);
  }

  function toggleHidden(state, trackId) {
    var track = findTrack(state, trackId);
    if (!track) return;
    pushUndo(state);
    track.hidden = !track.hidden;
    emit(state);
  }

  function deleteTrack(state, trackId) {
    var track = findTrack(state, trackId);
    if (!track) return false;
    pushUndo(state);
    state.tracks = state.tracks.filter(function (t) {
      return t.id !== trackId;
    });
    state.clips = state.clips.filter(function (c) {
      return c.trackId !== trackId;
    });
    if (state.selection && state.selection.trackId === trackId) {
      state.selection = null;
    }
    emit(state);
    return true;
  }

  function pictureClipAt(state, t) {
    for (var i = 0; i < state.tracks.length; i++) {
      var track = state.tracks[i];
      if (track.hidden) continue;
      var on = clipsOnTrack(state, track.id);
      for (var j = 0; j < on.length; j++) {
        var c = on[j];
        if (c.mediaType === "audio") continue;
        if (t >= c.start && t < c.start + c.duration) return c;
      }
    }
    return null;
  }

  function audioClipsAt(state, t) {
    var out = [];
    for (var i = 0; i < state.clips.length; i++) {
      var c = state.clips[i];
      if (c.mediaType !== "audio") continue;
      var track = findTrack(state, c.trackId);
      if (track && track.hidden) continue;
      if (t >= c.start && t < c.start + c.duration) out.push(c);
    }
    return out;
  }

  function formatTime(sec, fps) {
    fps = fps || 30;
    var s = Math.max(0, sec);
    var totalFrames = Math.round(s * fps);
    var frames = totalFrames % fps;
    var totalSec = Math.floor(totalFrames / fps);
    var ss = totalSec % 60;
    var mm = Math.floor(totalSec / 60) % 60;
    var hh = Math.floor(totalSec / 3600);
    function pad(n, w) {
      var str = String(n);
      while (str.length < (w || 2)) str = "0" + str;
      return str;
    }
    if (hh > 0) return pad(hh) + ":" + pad(mm) + ":" + pad(ss) + "." + pad(frames);
    return pad(mm) + ":" + pad(ss) + "." + pad(frames);
  }

  global.TimelineModel = {
    IMAGE_DEFAULT_DURATION: IMAGE_DEFAULT_DURATION,
    MIN_CLIP_DURATION: MIN_CLIP_DURATION,
    PX_PER_SEC_MIN: PX_PER_SEC_MIN,
    PX_PER_SEC_MAX: PX_PER_SEC_MAX,
    createState: createState,
    onChange: onChange,
    emit: emit,
    undo: undo,
    redo: redo,
    projectDuration: projectDuration,
    timelineWidth: timelineWidth,
    findTrack: findTrack,
    findClip: findClip,
    clipsOnTrack: clipsOnTrack,
    addTrack: addTrack,
    setPlayhead: setPlayhead,
    setPxPerSec: setPxPerSec,
    setSnap: setSnap,
    selectClip: selectClip,
    mediaTypeFromFile: mediaTypeFromFile,
    addClipsFromFiles: addClipsFromFiles,
    deleteSelection: deleteSelection,
    snapTime: snapTime,
    moveClip: moveClip,
    trimClip: trimClip,
    splitAtPlayhead: splitAtPlayhead,
    toggleLock: toggleLock,
    toggleHidden: toggleHidden,
    deleteTrack: deleteTrack,
    pictureClipAt: pictureClipAt,
    audioClipsAt: audioClipsAt,
    formatTime: formatTime,
    pushUndo: pushUndo,
  };
})(window);
