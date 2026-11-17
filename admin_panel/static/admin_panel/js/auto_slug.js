/**
 * Edvanto Admin Panel - Universal Auto Slug Generator
 *
 * Automatically generates slugs from title fields across admin forms.
 * Appends object ID if available (e.g., editing existing records).
 * Supports manual override and automatic re-sync when cleared.
 */
(function () {
  'use strict';

  function slugify(text) {
    if (!text) return '';
    return text
      .toString()
      .toLowerCase()
      .trim()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/[\s_]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function generateSlug(title, objectId) {
    var base = slugify(title);
    if (!base) return '';
    if (objectId !== undefined && objectId !== null && String(objectId).trim() !== '') {
      var idStr = String(objectId).trim();
      if (!base.endsWith('-' + idStr)) {
        return base + '-' + idStr;
      }
    }
    return base;
  }

  function setupAutoSlug(form) {
    if (!form || form.nodeType !== Node.ELEMENT_NODE) return;

    var titleInput = form.querySelector('input[name="title"], input#id_title, [data-slug-source]');
    var slugInput = form.querySelector('input[name="slug"], input#id_slug, [data-slug-target]');

    if (!titleInput || !slugInput) return;

    // Prevent duplicate event attachments
    if (slugInput.dataset.autoSlugBound === 'true') return;
    slugInput.dataset.autoSlugBound = 'true';

    // Detect objectId from form dataset, input fields, or URL
    var objectId = form.dataset.objectId;
    if (!objectId) {
      var idInput = form.querySelector('input[name="id"], input[name="pk"], input[name$="_id"]');
      if (idInput && idInput.value) {
        objectId = idInput.value;
      }
    }
    if (!objectId) {
      var urlMatch = window.location.pathname.match(/\/(\d+)\/(?:edit|update|change)?\/?$/i);
      if (urlMatch) {
        objectId = urlMatch[1];
      }
    }

    var currentSlug = (slugInput.value || '').trim();
    var currentTitle = (titleInput.value || '').trim();
    var generatedForCurrentTitle = generateSlug(currentTitle, objectId);
    var baseForCurrentTitle = slugify(currentTitle);

    // If slug is currently empty, or matches auto-generated slug (with or without ID),
    // treat it as not manually detached.
    var isManual = false;
    if (currentSlug && currentSlug !== generatedForCurrentTitle && currentSlug !== baseForCurrentTitle) {
      isManual = true;
    }

    // User explicitly types in slug field
    slugInput.addEventListener('input', function () {
      var val = slugInput.value.trim();
      if (val === '') {
        // Clearing slug re-enables auto generation from title
        isManual = false;
        slugInput.value = generateSlug(titleInput.value, objectId);
      } else if (val === generateSlug(titleInput.value, objectId) || val === slugify(titleInput.value)) {
        isManual = false;
      } else {
        isManual = true;
      }
    });

    // Real-time title updates
    titleInput.addEventListener('input', function () {
      if (!isManual) {
        slugInput.value = generateSlug(titleInput.value, objectId);
      }
    });

    // On submit fallback
    form.addEventListener('submit', function () {
      if (!slugInput.value.trim() && titleInput.value.trim()) {
        slugInput.value = generateSlug(titleInput.value, objectId);
      }
    });
  }

  function initAutoSlug(container) {
    var root = container || document;
    if (root.tagName === 'FORM') {
      setupAutoSlug(root);
    } else {
      var forms = root.querySelectorAll('form');
      forms.forEach(setupAutoSlug);
    }
  }

  // Expose globally for dynamic components/modals
  window.edvantoAutoSlug = {
    slugify: slugify,
    generateSlug: generateSlug,
    init: initAutoSlug,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initAutoSlug();
    });
  } else {
    initAutoSlug();
  }

  // Also observe dynamic modal insertions
  if (typeof MutationObserver !== 'undefined') {
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            initAutoSlug(node);
          }
        });
      });
    });
    observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true,
    });
  }
})();
