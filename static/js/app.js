/**
 * AI Smart Mail Manager — Global Application JavaScript
 */

(function () {
  'use strict';

  // --------------------------------------------------------------------------
  // Theme Management (Light / Dark mode persisted in localStorage)
  // --------------------------------------------------------------------------
  const THEME_STORAGE_KEY = 'ai_mail_theme';

  function getPreferredTheme() {
    const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (storedTheme) {
      return storedTheme;
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    const themeIcon = document.getElementById('themeToggleIcon');
    if (themeIcon) {
      if (theme === 'dark') {
        themeIcon.classList.remove('bi-moon-stars');
        themeIcon.classList.add('bi-sun');
      } else {
        themeIcon.classList.remove('bi-sun');
        themeIcon.classList.add('bi-moon-stars');
      }
    }
    // Dispatch custom event for charts to adapt colors
    window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
  }

  // Initialize theme immediately
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme);

  document.addEventListener('DOMContentLoaded', () => {
    // Theme toggle button click
    const toggleBtn = document.getElementById('themeToggleBtn');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-bs-theme') || 'light';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        localStorage.setItem(THEME_STORAGE_KEY, newTheme);
        applyTheme(newTheme);
        showToast('Theme Changed', `Switched to ${newTheme} mode`, 'info');
      });
    }

    // ------------------------------------------------------------------------
    // Mobile Sidebar Drawer & Backdrop
    // ------------------------------------------------------------------------
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebar = document.querySelector('.app-sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');

    if (mobileMenuBtn && sidebar && backdrop) {
      mobileMenuBtn.addEventListener('click', () => {
        sidebar.classList.toggle('show-mobile');
        backdrop.classList.toggle('active');
      });

      backdrop.addEventListener('click', () => {
        sidebar.classList.remove('show-mobile');
        backdrop.classList.remove('active');
      });
    }

    // ------------------------------------------------------------------------
    // Keyboard Shortcut: '/' focuses global search bar
    // ------------------------------------------------------------------------
    const searchInput = document.getElementById('globalSearchInput');
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
        if (searchInput) {
          e.preventDefault();
          searchInput.focus();
        }
      }
    });

    // ------------------------------------------------------------------------
    // Interactive Star / Pin / Important toggles via AJAX
    // ------------------------------------------------------------------------
    document.querySelectorAll('.email-action-toggle').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const emailId = btn.dataset.emailId;
        const action = btn.dataset.action;
        const url = `/emails/${emailId}/action/${action}/`;

        try {
          const response = await fetch(url, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
          });
          if (response.ok) {
            const data = await response.json();
            if (action === 'star') {
              const icon = btn.querySelector('i');
              if (data.state) {
                icon.className = 'bi bi-star-fill text-warning';
              } else {
                icon.className = 'bi bi-star text-muted';
              }
            } else if (action === 'pin') {
              const icon = btn.querySelector('i');
              if (data.state) {
                icon.className = 'bi bi-pin-angle-fill text-primary';
              } else {
                icon.className = 'bi bi-pin-angle text-muted';
              }
            } else if (action === 'important') {
              const icon = btn.querySelector('i');
              if (data.state) {
                icon.className = 'bi bi-exclamation-circle-fill text-danger';
              } else {
                icon.className = 'bi bi-exclamation-circle text-muted';
              }
            }
          }
        } catch (err) {
          console.warn('Action toggle error:', err);
        }
      });
    });

    // Initialize all Bootstrap Toasts on page
    const toastElList = [].slice.call(document.querySelectorAll('.toast'));
    toastElList.map(function (toastEl) {
      const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
      toast.show();
    });
  });

  // --------------------------------------------------------------------------
  // Global Toast Helper
  // --------------------------------------------------------------------------
  window.showToast = function (title, message, type = 'info') {
    let container = document.getElementById('globalToastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'globalToastContainer';
      container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      document.body.appendChild(container);
    }

    const typeIcons = {
      success: 'bi-check-circle-fill text-success',
      danger: 'bi-x-circle-fill text-danger',
      warning: 'bi-exclamation-triangle-fill text-warning',
      info: 'bi-info-circle-fill text-primary',
    };

    const toastId = 'toast_' + Date.now();
    const toastHtml = `
      <div id="${toastId}" class="toast align-items-center border-0 shadow-lg" role="alert" aria-live="assertive" aria-atomic="true">
        <div class="toast-header">
          <i class="bi ${typeIcons[type] || typeIcons.info} me-2"></i>
          <strong class="me-auto">${title}</strong>
          <small class="text-muted">just now</small>
          <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
          ${message}
        </div>
      </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);
    const toastElement = document.getElementById(toastId);
    if (window.bootstrap && bootstrap.Toast) {
      const bsToast = new bootstrap.Toast(toastElement, { delay: 4000 });
      bsToast.show();
      toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
    }
  };

})();
