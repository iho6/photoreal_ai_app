(function () {
  "use strict";

  const UI = window.PhotorealUI;
  const app = document.getElementById("app");

  const brand = document.createElement("h1");
  brand.className = "pr-brand";
  brand.textContent = "Photoreal";

  const lede = document.createElement("p");
  lede.className = "pr-lede";
  lede.textContent =
    "Enter Hugging Face and Git details, then Launch to install weights and start API + Comfy.";

  const form = document.createElement("div");
  form.style.marginTop = "2.5rem";

  const hf = UI.createField({
    label: "Hugging Face token",
    name: "hf_token",
    password: true,
    placeholder: "hf_…",
    hint: "Required for gated FLUX.2 Klein. Accept the NC license on Hugging Face first.",
    required: true,
  });
  const civitai = UI.createField({
    label: "Civitai API token",
    name: "civitai_api_token",
    password: true,
    placeholder: "Optional",
    hint: "Helps with Civitai rate limits when downloading LoRAs.",
  });
  const github = UI.createField({
    label: "GitHub token",
    name: "github_token",
    password: true,
    placeholder: "Optional",
  });
  const gitName = UI.createField({
    label: "Git user.name",
    name: "git_user_name",
    placeholder: "local repo only",
  });
  const gitEmail = UI.createField({
    label: "Git user.email",
    name: "git_user_email",
    type: "email",
    placeholder: "local repo only",
  });

  [hf, civitai, github, gitName, gitEmail].forEach(function (f) {
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
      civitai_api_token: civitai.input.value,
      github_token: github.input.value,
      git_user_name: gitName.input.value,
      git_user_email: gitEmail.input.value,
    };
  }

  function setStatus(html) {
    statusEl.innerHTML = html;
  }

  async function refreshStatus() {
    const r = await fetch("/api/status");
    const data = await r.json();
    const h = data.health || {};
    const apiOk = h.api && h.api.ok;
    const comfyOk = h.comfy && h.comfy.ok;
    const c = data.credentials || {};
    setStatus(
      "API <strong>" +
        (apiOk ? "up" : "down") +
        "</strong> · Comfy <strong>" +
        (comfyOk ? "up" : "down") +
        "</strong> · HF token <strong>" +
        (c.hf_token_set ? "saved" : "missing") +
        "</strong>"
    );
    if (c.git_user_name) gitName.input.placeholder = c.git_user_name;
    if (c.git_user_email) gitEmail.input.placeholder = c.git_user_email;
    return data;
  }

  const saveBtn = UI.createButton({
    label: "Save",
    onClick: async function () {
      UI.setButtonBusy(saveBtn, true, "Saving…");
      try {
        const r = await fetch("/api/credentials", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(collectCredentials()),
        });
        const body = await r.json().catch(function () {
          return {};
        });
        if (!r.ok) throw new Error(body.detail || "Save failed");
        await refreshStatus();
      } catch (e) {
        setStatus("<strong>Error:</strong> " + (e.message || e));
      } finally {
        UI.setButtonBusy(saveBtn, false);
      }
    },
  });

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
      return /^\s*\[[#\-]+\]\s+\d/.test(s) || s.indexOf("@@PROGRESS@@") === 0;
    };
    if (lines.length && isProg(lines[lines.length - 1])) {
      lines[lines.length - 1] = line;
    } else {
      lines.push(line);
    }
    logEl.textContent = lines.join("\n") + "\n";
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
            logEl.textContent = "";
            logCursor = 0;
            setDownloadProgress(0, formatLocalBar(0, "starting…"));
            return;
          }
          if (Object.prototype.hasOwnProperty.call(msg, "progress") && !msg.done) {
            setDownloadProgress(msg.progress, msg.label || null);
            return;
          }
          if (msg.line != null && msg.line !== undefined && !msg.done) {
            appendLog(msg.line);
            if (typeof msg.i === "number") logCursor = msg.i;
          }
          if (msg.done) {
            progress.dataset.active = "false";
            setDownloadProgress(null, null);
            stopWatching();
            UI.setButtonBusy(launchBtn, false);
            refreshStatus();
            if (!msg.ok) {
              setStatus(
                "<strong>Launch failed:</strong> " + (msg.error || "see log")
              );
            }
          }
        } catch (_) {
          /* ignore malformed */
        }
      };

      es.onerror = function () {
        // Browser would auto-replay the whole stream — close and resume from cursor.
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

  row.appendChild(saveBtn);
  row.appendChild(launchBtn);

  app.appendChild(brand);
  app.appendChild(lede);
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
