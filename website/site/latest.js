// Shows the latest release's version next to the download link and the logo. Without
// JavaScript (or if GitHub does not answer) the label keeps its default text.
(function () {
  fetch("https://api.github.com/repos/manuel-alcocer/qdstar/releases/latest",
        { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (release) {
      document.querySelectorAll("[data-version]").forEach(function (el) {
        el.textContent = el.getAttribute("data-version").replace("{v}", release.tag_name);
      });
    })
    .catch(function () { /* keep the default text */ });
})();
