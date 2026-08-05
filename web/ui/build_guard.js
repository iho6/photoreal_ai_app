(function () {
  "use strict";

  var meta = document.querySelector('meta[name="portal-build"]');
  var pageBuild = meta && meta.getAttribute("content");
  if (!pageBuild || pageBuild === "__BUILD__") return;

  var banner = null;
  var pollMs = 15000;

  function showBanner(serverBuild) {
    if (banner) return;
    banner = document.createElement("div");
    banner.id = "pr-build-guard";
    banner.setAttribute("role", "alert");
    banner.style.cssText =
      "position:fixed;z-index:2147483647;left:0;right:0;top:0;" +
      "display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;" +
      "padding:12px 16px;background:#7a1212;color:#fff;font:600 14px/1.4 system-ui,sans-serif;" +
      "box-shadow:0 2px 12px rgba(0,0,0,.35)";
    var msg = document.createElement("span");
    msg.textContent =
      "Portal code updated (page " +
      pageBuild.slice(0, 8) +
      " vs server " +
      String(serverBuild || "?").slice(0, 8) +
      "). Reload to use the new UI.";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Reload";
    btn.style.cssText =
      "cursor:pointer;border:0;border-radius:6px;padding:8px 14px;" +
      "background:#fff;color:#7a1212;font:700 13px/1 system-ui,sans-serif";
    btn.addEventListener("click", function () {
      var u = new URL(window.location.href);
      u.searchParams.set("b", String(serverBuild || Date.now()));
      window.location.replace(u.toString());
    });
    banner.appendChild(msg);
    banner.appendChild(btn);
    document.body.appendChild(banner);
  }

  function check() {
    fetch("/api/health", { cache: "no-store" })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (j) {
        if (!j || !j.build) return;
        if (String(j.build) !== String(pageBuild)) {
          showBanner(j.build);
        }
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check);
  } else {
    check();
  }
  setInterval(check, pollMs);
})();
