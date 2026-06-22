// Product analytics → Axiom CRM (GA4 property G-2YHG89FY0N).
// Every event carries `tool_name` so the CRM tool leaderboard can attribute
// page views, scroll depth, dwell time, and outbound clicks to this surface.
(function () {
  "use strict";

  var GA_ID = "G-2YHG89FY0N";
  var TOOL_NAME = "axiom-bills";

  window.dataLayer = window.dataLayer || [];
  function gtag() {
    window.dataLayer.push(arguments);
  }
  window.gtag = window.gtag || gtag;

  gtag("js", new Date());
  gtag("config", GA_ID, { tool_name: TOOL_NAME });

  // Scroll depth — fire once per milestone.
  var scrollFired = {};
  window.addEventListener(
    "scroll",
    function () {
      var docHeight =
        document.documentElement.scrollHeight - window.innerHeight;
      if (docHeight <= 0) return;
      var pct = Math.floor((window.scrollY / docHeight) * 100);
      [25, 50, 75, 100].forEach(function (m) {
        if (pct >= m && !scrollFired[m]) {
          scrollFired[m] = true;
          gtag("event", "scroll_depth", { percent: m, tool_name: TOOL_NAME });
        }
      });
    },
    { passive: true },
  );

  // Dwell time milestones.
  [30, 60, 120, 300].forEach(function (sec) {
    setTimeout(function () {
      if (document.visibilityState !== "hidden") {
        gtag("event", "time_on_tool", { seconds: sec, tool_name: TOOL_NAME });
      }
    }, sec * 1000);
  });

  // Outbound clicks — track navigation to external destinations.
  document.addEventListener("click", function (e) {
    var link = e.target && e.target.closest ? e.target.closest("a") : null;
    if (!link || !link.href) return;
    try {
      var url = new URL(link.href, window.location.origin);
      if (url.hostname && url.hostname !== window.location.hostname) {
        gtag("event", "outbound_click", {
          url: link.href,
          target_hostname: url.hostname,
          tool_name: TOOL_NAME,
        });
      }
    } catch (err) {}
  });
})();
