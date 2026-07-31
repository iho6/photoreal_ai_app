(function () {
  "use strict";

  const UI = window.PhotorealUI;
  const app = document.getElementById("app");

  const form = document.createElement("div");

  const hf = UI.createField({
    label: "Hugging Face token",
    hideLabel: true,
    name: "hf_token",
    password: true,
    placeholder: "Hugging Face token",
    required: true,
  });
  const github = UI.createField({
    label: "GitHub token",
    hideLabel: true,
    name: "github_token",
    password: true,
    placeholder: "GitHub token",
  });
  const runpod = UI.createField({
    label: "Runpod API key",
    hideLabel: true,
    name: "runpod_api_key",
    password: true,
    placeholder: "Runpod API key",
    required: true,
  });

  [hf, github, runpod].forEach(function (f) {
    form.appendChild(f.root);
  });

  const row = document.createElement("div");
  row.className = "pr-btn-row";

  const statusEl = document.createElement("div");
  statusEl.className = "portal-status";
  statusEl.textContent = "Loading status…";

  const progress = document.createElement("div");
  progress.className = "pr-progress";
  progress.dataset.active = "false";

  const downloadBar = document.createElement("div");
  downloadBar.className = "pr-download-bar";
  downloadBar.dataset.visible = "false";
  downloadBar.dataset.indeterminate = "false";
  downloadBar.setAttribute("role", "progressbar");
  downloadBar.setAttribute("aria-valuemin", "0");
  downloadBar.setAttribute("aria-valuemax", "100");
  const downloadFill = document.createElement("div");
  downloadFill.className = "pr-download-bar__fill";
  downloadBar.appendChild(downloadFill);

  const downloadMeta = document.createElement("div");
  downloadMeta.className = "pr-download-meta";
  downloadMeta.dataset.visible = "false";

  const logEl = document.createElement("pre");
  logEl.className = "pr-log";
  logEl.setAttribute("aria-live", "polite");

  function collectCredentials() {
    return {
      hf_token: hf.input.value,
      github_token: github.input.value,
      runpod_api_key: runpod.input.value,
    };
  }

  function setStatus(html) {
    statusEl.innerHTML = html;
  }

  let saveTimer = null;
  let saving = false;

  async function autoSaveCredentials() {
    if (saving) return;
    const body = collectCredentials();
    // Nothing new typed (placeholders only / empty) — skip.
    const hfVal = (body.hf_token || "").trim();
    const ghVal = (body.github_token || "").trim();
    const rpVal = (body.runpod_api_key || "").trim();
    if (!hfVal && !ghVal && !rpVal) return;
    if (
      /^•+$/.test(hfVal) &&
      (!ghVal || /^•+$/.test(ghVal)) &&
      (!rpVal || /^•+$/.test(rpVal))
    )
      return;

    saving = true;
    try {
      const r = await fetch("/api/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json().catch(function () {
        return {};
      });
      if (!r.ok) throw new Error(data.detail || "Save failed");
      await refreshStatus();
    } catch (e) {
      setStatus("<strong>Error:</strong> " + (e.message || e));
    } finally {
      saving = false;
    }
  }

  function scheduleAutoSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      autoSaveCredentials();
    }, 600);
  }

  [hf, github, runpod].forEach(function (f) {
    f.input.addEventListener("input", function () {
      f.input.dataset.dirty = "1";
    });
    f.input.addEventListener("change", scheduleAutoSave);
    f.input.addEventListener("blur", scheduleAutoSave);
  });

  async function refreshStatus() {
    const r = await fetch("/api/status");
    const data = await r.json();
    const h = data.health || {};
    const apiOk = h.api && h.api.ok;
    const comfyOk = h.comfy && h.comfy.ok;
    const c = data.credentials || {};
    const cuda = h.torch_cuda === true;
    setStatus(
      "API <strong>" +
        (apiOk ? "up" : "down") +
        "</strong> · Comfy <strong>" +
        (comfyOk ? "up" : "down") +
        "</strong> · HF token <strong>" +
        (c.hf_token_set ? "saved" : "missing") +
        "</strong> · Runpod <strong>" +
        (c.runpod_token_set ? "saved" : "missing") +
        "</strong> · Flash <strong>" +
        (c.flash_character_endpoint ? "cached" : "auto") +
        "</strong>" +
        (cuda ? "" : " · <strong>CPU</strong> torch")
    );
    if (c.hf_token_set && c.hf_token && !hf.input.dataset.dirty) {
      hf.input.value = c.hf_token;
    }
    if (c.github_token_set && c.github_token && !github.input.dataset.dirty) {
      github.input.value = c.github_token;
    }
    if (c.runpod_token_set && c.runpod_api_key && !runpod.input.dataset.dirty) {
      runpod.input.value = c.runpod_api_key;
    }
    return data;
  }

  function setDownloadProgress(pct, label) {
    const hasPct = pct != null && !isNaN(pct);
    const barLine =
      label && String(label).indexOf("[") >= 0 && String(label).indexOf("%") >= 0
        ? String(label)
        : null;

    if (!hasPct && !barLine) {
      downloadBar.dataset.visible = "false";
      downloadBar.dataset.indeterminate = "false";
      downloadFill.style.width = "0%";
      downloadMeta.dataset.visible = "false";
      downloadMeta.textContent = "";
      return;
    }

    const clamped = hasPct ? Math.max(0, Math.min(100, pct)) : 0;
    downloadBar.dataset.visible = "true";
    downloadBar.dataset.indeterminate = "false";
    downloadFill.style.width = clamped + "%";
    downloadBar.setAttribute("aria-valuenow", String(Math.round(clamped)));
    downloadMeta.dataset.visible = "true";
    downloadMeta.innerHTML = "<strong>" + Math.round(clamped) + "%</strong>";

    if (barLine) {
      replaceLogProgress(barLine);
    } else if (hasPct) {
      replaceLogProgress(formatLocalBar(clamped, ""));
    }
  }

  function formatLocalBar(pct, label) {
    const width = 20;
    const filled = Math.max(0, Math.min(width, Math.round((width * pct) / 100)));
    const bar = "#".repeat(filled) + "-".repeat(width - filled);
    const pctText = pct.toFixed(1).padStart(5, " ") + "%";
    return label
      ? "  [" + bar + "] " + pctText + "  " + label
      : "  [" + bar + "] " + pctText;
  }

  function shortLabel(label) {
    const s = label.replace(/\s+/g, " ").trim();
    if (s.length <= 72) return s;
    return s.slice(0, 69) + "…";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function isLogPinnedToBottom() {
    const slack = 48;
    return logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight <= slack;
  }

  function replaceLogProgress(line) {
    const stick = isLogPinnedToBottom();
    let text = logEl.textContent;
    if (text.endsWith("\n")) text = text.slice(0, -1);
    const lines = text.split("\n");
    const isProg = function (s) {
      return /^\s*\[[#\-]+\]\s+\d/.test(s) || String(s).indexOf("@@PROGRESS@@") === 0;
    };
    // Keep exactly one progress line (drop any older ones).
    const kept = lines.filter(function (s) {
      return !isProg(s);
    });
    kept.push(line);
    logEl.textContent = kept.join("\n") + "\n";
    if (stick) logEl.scrollTop = logEl.scrollHeight;
  }

  function appendLog(line) {
    if (!line && line !== "") return;
    // Never dump raw progress markers into the log.
    if (String(line).indexOf("@@PROGRESS@@|") === 0) return;
    const stick = isLogPinnedToBottom();
    logEl.textContent += line + "\n";
    if (stick) logEl.scrollTop = logEl.scrollHeight;
  }

  let logSource = null;
  let logCursor = 0;
  let watching = false;

  function stopWatching() {
    watching = false;
    if (logSource) {
      try {
        logSource.close();
      } catch (_) {}
      logSource = null;
    }
  }

  function stopLoadingUI(failedMessage) {
    progress.dataset.active = "false";
    setDownloadProgress(null, null);
    UI.setButtonBusy(launchBtn, false);
    if (failedMessage) {
      setStatus("<strong>Launch failed:</strong> " + failedMessage);
    }
  }

  function watchLogs() {
    stopWatching();
    watching = true;
    logCursor = 0;
    progress.dataset.active = "true";
    setDownloadProgress(0, formatLocalBar(0, "starting…"));

    function connect() {
      if (!watching) return;
      const es = new EventSource("/api/launch/logs?after=" + logCursor);
      logSource = es;

      es.onmessage = function (ev) {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.reset) {
            // Only a real new Launch should wipe the log — not SSE reconnect.
            logEl.textContent = "";
            logCursor = 0;
            progress.dataset.active = "true";
            setDownloadProgress(0, formatLocalBar(0, "starting…"));
            return;
          }
          if (Object.prototype.hasOwnProperty.call(msg, "progress") && !msg.done) {
            if (msg.progress == null && !(msg.label && String(msg.label).trim())) {
              setDownloadProgress(null, null);
            } else {
              setDownloadProgress(msg.progress, msg.label || null);
            }
            return;
          }
          if (msg.line != null && msg.line !== undefined && !msg.done) {
            appendLog(msg.line);
            if (typeof msg.i === "number") logCursor = msg.i;
            const line = String(msg.line);
            if (
              line.indexOf("Starting services") >= 0 ||
              line.indexOf("skip local model") >= 0 ||
              line.indexOf("skip (already") >= 0 ||
              line.indexOf("=== Launch complete") >= 0
            ) {
              setDownloadProgress(null, null);
            }
            if (
              line.indexOf("Traceback (most recent call last)") === 0 ||
              line.indexOf("ERROR:") === 0
            ) {
              stopLoadingUI(
                line.indexOf("ERROR:") === 0
                  ? line.replace(/^ERROR:\s*/, "")
                  : "see log"
              );
            }
          }
            if (msg.done) {
            stopWatching();
            stopLoadingUI(msg.ok ? null : msg.error || "see log");
            if (msg.ok) {
              window.location.href = "/timeline";
              return;
            }
            refreshStatus();
          }
        } catch (_) {
          /* ignore malformed */
        }
      };

      es.onerror = function () {
        // Resume from cursor — do not treat as a fresh Launch.
        try {
          es.close();
        } catch (_) {}
        if (logSource === es) logSource = null;
        if (watching) {
          setTimeout(connect, 400);
        }
      };
    }

    connect();
  }

  function formatApiDetail(detail) {
    if (detail == null) return null;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(function (d) {
          return d && d.msg ? d.msg : JSON.stringify(d);
        })
        .join("; ");
    }
    try {
      return JSON.stringify(detail);
    } catch (_) {
      return String(detail);
    }
  }

  const launchBtn = UI.createButton({
    label: "Launch",
    onClick: async function () {
      UI.setButtonBusy(launchBtn, true, "Launching…");
      stopWatching();
      logEl.textContent = "";
      logCursor = 0;
      setDownloadProgress(null, null);
      setStatus("Starting Launch…");
      try {
        const creds = collectCredentials();
        const hfOk = (creds.hf_token || "").trim() && !/^•+$/.test(creds.hf_token.trim());
        const rpOk =
          (creds.runpod_api_key || "").trim() &&
          !/^•+$/.test(creds.runpod_api_key.trim());
        // Prefer already-saved values from status if fields look empty/bullets.
        const st = await refreshStatus();
        const c = (st && st.credentials) || {};
        if (!hfOk && !c.hf_token_set) {
          throw new Error("Hugging Face token is required");
        }
        if (!rpOk && !c.runpod_token_set) {
          throw new Error("Runpod API key is required");
        }
        await autoSaveCredentials();
        const r = await fetch("/api/launch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            credentials: collectCredentials(),
            force: true,
          }),
        });
        const body = await r.json().catch(function () {
          return {};
        });
        if (!r.ok) {
          throw new Error(
            formatApiDetail(body.detail) ||
              "Launch failed to start (HTTP " + r.status + ")"
          );
        }
        if (body.replaced) {
          setStatus("Previous Launch cancelled — restarting…");
        } else {
          setStatus("Launch started…");
        }
        watchLogs();
      } catch (e) {
        UI.setButtonBusy(launchBtn, false);
        progress.dataset.active = "false";
        setStatus("<strong>Error:</strong> " + (e.message || e));
      }
    },
  });

  const skipBtn = UI.createButton({
    label: "Skip",
    onClick: function () {
      window.location.href = "/timeline";
    },
  });

  row.appendChild(launchBtn);
  row.appendChild(skipBtn);

  app.appendChild(form);
  app.appendChild(row);
  app.appendChild(statusEl);
  app.appendChild(progress);
  app.appendChild(downloadBar);
  app.appendChild(downloadMeta);
  app.appendChild(logEl);

  refreshStatus().catch(function (e) {
    setStatus("Could not reach API: " + (e.message || e));
  });
  setInterval(function () {
    if (progress.dataset.active !== "true") refreshStatus().catch(function () {});
  }, 5000);
})();
