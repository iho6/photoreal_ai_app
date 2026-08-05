/**
 * Blocking operation log modal for timeline pipeline jobs.
 * Close stays disabled until setFinished(); Escape only closes when finished.
 */
(function (global) {
  "use strict";

  function isLogPinned(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= 48;
  }

  function hasSelectionIn(el) {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return false;
    var node = sel.anchorNode;
    return !!(node && el.contains(node));
  }

  /**
   * @param {{ title?: string }} [opts]
   */
  function open(opts) {
    opts = opts || {};
    var titleText = opts.title || "Operation logs";

    var existing = document.querySelector(".nle-op-log-backdrop");
    if (existing) existing.remove();

    var backdrop = document.createElement("div");
    backdrop.className = "nle-op-log-backdrop";
    backdrop.setAttribute("role", "dialog");
    backdrop.setAttribute("aria-modal", "true");
    backdrop.setAttribute("aria-label", titleText);

    var panel = document.createElement("div");
    panel.className = "nle-op-log-modal";

    var bar = document.createElement("div");
    bar.className = "nle-op-log-modal__bar";
    var title = document.createElement("h2");
    title.className = "nle-op-log-modal__title";
    title.textContent = titleText;
    var closeBtn =
      global.PhotorealUI && global.PhotorealUI.createButton
        ? global.PhotorealUI.createButton({ label: "Close" })
        : document.createElement("button");
    if (!closeBtn.textContent) closeBtn.textContent = "Close";
    closeBtn.disabled = true;
    closeBtn.setAttribute("aria-disabled", "true");
    bar.appendChild(title);
    bar.appendChild(closeBtn);

    var meta = document.createElement("div");
    meta.className = "nle-op-log-modal__meta";
    meta.textContent = "Running…";

    var pre = document.createElement("pre");
    pre.className = "nle-op-log";
    pre.setAttribute("tabindex", "0");

    panel.appendChild(bar);
    panel.appendChild(meta);
    panel.appendChild(pre);
    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);

    var finished = false;
    /** Index into the last job.logs array (client appendLine does not use this). */
    var serverLogCount = 0;

    function setMeta(text) {
      meta.textContent = text || "";
    }

    function setFinished(ok, errMsg) {
      finished = true;
      closeBtn.disabled = false;
      closeBtn.removeAttribute("aria-disabled");
      meta.textContent = ok
        ? "Finished — you can close this window"
        : "Failed — you can close this window";
      if (errMsg) meta.textContent += ": " + errMsg;
    }

    function stickScroll() {
      var selecting = hasSelectionIn(pre);
      var stick = !selecting && isLogPinned(pre);
      if (stick) pre.scrollTop = pre.scrollHeight;
    }

    function appendLogs(logs) {
      if (!logs || !logs.length) return;
      if (logs.length < serverLogCount) {
        serverLogCount = 0;
      }
      for (var i = serverLogCount; i < logs.length; i++) {
        pre.appendChild(document.createTextNode(logs[i] + "\n"));
      }
      serverLogCount = logs.length;
      stickScroll();
    }

    function appendLine(line) {
      if (line == null || line === "") return;
      pre.appendChild(document.createTextNode(String(line) + "\n"));
      stickScroll();
    }

    function close() {
      if (!finished) return;
      backdrop.remove();
      window.removeEventListener("keydown", onKey);
    }

    closeBtn.addEventListener("click", close);

    function onKey(ev) {
      if (ev.key === "Escape" && finished) {
        close();
      }
    }
    window.addEventListener("keydown", onKey);

    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop && finished) close();
    });

    return {
      appendLogs: appendLogs,
      appendLine: appendLine,
      setMeta: setMeta,
      setFinished: setFinished,
      close: close,
    };
  }

  /**
   * Sync job.logs / stage into an open modal.
   * Emits a compact client line when the job has a stage but no logs yet.
   * @returns {(job: object) => void}
   */
  function bindJobUpdates(logUi, label) {
    var lastStage = "";
    var emittedFallback = false;
    return function (job) {
      if (!job || !logUi) return;
      if (job.stage && job.stage !== lastStage) {
        lastStage = job.stage;
        logUi.setMeta("Stage: " + job.stage);
        if (!job.logs || !job.logs.length) {
          logUi.appendLine(
            "[" +
              (job.status || "running") +
              "] " +
              (label || "job") +
              " stage=" +
              job.stage
          );
          emittedFallback = true;
        }
      }
      if (job.logs && job.logs.length) {
        logUi.appendLogs(job.logs);
        emittedFallback = false;
      } else if (
        !emittedFallback &&
        job.status &&
        job.status !== "queued" &&
        !job.stage
      ) {
        logUi.appendLine("[" + job.status + "] " + (label || "job") + "…");
        emittedFallback = true;
      }
    };
  }

  global.TimelineOpLog = {
    open: open,
    bindJobUpdates: bindJobUpdates,
  };
})(typeof window !== "undefined" ? window : globalThis);
