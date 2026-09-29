// Shows the latest release's version next to the download link and the logo, and puts it
// into the download file names (with a direct link to each file). Without
// JavaScript (or if GitHub does not answer) the label keeps its default text.
(function () {
  fetch("https://api.github.com/repos/manuel-alcocer/qdstar/releases/latest",
        { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (release) {
      document.querySelectorAll("[data-version]").forEach(function (el) {
        el.textContent = el.getAttribute("data-version").replace("{v}", release.tag_name);
      });
      // Download file names: the real version instead of x.y.z, linked to the file itself
      var assets = {};
      (release.assets || []).forEach(function (asset) { assets[asset.name] = asset.browser_download_url; });
      document.querySelectorAll("[data-file]").forEach(function (el) {
        var name = el.getAttribute("data-file").replace(/\{v\}/g, release.tag_name);
        el.textContent = name;
        var url = assets[name];
        if (url && !el.hasAttribute("data-nolink") && el.parentNode.tagName !== "A") {
          var link = document.createElement("a");
          link.href = url;
          el.parentNode.insertBefore(link, el);
          link.appendChild(el);
        }
      });
      document.querySelectorAll("[data-xyz-note]").forEach(function (el) { el.hidden = true; });
    })
    .catch(function () { /* keep the default text */ });
})();
