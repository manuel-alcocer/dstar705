// Fills in the latest release: version label and direct download links.
// Without JavaScript (or if GitHub does not answer) the links keep pointing
// at the releases page.
(function () {
  var api = "https://api.github.com/repos/manuel-alcocer/qdstar/releases/latest";
  fetch(api, { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (release) {
      document.querySelectorAll("[data-version]").forEach(function (el) {
        el.textContent = el.getAttribute("data-version").replace("{v}", release.tag_name);
      });
      var assets = release.assets || [];
      document.querySelectorAll("a[data-asset]").forEach(function (a) {
        var suffix = a.getAttribute("data-asset");
        var match = assets.find(function (x) { return x.name.endsWith(suffix); });
        if (match) {
          a.href = match.browser_download_url;
          a.title = match.name;
        }
      });
    })
    .catch(function () { /* keep the releases page links */ });
})();
