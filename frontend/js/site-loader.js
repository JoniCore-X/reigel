(function () {
  "use strict";

  var root = document.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var forced = window.matchMedia("(forced-colors: active)");

  // The overlay is decorative and must never block a reduced-motion or
  // high-contrast visit. The CSS hides it too, but skipping here avoids
  // locking scroll and announcing a loader that nobody sees.
  if (reduce.matches || forced.matches) return;

  root.classList.add("ps-booting");

  var MIN_FIRST = 1600;
  var MIN_NEXT = 650;
  var EXIT_MS = 520;
  // The overlay follows the real page load instead of a fixed maximum.
  // These limits only decide when the connection counts as failing.
  var SLOW_MS = 15000;
  var OFFLINE_GRACE = 2200;
  var FAILURES_ALLOWED = 3;
  var MESSAGES = {
    offline: "Sin conexión a internet. Revisa tu red y vuelve a intentarlo.",
    network: "No pudimos cargar todo el contenido. Revisa tu conexión y vuelve a intentarlo.",
    slow: "La conexión está tardando más de lo normal."
  };
  var started = 0;
  var loader = null;
  var errorBox = null;
  var errorText = null;
  var exitTimer = null;
  var slowTimer = null;
  var offlineTimer = null;
  var failedTargets = [];
  var failures = 0;
  var loaded = false;
  var failed = false;
  var done = false;
  var seen = false;

  try {
    seen = window.sessionStorage.getItem("ps-loader-seen") === "1";
  } catch (error) {
    seen = false;
  }

  var minimum = seen ? MIN_NEXT : MIN_FIRST;

  // Resource failures can happen while the document is still parsing, before
  // boot attaches its listeners, so watch from the start.
  window.addEventListener("error", onResourceError, true);

  function placeOnTop() {
    // A modal <dialog> lives in the browser top layer, above any z-index.
    // The chat shell opens one on load, so the overlay joins the top layer
    // itself; the fixed fallback still covers browsers without popovers.
    if (!loader || typeof loader.showPopover !== "function") return;
    if (!loader.hasAttribute("popover")) return;
    try {
      loader.showPopover();
    } catch (error) {
      /* already open or top layer unavailable */
    }
  }

  function removeFromTop() {
    if (!loader || typeof loader.hidePopover !== "function") return;
    try {
      loader.hidePopover();
    } catch (error) {
      /* not open */
    }
  }

  function clearTimers() {
    window.clearTimeout(exitTimer);
    window.clearTimeout(slowTimer);
    window.clearTimeout(offlineTimer);
  }

  function exit() {
    if (done) return;
    done = true;
    failed = false;
    clearTimers();
    window.removeEventListener("error", onResourceError, true);
    window.removeEventListener("offline", onOffline);
    window.removeEventListener("online", onOnline);
    if (!loader) {
      document.removeEventListener("keydown", onKeydown, true);
      root.classList.remove("ps-booting");
      return;
    }
    loader.classList.add("ps-leaving");
    window.setTimeout(function () {
      removeFromTop();
      loader.hidden = true;
      loader.classList.remove("ps-failed");
      if (errorBox) errorBox.hidden = true;
      if (errorText) errorText.textContent = "";
      root.classList.remove("ps-booting");
      document.removeEventListener("keydown", onKeydown, true);
      if (document.body) document.body.removeAttribute("aria-busy");
      try {
        window.sessionStorage.setItem("ps-loader-seen", "1");
      } catch (error) {
        /* session storage can be unavailable in private contexts */
      }
    }, EXIT_MS);
  }

  function schedule(immediate) {
    if (done || failed) return;
    var elapsed = performance.now() - started;
    var wait = immediate ? 0 : Math.max(0, minimum - elapsed);
    window.clearTimeout(exitTimer);
    exitTimer = window.setTimeout(exit, wait);
  }

  function skip() {
    if (done) return;
    failed = false;
    schedule(true);
  }

  function showError(kind) {
    if (done || failed) return;
    failed = true;
    clearTimers();
    if (!loader) return;
    loader.classList.add("ps-failed");
    if (errorText) errorText.textContent = MESSAGES[kind] || MESSAGES.network;
    if (errorBox) errorBox.hidden = false;
    var retry = loader.querySelector(".ps-retry");
    if (retry) retry.focus({ preventScroll: true });
  }

  function clearError() {
    failed = false;
    failures = 0;
    failedTargets = [];
    if (!loader) return;
    loader.classList.remove("ps-failed");
    if (errorBox) errorBox.hidden = true;
    if (errorText) errorText.textContent = "";
    if (!loaded) slowTimer = window.setTimeout(checkSlow, SLOW_MS);
  }

  function checkSlow() {
    if (!done && !failed && !loaded) showError("slow");
  }

  function onLoad() {
    loaded = true;
    window.clearTimeout(slowTimer);
    window.clearTimeout(offlineTimer);
    // A completed load does not silently erase a shown failure: the user
    // explicitly retries or continues, so the message never just flickers.
    schedule(false);
  }

  function onResourceError(event) {
    // Load can fire just before a failed deferred script reports its error,
    // so keep counting until the overlay actually leaves.
    if (done || failed) return;
    var target = event.target;
    if (!target || target === window || !target.tagName) return;
    var tag = target.tagName.toUpperCase();
    if (tag !== "IMG" && tag !== "SCRIPT" && tag !== "LINK" && tag !== "SOURCE") return;
    if (failedTargets.indexOf(target) !== -1) return;
    failedTargets.push(target);
    failures += 1;
    if (failures >= FAILURES_ALLOWED) showError("network");
  }

  function onOffline() {
    if (done || failed || loaded) return;
    window.clearTimeout(offlineTimer);
    offlineTimer = window.setTimeout(function () {
      if (!done && !failed && !loaded) showError("offline");
    }, OFFLINE_GRACE);
  }

  function onOnline() {
    window.clearTimeout(offlineTimer);
    if (!failed) {
      if (!loaded && !done) slowTimer = window.setTimeout(checkSlow, SLOW_MS);
      return;
    }
    if (navigator.onLine === false) return;
    clearError();
    if (loaded) schedule(false);
  }

  function onKeydown(event) {
    if (event.key !== "Escape") return;
    // Escape dismisses the loader, not a modal that may sit underneath.
    // Keep swallowing it through the fade so the dialog stays intact.
    event.preventDefault();
    event.stopPropagation();
    if (!done) skip();
  }

  function boot() {
    loader = document.getElementById("ps-loader");
    if (!loader) {
      window.removeEventListener("error", onResourceError, true);
      root.classList.remove("ps-booting");
      return;
    }
    loader.hidden = false;
    placeOnTop();
    // The minimum counts from the visible overlay, not from the head script,
    // so a slow parse never truncates the entrance sequence.
    started = performance.now();
    if (document.body) document.body.setAttribute("aria-busy", "true");

    errorBox = loader.querySelector(".ps-error");
    errorText = loader.querySelector(".ps-error-text");
    var retry = loader.querySelector(".ps-retry");
    var cont = loader.querySelector(".ps-continue");
    if (retry) {
      retry.addEventListener("click", function () {
        window.location.reload();
      });
    }
    if (cont) {
      cont.addEventListener("click", function () {
        skip();
      });
    }

    loader.addEventListener("pointerdown", function () {
      // Keep the failure message on screen; its buttons own the next step.
      if (failed) return;
      schedule(true);
    }, { passive: true });

    document.addEventListener("keydown", onKeydown, true);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);

    // Errors raised before boot have no element to update yet; surface them
    // now that the overlay exists instead of leaving a silent, stuck loader.
    if (failures >= FAILURES_ALLOWED) {
      failed = false;
      showError("network");
      return;
    }

    if (document.readyState === "complete") {
      loaded = true;
      schedule(false);
      return;
    }
    loaded = false;
    window.addEventListener("load", onLoad, { once: true });
    slowTimer = window.setTimeout(checkSlow, SLOW_MS);
    if (navigator.onLine === false) onOffline();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }

  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    done = true;
    failed = false;
    clearTimers();
    window.removeEventListener("error", onResourceError, true);
    window.removeEventListener("offline", onOffline);
    window.removeEventListener("online", onOnline);
    document.removeEventListener("keydown", onKeydown, true);
    removeFromTop();
    if (loader) {
      loader.hidden = true;
      loader.classList.remove("ps-failed");
    }
    if (errorBox) errorBox.hidden = true;
    if (errorText) errorText.textContent = "";
    root.classList.remove("ps-booting");
    if (document.body) document.body.removeAttribute("aria-busy");
  });
})();
