/* chess_en_bench dashboard: fetch health, leaderboard, and runs. */

"use strict";

function el(tag, text, className) {
  var node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function renderTable(container, headers, rows, emptyMessage) {
  container.replaceChildren();
  if (!rows.length) {
    container.appendChild(el("p", emptyMessage, "empty-state"));
    return;
  }
  var table = document.createElement("table");
  var thead = document.createElement("thead");
  var headRow = document.createElement("tr");
  headers.forEach(function (h) {
    var th = el("th", h);
    th.scope = "col";
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);
  var tbody = document.createElement("tbody");
  rows.forEach(function (cells) {
    var tr = document.createElement("tr");
    cells.forEach(function (cell, i) {
      tr.appendChild(el("td", cell, i === 0 ? "rank" : ""));
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
}

function setHealth(ok, text) {
  var pill = document.getElementById("health-pill");
  pill.classList.toggle("ok", ok);
  document.getElementById("health-text").textContent = text;
}

function loadHealth() {
  fetch("/health")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      setHealth(data.status === "ok",
        "ok — chess_en_bench v" + (data.version || "?"));
    })
    .catch(function () { setHealth(false, "server unreachable"); });
}

function loadLeaderboard() {
  var container = document.getElementById("leaderboard");
  fetch("/api/leaderboard?track=A")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var rows = (data.entries || []).map(function (e, i) {
        var best = e.best_round
          ? "round " + e.best_round.round + " (" + e.best_round.mode + ")"
          : "—";
        return [i + 1, e.run_id, e.score === null ? "—" : e.score, best,
                e.gate_passed ? "passed" : "not passed"];
      });
      renderTable(container, ["#", "Run", "Score", "Best round", "Gate"],
        rows, "No scored runs yet. Run a round, then refresh.");
    })
    .catch(function () {
      container.replaceChildren(
        el("p", "Could not load the leaderboard.", "empty-state"));
    });
}

function loadRuns() {
  var container = document.getElementById("runs");
  fetch("/api/runs")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var rows = (data.runs || []).map(function (run) {
        return [run.run_id, run.track,
                (run.rounds || []).length + " round(s)",
                run.budget_used + "/" + run.budget_total + " official budget"];
      });
      renderTable(container, ["Run", "Track", "Rounds", "Budget"],
        rows, "No runs recorded yet.");
    })
    .catch(function () {
      container.replaceChildren(
        el("p", "Could not load runs.", "empty-state"));
    });
}

document.getElementById("theme-toggle").addEventListener("click", function () {
  var root = document.documentElement;
  var dark = root.classList.toggle("dark");
  localStorage.setItem("ceb-theme", dark ? "dark" : "light");
  this.setAttribute("aria-pressed", dark ? "true" : "false");
});

loadHealth();
loadLeaderboard();
loadRuns();
