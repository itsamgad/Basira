/* ──────────────────────────────────────────────────────────────────
 * Basira marketing site — script.js
 * Pure vanilla JS. No frameworks, no build step.
 * Modern browsers handle smooth scroll via `scroll-behavior: smooth`
 * in CSS — this file adds polish: nav-shadow on scroll + offset for
 * the fixed nav so anchor targets aren't hidden under it.
 * ────────────────────────────────────────────────────────────────── */

(function () {
  'use strict';

  // ─── 1) Drop-shadow on the nav once you scroll past the hero ───
  const nav = document.querySelector('.nav');
  function setNavShadow() {
    if (!nav) return;
    if (window.scrollY > 8) {
      nav.style.boxShadow = '0 2px 14px rgba(15,23,42,.06)';
    } else {
      nav.style.boxShadow = 'none';
    }
  }
  setNavShadow();
  window.addEventListener('scroll', setNavShadow, { passive: true });

  // ─── 2) Anchor click → scroll the target into view, with offset ──
  // The nav is sticky and 62 px tall; default smooth-scroll lands the
  // section's top right under the nav. We bump 70 px above so headings
  // sit a comfortable distance below the navbar.
  const NAV_OFFSET = 70;
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      const id = this.getAttribute('href').slice(1);
      if (!id) return;                          // bare "#" → top
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      const y = target.getBoundingClientRect().top + window.scrollY - NAV_OFFSET;
      window.scrollTo({ top: y, behavior: 'smooth' });
      // Update the URL hash without a jump.
      history.replaceState(null, '', '#' + id);
    });
  });

  // ─── 3) Tiny "year auto-update" guard (in case the page outlives 2026) ──
  // Footer bakes 2026 in source; this overrides if the user lands later.
  const yearNode = document.querySelector('[data-year]');
  if (yearNode) yearNode.textContent = String(new Date().getFullYear());
})();
