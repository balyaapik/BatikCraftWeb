(() => {
  const header = document.getElementById("workspace-header");
  const button = header?.querySelector(".bob-mobile-toggle");
  if (!header || !button) return;
  button.addEventListener("click", () => {
    const open = header.classList.toggle("nav-open");
    button.setAttribute("aria-expanded", String(open));
  });
})();
