(function (global) {
  "use strict";

  var VOICE_RATE = 16000;
  var VOICE_CHUNK_MS = 160;
  var VOICE_DEBOUNCE_MS = 500;
  var STOP_FALLBACK_MS = 800;
  var RR_ASSET_VERSION = "rr9";

  function ensureCss() {
    var href =
      "/reference-assets/record_reference.css?v=" + RR_ASSET_VERSION;
    var existing = document.querySelector('link[data-rr-css="1"]');
    if (existing) {
      if (existing.getAttribute("href") !== href) existing.href = href;
      return;
    }
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.rrCss = "1";
    document.head.appendChild(link);
  }

  function pickMime() {
    var types = [
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm",
    ];
    for (var i = 0; i < types.length; i++) {
      if (
        global.MediaRecorder &&
        MediaRecorder.isTypeSupported &&
        MediaRecorder.isTypeSupported(types[i])
      ) {
        return types[i];
      }
    }
    return "";
  }

  function downsampleTo16k(float32, fromRate) {
    if (fromRate === VOICE_RATE) {
      var out = new Int16Array(float32.length);
      for (var i = 0; i < float32.length; i++) {
        var s = Math.max(-1, Math.min(1, float32[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      return out;
    }
    var ratio = fromRate / VOICE_RATE;
    var newLen = Math.max(1, Math.floor(float32.length / ratio));
    var pcm = new Int16Array(newLen);
    for (var j = 0; j < newLen; j++) {
      var idx = Math.floor(j * ratio);
      var v = Math.max(-1, Math.min(1, float32[idx] || 0));
      pcm[j] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    return pcm;
  }

  function formatClock(sec) {
    sec = Math.max(0, sec || 0);
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    var cs = Math.floor((sec % 1) * 100);
    function pad(n, w) {
      var t = String(n);
      while (t.length < (w || 2)) t = "0" + t;
      return t;
    }
    return pad(m) + ":" + pad(s) + "." + pad(cs);
  }

  function openRecordReferenceModal(opts) {
    opts = opts || {};
    ensureCss();
    var UI = global.PhotorealUI;

    var existing = document.querySelector(".rr-modal-backdrop");
    if (existing) existing.remove();

    var state = "camera_ready";
    var aspect = "16:9";
    var stream = null;
    var recorder = null;
    var recordMime = "";
    var chunks = [];
    var reviewUrl = null;
    var reviewBlob = null;
    var audioCtx = null;
    var processor = null;
    var voiceSource = null;
    var analyser = null;
    var muteGain = null;
    var voiceArmed = false;
    var voiceExpect = null;
    var voiceBusy = false;
    var lastVoiceCmdAt = 0;
    var pcmBuf = [];
    var pcmSamples = 0;
    var destroyed = false;
    var stopFallbackTimer = null;
    var finishingStop = false;
    var enteredReview = false;
    var waveRaf = 0;
    var waveData = null;

    var backdrop = document.createElement("div");
    backdrop.className = "rr-modal-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-label", "Record Reference");

    var modal = document.createElement("div");
    modal.className = "rr-modal";

    var bar = document.createElement("div");
    bar.className = "rr-modal__bar";
    var title = document.createElement("h1");
    title.className = "rr-modal__title";
    title.textContent = "Record Reference";
    var closeBtn = UI.createButton({ label: "Close", onClick: close });
    bar.appendChild(title);
    bar.appendChild(closeBtn);

    var body = document.createElement("div");
    body.className = "rr-modal__body rr-body";
    body.dataset.state = state;

    var stage = document.createElement("div");
    stage.className = "rr-stage";
    stage.dataset.mode = "live";
    stage.dataset.aspect = aspect;

    var aspectBar = document.createElement("div");
    aspectBar.className = "rr-aspect";
    aspectBar.setAttribute("role", "group");
    aspectBar.setAttribute("aria-label", "Preview aspect ratio");
    var aspectBtns = {};
    ["16:9", "9:16", "1:1"].forEach(function (ratio) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "rr-aspect__btn";
      b.textContent = ratio;
      b.setAttribute("aria-pressed", ratio === aspect ? "true" : "false");
      b.addEventListener("click", function () {
        setAspect(ratio);
      });
      aspectBtns[ratio] = b;
      aspectBar.appendChild(b);
    });

    var video = document.createElement("video");
    video.playsInline = true;
    video.muted = true;
    video.autoplay = true;

    var recBadge = document.createElement("div");
    recBadge.className = "rr-stage__rec";
    recBadge.innerHTML =
      '<span class="rr-stage__rec-dot" aria-hidden="true"></span><span>Rec</span>';

    var waveCanvas = document.createElement("canvas");
    waveCanvas.className = "rr-wave";
    waveCanvas.width = 320;
    waveCanvas.height = 36;
    waveCanvas.setAttribute("aria-hidden", "true");

    stage.appendChild(video);
    stage.appendChild(aspectBar);
    stage.appendChild(recBadge);
    stage.appendChild(waveCanvas);

    var statusEl = document.createElement("div");
    statusEl.className = "rr-status";
    statusEl.textContent = "Starting camera…";

    var stopMark = 0;
    function rrLog() {
      /* debug panel removed */
    }

    var controls = document.createElement("div");
    controls.className = "rr-controls";
    var startBtn = UI.createButton({ label: "Start", onClick: onStartClick });
    var stopBtn = UI.createButton({ label: "Stop", onClick: onStopClick });
    var rerecordBtn = UI.createButton({
      label: "Rerecord",
      onClick: onRerecordClick,
    });
    var saveBtn = UI.createButton({ label: "Save", onClick: onSaveClick });
    controls.appendChild(startBtn);
    controls.appendChild(stopBtn);
    controls.appendChild(rerecordBtn);
    controls.appendChild(saveBtn);

    var review = document.createElement("div");
    review.className = "rr-review";

    var trimBar = document.createElement("div");
    trimBar.className = "rr-trim";
    trimBar.setAttribute("role", "group");
    trimBar.setAttribute("aria-label", "Trim and scrub");
    var trimTrack = document.createElement("div");
    trimTrack.className = "rr-trim__track";
    var trimRange = document.createElement("div");
    trimRange.className = "rr-trim__range";
    var trimInHandle = document.createElement("button");
    trimInHandle.type = "button";
    trimInHandle.className = "rr-trim__handle rr-trim__handle--in";
    trimInHandle.textContent = "|";
    trimInHandle.setAttribute("aria-label", "Trim in");
    var trimOutHandle = document.createElement("button");
    trimOutHandle.type = "button";
    trimOutHandle.className = "rr-trim__handle rr-trim__handle--out";
    trimOutHandle.textContent = "|";
    trimOutHandle.setAttribute("aria-label", "Trim out");
    var trimPlayhead = document.createElement("div");
    trimPlayhead.className = "rr-trim__playhead";
    trimPlayhead.setAttribute("aria-hidden", "true");
    trimTrack.appendChild(trimRange);
    trimTrack.appendChild(trimInHandle);
    trimTrack.appendChild(trimOutHandle);
    trimTrack.appendChild(trimPlayhead);
    trimBar.appendChild(trimTrack);

    var transport = document.createElement("div");
    transport.className = "rr-transport";
    var toStartBtn = UI.createButton({
      label: "|<",
      onClick: function () {
        try {
          video.currentTime = trimIn;
        } catch (_) {}
        updateReviewUi();
      },
    });
    toStartBtn.setAttribute("aria-label", "Go to start");
    var playBtn = UI.createButton({ label: "▶", onClick: togglePlay });
    playBtn.setAttribute("aria-label", "Play");
    var timeEl = document.createElement("div");
    timeEl.className = "rr-time";
    timeEl.textContent = "0:00.00 / 0:00.00";
    transport.appendChild(toStartBtn);
    transport.appendChild(playBtn);
    transport.appendChild(timeEl);
    review.appendChild(trimBar);
    review.appendChild(transport);

    body.appendChild(stage);
    body.appendChild(review);
    body.appendChild(statusEl);
    body.appendChild(controls);
    modal.appendChild(bar);
    modal.appendChild(body);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    var sourceDur = 0;
    var trimIn = 0;
    var trimOut = 0;
    var MIN_TRIM = 0.1;

    function resetTrim(fullDur) {
      sourceDur = isFinite(fullDur) && fullDur > 0 ? fullDur : 0;
      trimIn = 0;
      trimOut = sourceDur > 0 ? sourceDur : 0;
      layoutTrim();
    }

    function layoutTrim() {
      if (!sourceDur || sourceDur <= 0) {
        trimRange.style.left = "0%";
        trimRange.style.width = "100%";
        trimInHandle.style.left = "0%";
        trimOutHandle.style.left = "100%";
        trimPlayhead.style.left = "0%";
        return;
      }
      var inPct = (trimIn / sourceDur) * 100;
      var outPct = (trimOut / sourceDur) * 100;
      var cur = video.currentTime || trimIn;
      if (cur < trimIn) cur = trimIn;
      if (cur > trimOut) cur = trimOut;
      var playPct = (cur / sourceDur) * 100;
      trimInHandle.style.left = inPct + "%";
      trimOutHandle.style.left = outPct + "%";
      trimRange.style.left = inPct + "%";
      trimRange.style.width = Math.max(0, outPct - inPct) + "%";
      trimPlayhead.style.left = playPct + "%";
    }

    function timeFromClientX(clientX) {
      var rect = trimTrack.getBoundingClientRect();
      if (rect.width <= 0 || sourceDur <= 0) return 0;
      var x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      return x * sourceDur;
    }

    function bindTrimDrag(handle, which) {
      handle.addEventListener("pointerdown", function (ev) {
        if (state !== "review") return;
        ev.preventDefault();
        ev.stopPropagation();
        handle.setPointerCapture(ev.pointerId);
        function onMove(e) {
          var t = timeFromClientX(e.clientX);
          if (which === "in") {
            trimIn = Math.max(0, Math.min(t, trimOut - MIN_TRIM));
          } else {
            trimOut = Math.min(
              sourceDur,
              Math.max(t, trimIn + MIN_TRIM)
            );
          }
          if (video.currentTime < trimIn) video.currentTime = trimIn;
          if (video.currentTime > trimOut) video.currentTime = trimOut;
          layoutTrim();
          updateReviewUi();
        }
        function onUp(e) {
          handle.releasePointerCapture(e.pointerId);
          handle.removeEventListener("pointermove", onMove);
          handle.removeEventListener("pointerup", onUp);
          handle.removeEventListener("pointercancel", onUp);
        }
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onUp);
        handle.addEventListener("pointercancel", onUp);
      });
    }
    bindTrimDrag(trimInHandle, "in");
    bindTrimDrag(trimOutHandle, "out");

    trimTrack.addEventListener("pointerdown", function (ev) {
      if (state !== "review") return;
      if (ev.target === trimInHandle || ev.target === trimOutHandle) return;
      ev.preventDefault();
      trimTrack.setPointerCapture(ev.pointerId);
      function scrubTo(e) {
        var t = timeFromClientX(e.clientX);
        t = Math.max(trimIn, Math.min(trimOut, t));
        try {
          video.currentTime = t;
        } catch (_) {}
        layoutTrim();
        updateReviewUi();
      }
      scrubTo(ev);
      function onMove(e) {
        scrubTo(e);
      }
      function onUp(e) {
        trimTrack.releasePointerCapture(e.pointerId);
        trimTrack.removeEventListener("pointermove", onMove);
        trimTrack.removeEventListener("pointerup", onUp);
        trimTrack.removeEventListener("pointercancel", onUp);
      }
      trimTrack.addEventListener("pointermove", onMove);
      trimTrack.addEventListener("pointerup", onUp);
      trimTrack.addEventListener("pointercancel", onUp);
    });

    function setAspect(ratio) {
      aspect = ratio;
      stage.dataset.aspect = ratio;
      Object.keys(aspectBtns).forEach(function (key) {
        aspectBtns[key].setAttribute(
          "aria-pressed",
          key === ratio ? "true" : "false"
        );
      });
    }

    function setStatus(text, isError) {
      statusEl.textContent = text || "";
      statusEl.dataset.error = isError ? "true" : "false";
    }

    function clearStopFallback() {
      if (stopFallbackTimer) {
        clearTimeout(stopFallbackTimer);
        stopFallbackTimer = null;
      }
    }

    function setUiState(next) {
      state = next;
      body.dataset.state = next;
      var live = next !== "review";
      if (next === "recording") {
        stage.dataset.mode = "recording";
      } else if (next === "stopping") {
        stage.dataset.mode = "stopping";
      } else if (next === "review") {
        stage.dataset.mode = "review";
      } else {
        stage.dataset.mode = "live";
      }
      startBtn.disabled = next !== "listening_start";
      stopBtn.disabled = next !== "recording";
      rerecordBtn.disabled = next !== "review";
      saveBtn.disabled = next !== "review";
      video.muted = live;
      video.controls = false;
      if (next === "listening_start") {
        if (!statusEl.dataset.error || statusEl.dataset.error === "false") {
          setStatus("Say “start” or press Start");
        }
        voiceExpect = "start";
        voiceArmed = true;
        startWaveLoop();
      } else if (next === "recording") {
        setStatus("Recording — say “stop” or press Stop");
        voiceExpect = "stop";
        voiceArmed = true;
        startWaveLoop();
      } else if (next === "stopping") {
        setStatus("Stopping… preparing preview");
        voiceExpect = null;
        voiceArmed = false;
        stopWaveLoop();
      } else if (next === "review") {
        setStatus("Review, then Save or Rerecord");
        voiceExpect = null;
        voiceArmed = false;
        finishingStop = false;
        stopWaveLoop();
      } else {
        setStatus("Preparing camera…");
        voiceExpect = null;
        voiceArmed = false;
        stopWaveLoop();
      }
    }

    function resumeAudioCtx() {
      if (!audioCtx) {
        if (stream) startVoiceTap();
        return Promise.resolve();
      }
      if (audioCtx.state === "closed") {
        startVoiceTap();
        return Promise.resolve();
      }
      if (audioCtx.state === "suspended") {
        return audioCtx.resume().catch(function () {});
      }
      return Promise.resolve();
    }

    function stopWaveLoop() {
      if (waveRaf) {
        cancelAnimationFrame(waveRaf);
        waveRaf = 0;
      }
    }

    function startWaveLoop() {
      stopWaveLoop();
      function draw() {
        waveRaf = requestAnimationFrame(draw);
        if (destroyed) return;
        var ctx2d = waveCanvas.getContext("2d");
        if (!ctx2d) return;
        var w = waveCanvas.width;
        var h = waveCanvas.height;
        ctx2d.clearRect(0, 0, w, h);
        ctx2d.fillStyle = "rgba(10,10,10,0.35)";
        ctx2d.fillRect(0, 0, w, h);

        var bars = 28;
        var gap = 2;
        var barW = (w - gap * (bars - 1)) / bars;
        var levels = new Array(bars);
        var i;
        for (i = 0; i < bars; i++) levels[i] = 0.08;

        if (analyser && waveData) {
          analyser.getByteTimeDomainData(waveData);
          var step = Math.max(1, Math.floor(waveData.length / bars));
          for (i = 0; i < bars; i++) {
            var peak = 0;
            var base = i * step;
            for (var j = 0; j < step && base + j < waveData.length; j++) {
              var v = Math.abs(waveData[base + j] - 128) / 128;
              if (v > peak) peak = v;
            }
            levels[i] = Math.max(0.08, Math.min(1, peak * 1.8));
          }
        }

        for (i = 0; i < bars; i++) {
          var bh = levels[i] * (h - 4);
          var x = i * (barW + gap);
          var y = (h - bh) / 2;
          ctx2d.fillStyle =
            levels[i] > 0.35
              ? "rgba(255,255,255,0.92)"
              : "rgba(255,255,255,0.55)";
          ctx2d.fillRect(x, y, Math.max(1, barW), bh);
        }
      }
      draw();
    }

    function teardownVoiceTap() {
      voiceArmed = false;
      stopWaveLoop();
      try {
        if (processor) {
          processor.onaudioprocess = null;
          processor.disconnect();
        }
      } catch (_) {}
      try {
        if (analyser) analyser.disconnect();
      } catch (_) {}
      try {
        if (muteGain) muteGain.disconnect();
      } catch (_) {}
      try {
        if (voiceSource) voiceSource.disconnect();
      } catch (_) {}
      processor = null;
      analyser = null;
      muteGain = null;
      voiceSource = null;
      waveData = null;
      pcmBuf = [];
      pcmSamples = 0;
      if (audioCtx) {
        try {
          audioCtx.close();
        } catch (_) {}
        audioCtx = null;
      }
    }

    function stopStream() {
      if (stream) {
        stream.getTracks().forEach(function (t) {
          try {
            t.stop();
          } catch (_) {}
        });
        stream = null;
      }
    }

    function revokeReview() {
      if (reviewUrl) {
        try {
          URL.revokeObjectURL(reviewUrl);
        } catch (_) {}
        reviewUrl = null;
      }
      reviewBlob = null;
    }

    function close() {
      if (destroyed) return;
      destroyed = true;
      clearStopFallback();
      finishingStop = false;
      try {
        if (recorder && recorder.state === "recording") recorder.stop();
      } catch (_) {}
      recorder = null;
      teardownVoiceTap();
      stopStream();
      revokeReview();
      try {
        fetch("/api/voice/command?reset=true", {
          method: "POST",
          body: new Uint8Array(0),
        }).catch(function () {});
      } catch (_) {}
      backdrop.remove();
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", layoutTrim);
    }

    function onKey(ev) {
      if (ev.key === "Escape") close();
    }
    window.addEventListener("keydown", onKey);
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop) close();
    });

    function flushPcm(force) {
      if (!voiceArmed || destroyed || voiceBusy) return;
      var need = Math.floor((VOICE_RATE * VOICE_CHUNK_MS) / 1000);
      if (!force && pcmSamples < need) return;
      if (!pcmSamples) return;
      var total = 0;
      for (var i = 0; i < pcmBuf.length; i++) total += pcmBuf[i].length;
      var merged = new Int16Array(total);
      var off = 0;
      for (var j = 0; j < pcmBuf.length; j++) {
        merged.set(pcmBuf[j], off);
        off += pcmBuf[j].length;
      }
      pcmBuf = [];
      pcmSamples = 0;
      voiceBusy = true;
      var expect = voiceExpect;
      fetch("/api/voice/command?sample_rate=" + VOICE_RATE, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: merged.buffer,
      })
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error(j.detail || r.statusText);
            return j;
          });
        })
        .then(function (j) {
          voiceBusy = false;
          if (destroyed || !voiceArmed) return;
          var heard = (j && j.text) || "";
          var cmd = j && j.command;
          if (
            heard &&
            (state === "listening_start" || state === "recording") &&
            (!statusEl.dataset.error || statusEl.dataset.error === "false")
          ) {
            var hint =
              expect === "start"
                ? "Listening for “start”"
                : "Listening for “stop”";
            setStatus(hint + (heard ? " — heard: " + heard : ""));
          }
          if (!cmd || cmd === "none" || cmd !== expect) return;
          var now = Date.now();
          if (now - lastVoiceCmdAt < VOICE_DEBOUNCE_MS) return;
          lastVoiceCmdAt = now;
          if (cmd === "start") {
            setStatus("Heard “start” — starting…");
            rrLog("voice command start text=" + heard);
            beginRecording();
          } else if (cmd === "stop") {
            rrLog("voice command stop text=" + heard);
            endRecording({ fromVoice: true });
          }
        })
        .catch(function (err) {
          voiceBusy = false;
          if (destroyed || !voiceArmed) return;
          var msg = (err && err.message) || "voice API error";
          if (state === "listening_start" || state === "recording") {
            setStatus(String(msg) + " — use Start / Stop buttons", true);
          }
        });
    }

    function startVoiceTap() {
      var keepArmed = voiceArmed;
      var keepExpect = voiceExpect;
      teardownVoiceTap();
      voiceArmed = keepArmed;
      voiceExpect = keepExpect;
      if (!stream) return;
      var AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) {
        setStatus("Voice unavailable — use Start / Stop buttons", false);
        return;
      }
      audioCtx = new AC();
      voiceSource = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.7;
      waveData = new Uint8Array(analyser.fftSize);

      var bufSize = 4096;
      processor = audioCtx.createScriptProcessor(bufSize, 1, 1);
      processor.onaudioprocess = function (ev) {
        if (!voiceArmed || destroyed) return;
        var input = ev.inputBuffer.getChannelData(0);
        var pcm = downsampleTo16k(input, audioCtx.sampleRate);
        pcmBuf.push(pcm);
        pcmSamples += pcm.length;
        flushPcm(false);
      };
      muteGain = audioCtx.createGain();
      muteGain.gain.value = 0;
      voiceSource.connect(analyser);
      analyser.connect(processor);
      processor.connect(muteGain);
      muteGain.connect(audioCtx.destination);

      if (audioCtx.state === "suspended") {
        audioCtx.resume().catch(function () {});
      }

      fetch("/api/voice/status")
        .then(function (r) {
          return r.json();
        })
        .then(function (st) {
          if (destroyed) return;
          if (!st.ready && state === "listening_start") {
            setStatus(
              (st.hint || "Local voice not ready") + " — use Start / Stop",
              false
            );
          }
        })
        .catch(function () {});

      if (state === "listening_start" || state === "recording") {
        startWaveLoop();
      }
    }

    function pauseVoiceGraphForStop() {
      // ScriptProcessor on the same mic stream can delay/hang MediaRecorder.stop().
      voiceArmed = false;
      voiceExpect = null;
      try {
        if (processor) {
          processor.onaudioprocess = null;
          processor.disconnect();
        }
      } catch (_) {}
      try {
        if (analyser) analyser.disconnect();
      } catch (_) {}
      try {
        if (muteGain) muteGain.disconnect();
      } catch (_) {}
      try {
        if (voiceSource) voiceSource.disconnect();
      } catch (_) {}
      processor = null;
      analyser = null;
      muteGain = null;
      voiceSource = null;
      waveData = null;
      stopWaveLoop();
    }

    function enterReviewFromChunks(mime, allowRetry) {
      clearStopFallback();
      if (destroyed || enteredReview) return;
      var type =
        mime ||
        (recorder && recorder.mimeType) ||
        recordMime ||
        "video/webm";
      var bytes = chunks.reduce(function (n, c) {
        return n + (c && c.size ? c.size : 0);
      }, 0);
      rrLog(
        "enterReview chunks=" +
          chunks.length +
          " bytes=" +
          bytes +
          " allowRetry=" +
          (allowRetry !== false)
      );
      // dataavailable can land after onstop — retry once before failing.
      if (!chunks.length || bytes === 0) {
        if (allowRetry !== false) {
          rrLog("no chunks yet — waiting 120ms for dataavailable");
          stopFallbackTimer = setTimeout(function () {
            enterReviewFromChunks(mime, false);
          }, 120);
          return;
        }
        finishingStop = false;
        setStatus("Recording produced no data — try Start again", true);
        rrLog("finalize failed: empty recording");
        recorder = null;
        if (stream) {
          video.srcObject = stream;
          video.muted = true;
          video.play().catch(function () {});
          startVoiceTap();
        }
        setUiState("listening_start");
        return;
      }

      try {
        var blob = new Blob(chunks, { type: type });
        // Only revoke the previous object URL — do NOT null the new blob.
        if (reviewUrl) {
          try {
            URL.revokeObjectURL(reviewUrl);
          } catch (_) {}
          reviewUrl = null;
        }
        reviewBlob = blob;
        reviewUrl = URL.createObjectURL(reviewBlob);
        chunks = [];
        enteredReview = true;
        finishingStop = false;
        rrLog("blob ready type=" + type + " size=" + reviewBlob.size);

        stage.dataset.mode = "review";
        try {
          video.pause();
        } catch (_) {}
        video.removeAttribute("src");
        video.srcObject = null;
        video.src = reviewUrl;
        video.muted = false;
        video.onloadedmetadata = function () {
          var d = video.duration;
          if (!isFinite(d) || d <= 0) {
            try {
              video.currentTime = 1e8;
            } catch (_) {}
          } else {
            resetTrim(d);
            try {
              video.currentTime = trimIn;
            } catch (_) {}
          }
          updateReviewUi();
          rrLog("review metadata ready duration=" + (video.duration || "?"));
        };
        video.onseeked = function () {
          if (state !== "review") return;
          if (
            (!sourceDur || sourceDur <= 0) &&
            isFinite(video.duration) &&
            video.duration > 0
          ) {
            resetTrim(video.duration);
            if (video.currentTime < trimIn || video.currentTime > trimOut) {
              try {
                video.currentTime = trimIn;
              } catch (_) {}
            }
          }
          layoutTrim();
        };
        video.onerror = function () {
          rrLog("review video element error");
          setStatus("Preview failed to load — try Rerecord", true);
        };
        video.ontimeupdate = function () {
          if (state !== "review") return;
          if (trimOut > 0 && video.currentTime >= trimOut - 0.04) {
            try {
              video.pause();
              video.currentTime = trimOut;
            } catch (_) {}
            playBtn.textContent = "▶";
            playBtn.setAttribute("aria-label", "Play");
          }
          updateReviewUi();
        };
        video.onended = function () {
          playBtn.textContent = "▶";
          playBtn.setAttribute("aria-label", "Play");
          try {
            video.currentTime = trimIn;
          } catch (_) {}
          updateReviewUi();
        };
        setUiState("review");
        try {
          var p = video.play();
          if (p && p.catch) p.catch(function () {});
        } catch (_) {}
        recorder = null;
        rrLog("review UI ready (playable preview)");
      } catch (err) {
        enteredReview = false;
        finishingStop = false;
        rrLog("enterReview threw: " + (err && err.message ? err.message : err));
        setStatus(
          "Preview failed: " + (err && err.message ? err.message : err),
          true
        );
        if (allowRetry !== false) {
          stopFallbackTimer = setTimeout(function () {
            enterReviewFromChunks(mime, false);
          }, 50);
          return;
        }
        recorder = null;
        if (stream) {
          video.srcObject = stream;
          video.muted = true;
          video.play().catch(function () {});
          startVoiceTap();
        }
        setUiState("listening_start");
      }
    }

    function beginRecording() {
      if (destroyed) return;
      if (state !== "listening_start") {
        setStatus("Not ready to record yet — wait for camera", true);
        return;
      }
      if (!stream) {
        setStatus("Camera not ready", true);
        return;
      }
      if (!global.MediaRecorder) {
        setStatus("MediaRecorder not supported in this browser", true);
        return;
      }
      enteredReview = false;
      finishingStop = false;
      clearStopFallback();
      chunks = [];
      recordMime = pickMime();
      try {
        recorder = recordMime
          ? new MediaRecorder(stream, { mimeType: recordMime })
          : new MediaRecorder(stream);
      } catch (e) {
        setStatus("Could not start recorder: " + (e.message || e), true);
        return;
      }
      recorder.ondataavailable = function (ev) {
        if (ev.data && ev.data.size) {
          chunks.push(ev.data);
          rrLog(
            "dataavailable size=" +
              ev.data.size +
              " finishing=" +
              finishingStop
          );
        }
      };
      recorder.onerror = function () {
        setStatus("Recorder error", true);
        finishingStop = false;
        clearStopFallback();
        rrLog("MediaRecorder error");
      };
      recorder.onstop = function () {
        rrLog(
          "MediaRecorder onstop chunks=" +
            chunks.length +
            " — scheduling review"
        );
        if (destroyed) return;
        // Defer so dataavailable (same turn) is applied first.
        setTimeout(function () {
          enterReviewFromChunks(
            (recorder && recorder.mimeType) || recordMime,
            true
          );
        }, 0);
      };
      try {
        // Light timeslice keeps encoder warm; final slice still arrives on stop.
        recorder.start(1000);
        rrLog(
          "MediaRecorder start mime=" +
            (recorder.mimeType || recordMime || "default")
        );
      } catch (e2) {
        setStatus("Could not start recorder: " + (e2.message || e2), true);
        recorder = null;
        return;
      }
      setUiState("recording");
      fetch("/api/voice/command?reset=true", {
        method: "POST",
        body: new Uint8Array(0),
      }).catch(function () {});
    }

    function endRecording(optsEnd) {
      optsEnd = optsEnd || {};
      if (destroyed) return;
      if (state === "stopping" || finishingStop) return;
      if (state !== "recording") {
        if (!optsEnd.fromVoice) {
          setStatus("Not recording", true);
        }
        return;
      }
      if (!recorder) {
        setStatus("No active recorder", true);
        setUiState("listening_start");
        return;
      }
      finishingStop = true;
      stopMark = performance.now();
      pauseVoiceGraphForStop();
      setUiState("stopping");
      rrLog(
        "stop begin via=" +
          (optsEnd.fromVoice ? "voice" : "button") +
          " recorder.state=" +
          recorder.state +
          " chunks=" +
          chunks.length
      );
      clearStopFallback();
      // Hard guarantee: always leave Stopping, even if onstop never fires.
      stopFallbackTimer = setTimeout(function () {
        if (destroyed || enteredReview) return;
        rrLog("stop fallback fired after " + STOP_FALLBACK_MS + "ms");
        enterReviewFromChunks(
          (recorder && recorder.mimeType) || recordMime,
          true
        );
      }, STOP_FALLBACK_MS);
      try {
        if (recorder.state === "recording" || recorder.state === "paused") {
          rrLog("calling MediaRecorder.stop()");
          recorder.stop();
          rrLog("MediaRecorder.stop() returned (onstop pending)");
        } else {
          rrLog("recorder not active state=" + recorder.state);
          enterReviewFromChunks(
            (recorder && recorder.mimeType) || recordMime,
            true
          );
        }
      } catch (e) {
        setStatus("Stop failed: " + (e.message || e), true);
        rrLog("stop threw: " + (e.message || e));
        enterReviewFromChunks(recordMime, true);
      }
    }

    function onStartClick() {
      setStatus("Starting…");
      resumeAudioCtx().then(function () {
        if (destroyed) return;
        beginRecording();
      });
    }

    function onStopClick() {
      resumeAudioCtx().then(function () {
        if (destroyed) return;
        endRecording();
      });
    }

    function onRerecordClick() {
      if (state !== "review") return;
      clearStopFallback();
      finishingStop = false;
      enteredReview = false;
      try {
        video.pause();
      } catch (_) {}
      revokeReview();
      video.removeAttribute("src");
      video.load();
      resetTrim(0);
      if (stream) {
        video.srcObject = stream;
        video.muted = true;
        video.play().catch(function () {});
      }
      startVoiceTap();
      resumeAudioCtx().then(function () {
        if (destroyed) return;
        setUiState("listening_start");
      });
      fetch("/api/voice/command?reset=true", {
        method: "POST",
        body: new Uint8Array(0),
      }).catch(function () {});
    }

    function onSaveClick() {
      if (state !== "review" || !reviewBlob) return;
      var blob = reviewBlob;
      var name =
        "reference_" +
        new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19) +
        ".webm";
      var full =
        sourceDur > 0
          ? sourceDur
          : isFinite(video.duration) && video.duration > 0
            ? video.duration
            : null;
      var inPt = trimIn;
      var outPt = trimOut > trimIn ? trimOut : full || trimIn + MIN_TRIM;
      var clipDur = Math.max(MIN_TRIM, outPt - inPt);
      var meta = {
        name: name,
        aspect: aspect,
        mirror: true,
        duration: clipDur,
        inPoint: inPt,
        sourceDuration: full || inPt + clipDur,
      };
      var cb = opts.onSave;
      if (typeof cb === "function") {
        try {
          cb(blob, meta);
        } catch (e) {
          global.alert("Save failed: " + (e.message || e));
        }
      }
      close();
    }

    function updateReviewUi() {
      var dur = sourceDur > 0 ? sourceDur : video.duration;
      if (!isFinite(dur)) dur = 0;
      var cur = video.currentTime || 0;
      var win = Math.max(0, trimOut - trimIn);
      timeEl.textContent =
        formatClock(Math.max(0, cur - trimIn)) +
        " / " +
        formatClock(win || dur);
      layoutTrim();
      playBtn.textContent = video.paused ? "▶" : "❚❚";
      playBtn.setAttribute("aria-label", video.paused ? "Play" : "Pause");
    }

    function togglePlay() {
      if (state !== "review") return;
      if (video.paused) {
        if (video.currentTime < trimIn || video.currentTime >= trimOut - 0.05) {
          try {
            video.currentTime = trimIn;
          } catch (_) {}
        }
        video.play().catch(function () {});
      } else {
        video.pause();
      }
      updateReviewUi();
    }

    window.addEventListener("resize", layoutTrim);

    setUiState("camera_ready");
    startBtn.disabled = true;
    stopBtn.disabled = true;
    rerecordBtn.disabled = true;
    saveBtn.disabled = true;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Camera API not available in this browser", true);
      return { close: close };
    }

    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: "user" },
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      })
      .then(function (s) {
        if (destroyed) {
          s.getTracks().forEach(function (t) {
            t.stop();
          });
          return;
        }
        stream = s;
        video.srcObject = stream;
        return video.play().catch(function () {});
      })
      .then(function () {
        if (destroyed) return;
        startVoiceTap();
        setUiState("listening_start");
      })
      .catch(function (e) {
        setStatus(
          "Camera/mic permission failed: " + (e.message || e),
          true
        );
      });

    return { close: close };
  }

  global.PhotorealRecordReference = {
    version: RR_ASSET_VERSION,
    openModal: openRecordReferenceModal,
  };
})(window);
