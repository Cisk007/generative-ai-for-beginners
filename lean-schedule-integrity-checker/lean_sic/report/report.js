(function () {
  "use strict";

  // -- check list filters (status + text search) ---------------------------------
  document.querySelectorAll("[data-check-filter]").forEach(function (bar) {
    var list = document.getElementById(bar.getAttribute("data-check-filter"));
    if (!list) return;
    var buttons = bar.querySelectorAll("button[data-status]");
    var search = bar.querySelector("input[type=search]");
    var counter = bar.querySelector(".count");
    var empty = list.querySelector(".empty");
    var status = "all";
    function apply() {
      var q = search ? search.value.trim().toLowerCase() : "";
      var shown = 0;
      list.querySelectorAll(".check").forEach(function (row) {
        var s = row.getAttribute("data-status");
        var okStatus = status === "all" || s === status || (status === "info" && s === "na");
        var okText = !q || row.getAttribute("data-search").indexOf(q) !== -1;
        row.hidden = !(okStatus && okText);
        if (!row.hidden) shown += 1;
      });
      list.querySelectorAll(".checks-group").forEach(function (group) {
        var next = group.nextElementSibling, any = false;
        while (next && !next.classList.contains("checks-group")) {
          if (next.classList.contains("check") && !next.hidden) any = true;
          next = next.nextElementSibling;
        }
        group.hidden = !any;
      });
      if (counter) counter.textContent = shown + (shown === 1 ? " check" : " checks");
      if (empty) empty.hidden = shown !== 0;
    }
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        status = button.getAttribute("data-status");
        buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b === button)); });
        apply();
      });
    });
    if (search) search.addEventListener("input", apply);
    apply();
  });

  // -- "show all rows" buttons -------------------------------------------------------
  document.addEventListener("click", function (ev) {
    var button = ev.target.closest("[data-show-rows]");
    if (!button) return;
    var table = document.getElementById(button.getAttribute("data-show-rows"));
    if (table) table.querySelectorAll("tr.more").forEach(function (tr) { tr.classList.remove("more"); });
    button.remove();
  });

  // -- tooltips: one floating element fed by data-tip (text only) ----------------
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  function place(x, y) {
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14));
    var top = y - h - 12 < 8 ? y + 18 : y - h - 12;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function show(el, x, y) {
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
    place(x, y);
  }
  document.addEventListener("pointermove", function (ev) {
    var el = ev.target.closest && ev.target.closest("[data-tip]");
    if (!el) { tip.hidden = true; return; }
    show(el, ev.clientX, ev.clientY);
  });
  document.addEventListener("focusin", function (ev) {
    var el = ev.target.closest && ev.target.closest("[data-tip]");
    if (!el) return;
    var r = el.getBoundingClientRect();
    show(el, r.left + r.width / 2, r.top);
  });
  document.addEventListener("focusout", function () { tip.hidden = true; });
  window.addEventListener("scroll", function () { tip.hidden = true; }, { passive: true });

  // -- planning assistant (web app only) ---------------------------------------------
  var form = document.getElementById("ask-form");
  if (form) {
    var answer = document.getElementById("ask-answer");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var field = document.getElementById("ask-question");
      var question = field.value.trim();
      if (!question) { field.focus(); return; }
      var button = form.querySelector("button");
      button.disabled = true;
      button.textContent = "Thinking...";
      fetch(form.getAttribute("data-endpoint"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question })
      })
        .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
        .then(function (res) {
          // the server returns HTML that it built from escaped text
          answer.innerHTML = res.ok ? res.body.html : "";
          if (!res.ok) answer.textContent = res.body.error || "The question could not be answered.";
          answer.hidden = false;
        })
        .catch(function () {
          answer.textContent = "The assistant could not be reached. Is the web app still running?";
          answer.hidden = false;
        })
        .finally(function () {
          button.disabled = false;
          button.textContent = "Ask";
        });
    });
  }
})();
