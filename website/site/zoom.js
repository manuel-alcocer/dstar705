// Click an image to see it as large as the browser window; click again,
// or press Escape, to close it.
(function () {
  var overlay = document.createElement("div");
  overlay.className = "zoom";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  var big = document.createElement("img");
  overlay.appendChild(big);
  document.body.appendChild(overlay);

  function close() {
    overlay.classList.remove("open");
    document.body.classList.remove("zoomed");
  }
  function open(img) {
    big.src = img.currentSrc || img.src;
    big.alt = img.alt;
    overlay.classList.add("open");
    document.body.classList.add("zoomed");
  }

  document.querySelectorAll(".photos img, figure img").forEach(function (img) {
    img.classList.add("zoomable");
    img.tabIndex = 0;
    img.addEventListener("click", function () { open(img); });
    img.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(img); }
    });
  });
  overlay.addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") close();
  });
})();
