(function (global) {
  "use strict";

  function mountCharacterStudio(root, opts) {
    opts = opts || {};
    var UI = global.PhotorealUI;
    var Gallery = global.CharacterGallery;

    root.classList.add("ch");
    root.innerHTML = "";

    var previewWrap = document.createElement("div");
    previewWrap.className = "ch-preview-wrap";
    previewWrap.setAttribute("aria-label", "Character preview");

    var stage = document.createElement("div");
    stage.className = "ch-preview-stage";

    var empty = document.createElement("div");
    empty.className = "ch-preview-empty";
    empty.textContent = "Preview";

    var img = document.createElement("img");
    img.className = "ch-preview-img";
    img.alt = "";
    img.decoding = "async";

    stage.appendChild(empty);
    stage.appendChild(img);
    previewWrap.appendChild(stage);

    var tools = document.createElement("div");
    tools.className = "ch-preview-tools";
    var zoomOut = UI.createButton({ label: "−" });
    zoomOut.setAttribute("aria-label", "Zoom out");
    var zoomIn = UI.createButton({ label: "+" });
    zoomIn.setAttribute("aria-label", "Zoom in");
    var zoomReset = UI.createButton({ label: "1:1" });
    zoomReset.setAttribute("aria-label", "Reset zoom");
    tools.appendChild(zoomOut);
    tools.appendChild(zoomIn);
    tools.appendChild(zoomReset);
    previewWrap.appendChild(tools);

    var promptWrap = document.createElement("div");
    promptWrap.className = "ch-prompt pr-field";
    var promptLabel = document.createElement("label");
    promptLabel.htmlFor = "ch-prompt";
    promptLabel.textContent = "Prompt";
    var promptInput = document.createElement("textarea");
    promptInput.id = "ch-prompt";
    promptInput.name = "prompt";
    promptInput.placeholder = "Describe the character…";
    promptInput.rows = 3;
    promptWrap.appendChild(promptLabel);
    promptWrap.appendChild(promptInput);

    var genRow = document.createElement("div");
    genRow.className = "ch-gen-row";
    var genBtn = UI.createButton({ label: "Generate" });
    var statusEl = document.createElement("div");
    statusEl.className = "ch-status";
    statusEl.textContent = "";
    genRow.appendChild(genBtn);
    genRow.appendChild(statusEl);

    var galleryLabel = document.createElement("h2");
    galleryLabel.className = "ch-gallery-label";
    galleryLabel.textContent = "Gallery";

    var galleryRoot = document.createElement("div");
    galleryRoot.className = "ch-gallery";

    root.appendChild(previewWrap);
    root.appendChild(promptWrap);
    root.appendChild(genRow);
    root.appendChild(galleryLabel);
    root.appendChild(galleryRoot);

    var zoom = 1;
    var panX = 0;
    var panY = 0;

    function applyTransform() {
      stage.style.transform =
        "translate(" + panX + "px," + panY + "px) scale(" + zoom + ")";
    }

    function setPreview(url) {
      if (!url) {
        img.removeAttribute("src");
        img.removeAttribute("data-url");
        previewWrap.dataset.hasImage = "false";
        zoom = 1;
        panX = 0;
        panY = 0;
        applyTransform();
        return;
      }
      previewWrap.dataset.hasImage = "true";
      img.dataset.url = url;
      img.onload = function () {
        previewWrap.dataset.hasImage = "true";
      };
      img.onerror = function () {
        img.removeAttribute("src");
        previewWrap.dataset.hasImage = "false";
      };
      img.src = url;
      zoom = 1;
      panX = 0;
      panY = 0;
      applyTransform();
    }

    // Empty state until an image is selected/generated
    setPreview(null);

    function setStatus(text, isError) {
      statusEl.textContent = text || "";
      statusEl.dataset.error = isError ? "true" : "false";
    }

    zoomIn.addEventListener("click", function () {
      zoom = Math.min(5, zoom * 1.2);
      applyTransform();
    });
    zoomOut.addEventListener("click", function () {
      zoom = Math.max(0.4, zoom / 1.2);
      applyTransform();
    });
    zoomReset.addEventListener("click", function () {
      zoom = 1;
      panX = 0;
      panY = 0;
      applyTransform();
    });

    previewWrap.addEventListener(
      "wheel",
      function (ev) {
        ev.preventDefault();
        var factor = ev.deltaY < 0 ? 1.08 : 1 / 1.08;
        zoom = Math.max(0.4, Math.min(5, zoom * factor));
        applyTransform();
      },
      { passive: false }
    );

    var panning = false;
    var panStart = null;
    previewWrap.addEventListener("pointerdown", function (ev) {
      if (ev.button != null && ev.button !== 0) return;
      if (ev.target.closest && ev.target.closest(".ch-preview-tools")) return;
      panning = true;
      previewWrap.dataset.panning = "true";
      panStart = { x: ev.clientX, y: ev.clientY, panX: panX, panY: panY };
      previewWrap.setPointerCapture(ev.pointerId);
    });
    previewWrap.addEventListener("pointermove", function (ev) {
      if (!panning || !panStart) return;
      panX = panStart.panX + (ev.clientX - panStart.x);
      panY = panStart.panY + (ev.clientY - panStart.y);
      applyTransform();
    });
    function endPan(ev) {
      if (!panning) return;
      panning = false;
      previewWrap.dataset.panning = "false";
      panStart = null;
      try {
        previewWrap.releasePointerCapture(ev.pointerId);
      } catch (_) {}
    }
    previewWrap.addEventListener("pointerup", endPan);
    previewWrap.addEventListener("pointercancel", endPan);

    var gallery = Gallery.mountGallery({
      root: galleryRoot,
      layout: Gallery.loadLayout(),
      onSelect: function (entry) {
        setPreview(entry.url);
      },
    });

    function refreshGallery() {
      return fetch("/api/character/gallery")
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          gallery.syncFromServer(data.items || []);
        })
        .catch(function () {});
    }

    refreshGallery();

    var pollTimer = null;
    var logUi = null;

    function stopPoll() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    }

    function isLogPinned(el) {
      return el.scrollHeight - el.scrollTop - el.clientHeight <= 48;
    }

    function hasSelectionIn(el) {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) return false;
      var node = sel.anchorNode;
      return !!(node && el.contains(node));
    }

    function openLogModal() {
      var existing = document.querySelector(".ch-log-backdrop");
      if (existing) existing.remove();

      var backdrop = document.createElement("div");
      backdrop.className = "ch-log-backdrop";
      backdrop.setAttribute("role", "dialog");
      backdrop.setAttribute("aria-modal", "true");
      backdrop.setAttribute("aria-label", "Generate logs");

      var panel = document.createElement("div");
      panel.className = "ch-log-modal";

      var bar = document.createElement("div");
      bar.className = "ch-log-modal__bar";
      var title = document.createElement("h2");
      title.className = "ch-log-modal__title";
      title.textContent = "Generate logs";
      var closeBtn = UI.createButton({ label: "Close" });
      closeBtn.disabled = true;
      closeBtn.setAttribute("aria-disabled", "true");
      bar.appendChild(title);
      bar.appendChild(closeBtn);

      var meta = document.createElement("div");
      meta.className = "ch-log-modal__meta";
      meta.textContent = "Running…";

      var pre = document.createElement("pre");
      pre.className = "ch-log";
      // Avoid aria-live re-announcing (and selection disruption) on each poll append.
      pre.setAttribute("tabindex", "0");

      panel.appendChild(bar);
      panel.appendChild(meta);
      panel.appendChild(pre);
      backdrop.appendChild(panel);
      document.body.appendChild(backdrop);

      var finished = false;
      var logCount = 0;

      function setFinished(ok, errMsg) {
        finished = true;
        closeBtn.disabled = false;
        closeBtn.removeAttribute("aria-disabled");
        meta.textContent = ok
          ? "Finished — you can close this window"
          : "Failed — you can close this window";
        if (errMsg) meta.textContent += ": " + errMsg;
      }

      function appendLogs(logs) {
        if (!logs || !logs.length) return;
        var selecting = hasSelectionIn(pre);
        var stick = !selecting && isLogPinned(pre);
        if (logs.length < logCount) {
          pre.textContent = "";
          logCount = 0;
        }
        // Append as text nodes — rewriting textContent clears the user's selection.
        for (var i = logCount; i < logs.length; i++) {
          pre.appendChild(document.createTextNode(logs[i] + "\n"));
        }
        logCount = logs.length;
        if (stick) pre.scrollTop = pre.scrollHeight;
      }

      function close() {
        if (!finished) return;
        backdrop.remove();
        window.removeEventListener("keydown", onKey);
        logUi = null;
      }

      closeBtn.addEventListener("click", close);

      function onKey(ev) {
        if (ev.key === "Escape") {
          if (finished) {
            close();
          } else {
            ev.preventDefault();
            ev.stopPropagation();
          }
        }
      }
      window.addEventListener("keydown", onKey, true);

      backdrop.addEventListener("click", function (ev) {
        if (ev.target === backdrop && finished) close();
      });

      return {
        appendLogs: appendLogs,
        setFinished: setFinished,
        setMeta: function (t) {
          if (!finished) meta.textContent = t;
        },
        close: close,
      };
    }

    function pollJob(jobId) {
      stopPoll();
      logUi = openLogModal();
      pollTimer = setInterval(function () {
        fetch("/api/character/jobs/" + jobId)
          .then(function (r) {
            return r.json();
          })
          .then(function (job) {
            if (logUi) logUi.appendLogs(job.logs || []);
            if (job.stage === "reprompt") {
              setStatus("Reprompting…");
              if (logUi) logUi.setMeta("Stage: reprompt");
            } else if (job.stage === "gen" || job.stage === "queued") {
              setStatus(job.stage === "queued" ? "Queued…" : "Generating…");
              if (logUi) logUi.setMeta("Stage: " + job.stage);
            }
            if (job.status === "done") {
              stopPoll();
              UI.setButtonBusy(genBtn, false);
              setStatus("Done");
              var images = job.images || [];
              gallery.addImages(images);
              if (images[0]) setPreview(images[0].url);
              refreshGallery();
              if (logUi) logUi.setFinished(true);
            } else if (job.status === "error") {
              stopPoll();
              UI.setButtonBusy(genBtn, false);
              setStatus(job.error || "Generate failed", true);
              if (logUi) logUi.setFinished(false, job.error || "error");
            }
          })
          .catch(function (e) {
            stopPoll();
            UI.setButtonBusy(genBtn, false);
            setStatus(String(e.message || e), true);
            if (logUi) logUi.setFinished(false, String(e.message || e));
          });
      }, 500);
    }

    genBtn.addEventListener("click", function () {
      var prompt = (promptInput.value || "").trim();
      if (!prompt) {
        setStatus("Enter a prompt", true);
        promptInput.focus();
        return;
      }
      UI.setButtonBusy(genBtn, true, "Generating…");
      setStatus("Starting…");
      fetch("/api/character/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt }),
      })
        .then(function (r) {
          return r.json().then(function (body) {
            if (!r.ok) {
              var detail = body && body.detail;
              var msg = "Generate failed (HTTP " + r.status + ")";
              if (typeof detail === "string") msg = detail;
              else if (Array.isArray(detail)) {
                msg = detail
                  .map(function (d) {
                    return d && d.msg ? d.msg : JSON.stringify(d);
                  })
                  .join("; ");
              }
              throw new Error(msg);
            }
            return body;
          });
        })
        .then(function (job) {
          setStatus("Reprompting…");
          pollJob(job.job_id);
        })
        .catch(function (e) {
          UI.setButtonBusy(genBtn, false);
          var msg = e.message || String(e);
          if (Array.isArray(e)) msg = JSON.stringify(e);
          setStatus(msg, true);
        });
    });

    return {
      setPreview: setPreview,
      destroy: function () {
        stopPoll();
      },
      focusPrompt: function () {
        promptInput.focus();
      },
    };
  }

  function openCharacterModal() {
    var existing = document.querySelector(".ch-modal-backdrop");
    if (existing) existing.remove();

    var backdrop = document.createElement("div");
    backdrop.className = "ch-modal-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-label", "Create Character");

    var modal = document.createElement("div");
    modal.className = "ch-modal";

    var bar = document.createElement("div");
    bar.className = "ch-modal__bar";
    var title = document.createElement("h1");
    title.className = "ch-modal__title";
    title.textContent = "Create Character";
    var closeBtn = global.PhotorealUI.createButton({
      label: "Close",
      onClick: close,
    });
    bar.appendChild(title);
    bar.appendChild(closeBtn);

    var body = document.createElement("div");
    body.className = "ch-modal__body";

    modal.appendChild(bar);
    modal.appendChild(body);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    // Ensure character CSS is loaded when opened from timeline
    ensureCharacterCss();

    var studio = mountCharacterStudio(body);
    studio.focusPrompt();

    function close() {
      studio.destroy();
      backdrop.remove();
      window.removeEventListener("keydown", onKey);
    }

    function onKey(ev) {
      if (ev.key === "Escape") close();
    }
    window.addEventListener("keydown", onKey);

    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop) close();
    });

    return { close: close, studio: studio };
  }

  function ensureCharacterCss() {
    if (document.querySelector('link[data-ch-css="1"]')) return;
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/character-assets/character.css?v=ch3";
    link.dataset.chCss = "1";
    document.head.appendChild(link);
  }

  global.PhotorealCharacter = {
    mount: mountCharacterStudio,
    openModal: openCharacterModal,
  };
})(window);
