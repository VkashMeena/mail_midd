/**
 * AI Smart Mail Manager — Real-Time Notification Client Engine (Phase 6)
 * Handles WebSockets (Django Channels), Desktop Notification API,
 * Web Push subscription, Audible Chimes, and Fallback Short-Polling.
 */

(function () {
  'use strict';

  // Read configuration from document body
  const body = document.body;
  const isAuthenticated = body.dataset.authenticated === 'true';
  const soundEnabled = body.dataset.soundEnabled === 'true';
  const browserEnabled = body.dataset.browserEnabled === 'true';
  const websocketEnabled = body.dataset.websocketEnabled !== 'false';
  const vapidPublicKey = body.dataset.vapidPublicKey || '';
  const csrfToken = body.dataset.csrfToken || '';

  if (!isAuthenticated) {
    return;
  }

  // Audio Chime Synthesizer using Web Audio API (No external sound file required)
  let audioCtx = null;
  function playNotificationChime() {
    if (!soundEnabled) return;
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }

      const now = audioCtx.currentTime;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      osc.type = 'sine';
      // Harmonic chime: E5 (659Hz) -> A5 (880Hz)
      osc.frequency.setValueAtTime(659.25, now);
      osc.frequency.exponentialRampToValueAtTime(880.0, now + 0.12);

      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);

      osc.connect(gain);
      gain.connect(audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.45);
    } catch (e) {
      console.debug('Audio chime playback omitted or blocked by autoplay policy:', e);
    }
  }

  // Update navbar bell and sidebar notification badges
  function updateNotificationBadges(unreadCount) {
    const topbarBadge = document.querySelector('.topbar-icon-badge');
    const notifDropdownHeaderBadge = document.querySelector('#notifDropdownBtn + ul .badge');
    const sidebarNotifBadge = document.querySelector('a[href*="/notifications/"] .nav-counter');
    const notifCenterHeadingBadge = document.querySelector('.page-container .badge.bg-warning');
    const notifTabUnreadBadge = document.querySelector('a[href="?tab=unread"] .badge');

    if (unreadCount > 0) {
      if (!topbarBadge) {
        const btn = document.getElementById('notifDropdownBtn');
        if (btn && !btn.querySelector('.topbar-icon-badge')) {
          const badgeSpan = document.createElement('span');
          badgeSpan.className = 'topbar-icon-badge';
          btn.appendChild(badgeSpan);
        }
      }
      if (notifDropdownHeaderBadge) {
        notifDropdownHeaderBadge.textContent = `${unreadCount} new`;
        notifDropdownHeaderBadge.style.display = 'inline-block';
      }
      if (sidebarNotifBadge) {
        sidebarNotifBadge.textContent = unreadCount;
        sidebarNotifBadge.style.display = 'inline-block';
      }
      if (notifCenterHeadingBadge) {
        notifCenterHeadingBadge.textContent = `${unreadCount} Unread`;
        notifCenterHeadingBadge.style.display = 'inline-block';
      }
      if (notifTabUnreadBadge) {
        notifTabUnreadBadge.textContent = unreadCount;
      }
    } else {
      if (topbarBadge) topbarBadge.remove();
      if (notifDropdownHeaderBadge) notifDropdownHeaderBadge.style.display = 'none';
      if (sidebarNotifBadge) sidebarNotifBadge.style.display = 'none';
      if (notifCenterHeadingBadge) notifCenterHeadingBadge.style.display = 'none';
      if (notifTabUnreadBadge) notifTabUnreadBadge.textContent = '0';
    }
  }

  // Prepend live notification item into Notifications Center if currently on /notifications/
  function prependNotificationToUI(data) {
    const container = document.getElementById('notificationsContainer');
    if (!container) return;

    // Remove empty state placeholder if present
    const emptyState = document.getElementById('notificationsEmptyState');
    if (emptyState) emptyState.remove();

    const notifId = data.notification_id;
    if (document.getElementById(`notification-item-${notifId}`)) return;

    const card = document.createElement('div');
    card.className = 'card mb-3 p-3 border-primary border-start border-3 bg-body-tertiary shadow-sm transition-all';
    card.id = `notification-item-${notifId}`;
    card.innerHTML = `
      <div class="d-flex align-items-start justify-content-between gap-3">
        <div class="d-flex align-items-start gap-3">
          <div class="stat-icon-wrapper bg-primary-subtle text-primary mt-1" style="width: 40px; height: 40px; font-size: 1.2rem;">
            <i class="bi ${data.icon_class || 'bi-bell-fill'}"></i>
          </div>
          <div>
            <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
              <h6 class="mb-0 fw-semibold">${escapeHtml(data.title)}</h6>
              <span class="badge bg-primary text-white" style="font-size: 0.65rem;">NEW</span>
              <span class="badge ${data.badge_class || 'bg-danger text-white'}" style="font-size: 0.65rem;">${escapeHtml(data.priority || 'High')}</span>
              <span class="badge bg-secondary-subtle text-secondary" style="font-size: 0.7rem;">${escapeHtml(data.importance_source || 'Important')}</span>
            </div>
            <p class="mb-2 text-muted" style="font-size: 0.9rem;">${escapeHtml(data.message)}</p>
            <div class="d-flex align-items-center gap-3">
              <small class="text-muted"><i class="bi bi-clock me-1"></i>Just now</small>
              <a href="${data.url || '/inbox/'}" class="btn btn-sm btn-link p-0 text-decoration-none">
                View Email <i class="bi bi-arrow-right"></i>
              </a>
            </div>
          </div>
        </div>
        <div class="d-flex align-items-center gap-2">
          <button
            type="button"
            class="btn btn-sm btn-outline-secondary mark-notification-btn"
            data-notif-id="${notifId}"
            title="Mark as read"
          >
            <i class="bi bi-check2"></i> Mark Read
          </button>
          <button
            type="button"
            class="btn btn-sm btn-outline-danger delete-notification-btn"
            data-notif-id="${notifId}"
            title="Delete notification"
          >
            <i class="bi bi-trash3"></i>
          </button>
        </div>
      </div>
    `;

    container.insertBefore(card, container.firstChild);
    bindNotificationActionButtons(card);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  // Trigger HTML5 Desktop Notification
  function showDesktopNotification(data) {
    if (!browserEnabled) return;
    if (!('Notification' in window)) return;

    function triggerNativeNotification() {
      // 1. Try ServiceWorker registration.showNotification first if active
      if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        navigator.serviceWorker.ready.then((reg) => {
          reg.showNotification(data.title || 'SmartMail Alert', {
            body: data.message || 'Important email received.',
            icon: '/static/images/logo-192.png',
            tag: `smartmail-notif-${data.notification_id}`,
            renotify: true,
            data: { url: data.url || '/inbox/' },
          });
        }).catch((e) => {
          fallbackWindowNotification();
        });
      } else {
        fallbackWindowNotification();
      }
    }

    function fallbackWindowNotification() {
      try {
        const notif = new Notification(data.title || 'SmartMail Alert', {
          body: data.message || 'Important email received.',
          icon: '/static/images/logo-192.png',
          tag: `smartmail-notif-${data.notification_id}`,
          renotify: true,
        });

        notif.onclick = function (e) {
          e.preventDefault();
          window.focus();
          if (data.url) {
            window.location.href = data.url;
          }
          notif.close();
        };
      } catch (e) {
        console.debug('HTML5 desktop notification execution failed:', e);
      }
    }

    if (Notification.permission === 'granted') {
      triggerNativeNotification();
    } else if (Notification.permission === 'default') {
      // If permission has not been requested, prompt user
      Notification.requestPermission().then((perm) => {
        updatePermissionUIState(perm);
        if (perm === 'granted') {
          triggerNativeNotification();
        }
      });
    }
  }

  // Process incoming notification packet (from WebSocket or Short Polling)
  function handleNotificationPayload(data) {
    if (data.type === 'notification_message' || data.notification_id) {
      playNotificationChime();

      if (data.unread_count !== undefined) {
        updateNotificationBadges(data.unread_count);
      }

      showDesktopNotification(data);

      if (window.showToast) {
        window.showToast(data.title, data.message, data.priority === 'High' ? 'danger' : 'info');
      }

      prependNotificationToUI(data);
    } else if (data.type === 'connection_established' && data.unread_count !== undefined) {
      updateNotificationBadges(data.unread_count);
    }
  }

  // WebSocket Connection Management
  let socket = null;
  let reconnectAttempts = 0;
  const maxReconnectAttempts = 10;
  let isPollingFallbackActive = false;

  function connectWebSocket() {
    if (!websocketEnabled) {
      startShortPolling();
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/notifications/`;

    try {
      socket = new WebSocket(wsUrl);

      socket.onopen = function () {
        reconnectAttempts = 0;
        console.debug('Notification WebSocket connected.');
        stopShortPolling();
      };

      socket.onmessage = function (event) {
        try {
          const data = JSON.parse(event.data);
          handleNotificationPayload(data);
        } catch (e) {
          console.error('Failed to parse incoming WebSocket message:', e);
        }
      };

      socket.onclose = function (event) {
        console.debug(`Notification WebSocket closed (code: ${event.code}).`);
        socket = null;
        scheduleReconnect();
      };

      socket.onerror = function (err) {
        console.debug('Notification WebSocket error:', err);
        try { socket.close(); } catch (e) {}
      };
    } catch (e) {
      console.debug('WebSocket initialization failed, enabling short polling:', e);
      startShortPolling();
    }
  }

  function scheduleReconnect() {
    if (reconnectAttempts < maxReconnectAttempts) {
      reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(1.8, reconnectAttempts), 30000);
      console.debug(`Scheduling WebSocket reconnect in ${Math.round(delay / 1000)}s (attempt ${reconnectAttempts})`);
      setTimeout(connectWebSocket, delay);
    } else {
      console.warn('Max WebSocket reconnect attempts reached. Switching to HTTP short polling.');
      startShortPolling();
    }
  }

  // Short Polling Fallback
  let pollIntervalId = null;
  function startShortPolling() {
    if (isPollingFallbackActive) return;
    isPollingFallbackActive = true;

    pollIntervalId = setInterval(async () => {
      try {
        const res = await fetch('/notifications/unread-count/', {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (res.ok) {
          const data = await res.json();
          if (data.unread_count !== undefined) {
            updateNotificationBadges(data.unread_count);
          }
        }
      } catch (err) {
        console.debug('Short polling request failed:', err);
      }
    }, 30000);
  }

  function stopShortPolling() {
    if (pollIntervalId) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
    }
    isPollingFallbackActive = false;
  }

  // Service Worker Registration
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/static/js/service-worker.js')
        .then(reg => {
          console.debug('Service Worker registered with scope:', reg.scope);
        })
        .catch(err => {
          console.debug('Service Worker registration failed:', err);
        });
    });
  }

  // Browser Desktop Notification Permission Helper
  async function requestDesktopNotificationPermission() {
    if (!('Notification' in window)) {
      if (window.showToast) {
        window.showToast('Not Supported', 'This browser does not support desktop notifications.', 'warning');
      }
      return 'unsupported';
    }

    try {
      const permission = await Notification.requestPermission();
      updatePermissionUIState(permission);
      if (permission === 'granted') {
        if (window.showToast) {
          window.showToast('Notifications Enabled', 'Desktop notifications are now enabled for urgent emails.', 'success');
        }
        // Attempt Web Push subscription if supported and VAPID key is configured
        if (vapidPublicKey) {
          subscribeToPushNotifications();
        }
      } else if (permission === 'denied') {
        if (window.showToast) {
          window.showToast('Permission Denied', 'Browser notifications are blocked. Please enable them in browser settings.', 'warning');
        }
      }
      return permission;
    } catch (err) {
      console.error('Error requesting notification permission:', err);
      return 'error';
    }
  }

  function updatePermissionUIState(permission) {
    const permStatusEl = document.getElementById('browserPermissionStatus');
    const permBtn = document.getElementById('enableBrowserNotifBtn');
    if (!permStatusEl) return;

    if (permission === 'granted') {
      permStatusEl.innerHTML = '<span class="badge bg-success-subtle text-success border border-success-subtle px-2 py-1"><i class="bi bi-check-circle me-1"></i>Enabled</span>';
      if (permBtn) {
        permBtn.textContent = 'Notifications Active';
        permBtn.disabled = true;
        permBtn.className = 'btn btn-sm btn-outline-success';
      }
    } else if (permission === 'denied') {
      permStatusEl.innerHTML = '<span class="badge bg-danger-subtle text-danger border border-danger-subtle px-2 py-1"><i class="bi bi-slash-circle me-1"></i>Blocked</span>';
      if (permBtn) {
        permBtn.textContent = 'Blocked by Browser';
        permBtn.disabled = true;
        permBtn.className = 'btn btn-sm btn-outline-danger';
      }
    } else {
      permStatusEl.innerHTML = '<span class="badge bg-warning-subtle text-warning border border-warning-subtle px-2 py-1"><i class="bi bi-exclamation-circle me-1"></i>Not Enabled</span>';
      if (permBtn) {
        permBtn.textContent = 'Enable Notifications';
        permBtn.disabled = false;
        permBtn.className = 'btn btn-sm btn-primary';
      }
    }
  }

  // Web Push Subscription Helper
  async function subscribeToPushNotifications() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !vapidPublicKey) {
      return;
    }

    try {
      const reg = await navigator.serviceWorker.ready;
      let subscription = await reg.pushManager.getSubscription();

      if (!subscription) {
        const convertedKey = urlBase64ToUint8Array(vapidPublicKey);
        subscription = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: convertedKey
        });
      }

      // Send subscription to backend
      const rawKey = subscription.getKey('p256dh');
      const rawAuth = subscription.getKey('auth');
      const p256dh = rawKey ? btoa(String.fromCharCode.apply(null, new Uint8Array(rawKey))) : '';
      const auth = rawAuth ? btoa(String.fromCharCode.apply(null, new Uint8Array(rawAuth))) : '';

      await fetch('/notifications/push/subscribe/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
          endpoint: subscription.endpoint,
          p256dh: p256dh,
          auth: auth,
          user_agent: navigator.userAgent
        })
      });
      console.debug('Web Push subscription registered successfully.');
    } catch (err) {
      console.debug('Failed to subscribe to Web Push:', err);
    }
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  // Bind actions (Mark Read, Delete) to notification buttons
  function bindNotificationActionButtons(root) {
    const scope = root || document;

    // Mark as Read button
    scope.querySelectorAll('.mark-notification-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const notifId = btn.dataset.notifId;
        const notifItem = document.getElementById(`notification-item-${notifId}`);

        try {
          const response = await fetch(`/notifications/${notifId}/read/`, {
            method: 'POST',
            headers: {
              'X-CSRFToken': csrfToken,
              'X-Requested-With': 'XMLHttpRequest'
            }
          });
          if (response.ok) {
            const data = await response.json();
            if (notifItem) {
              notifItem.classList.remove('border-primary', 'border-start', 'border-3', 'bg-body-tertiary');
              const newBadge = notifItem.querySelector('.badge.bg-primary');
              if (newBadge) newBadge.remove();
              btn.remove();
            }
            if (data.unread_count !== undefined) {
              updateNotificationBadges(data.unread_count);
            }
            if (window.showToast) {
              window.showToast('Notification Updated', 'Marked notification as read.', 'success');
            }
          }
        } catch (err) {
          console.error('Error marking notification read:', err);
        }
      });
    });

    // Delete notification button
    scope.querySelectorAll('.delete-notification-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const notifId = btn.dataset.notifId;
        const notifItem = document.getElementById(`notification-item-${notifId}`);

        if (!confirm('Remove this notification? (Your email will not be deleted)')) {
          return;
        }

        try {
          const response = await fetch(`/notifications/${notifId}/delete/`, {
            method: 'POST',
            headers: {
              'X-CSRFToken': csrfToken,
              'X-Requested-With': 'XMLHttpRequest'
            }
          });
          if (response.ok) {
            const data = await response.json();
            if (notifItem) notifItem.remove();
            if (data.unread_count !== undefined) {
              updateNotificationBadges(data.unread_count);
            }
            if (window.showToast) {
              window.showToast('Notification Removed', 'Notification was removed.', 'info');
            }
          }
        } catch (err) {
          console.error('Error deleting notification:', err);
        }
      });
    });
  }

  // Send test notification helper
  async function sendTestNotification() {
    try {
      const res = await fetch('/notifications/test/', {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest'
        }
      });
      if (res.ok) {
        const data = await res.json();
        if (window.showToast) {
          window.showToast('Test Sent', data.message || 'Test notification dispatched.', 'success');
        }
      }
    } catch (err) {
      console.error('Failed to trigger test notification:', err);
    }
  }

  // Expose global methods
  window.SmartMailNotifications = {
    requestPermission: requestDesktopNotificationPermission,
    playChime: playNotificationChime,
    sendTestNotification: sendTestNotification,
    subscribePush: subscribeToPushNotifications,
    getPermissionStatus: () => ('Notification' in window ? Notification.permission : 'unsupported')
  };

  // Lifecycle Initialization
  document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    bindNotificationActionButtons(document);

    // Initial permission UI sync on settings page
    if ('Notification' in window) {
      updatePermissionUIState(Notification.permission);
    }

    // Bind Enable Notifications button if present on page
    const enableBtn = document.getElementById('enableBrowserNotifBtn');
    if (enableBtn) {
      enableBtn.addEventListener('click', (e) => {
        e.preventDefault();
        requestDesktopNotificationPermission();
      });
    }

    // Bind Test Notification button if present on page
    const testBtn = document.getElementById('sendTestNotifBtn');
    if (testBtn) {
      testBtn.addEventListener('click', (e) => {
        e.preventDefault();
        sendTestNotification();
      });
    }

    // Bind Sound Preview button if present on page
    const soundPreviewBtn = document.getElementById('previewSoundBtn');
    if (soundPreviewBtn) {
      soundPreviewBtn.addEventListener('click', (e) => {
        e.preventDefault();
        playNotificationChime();
      });
    }

    // Proactively offer 1-click desktop notification enablement if permission has not been requested yet
    if ('Notification' in window && Notification.permission === 'default' && browserEnabled) {
      setTimeout(() => {
        const promptToastId = 'notif_permission_prompt';
        if (!document.getElementById(promptToastId) && !sessionStorage.getItem('notif_prompt_dismissed')) {
          const container = document.getElementById('globalToastContainer');
          if (container) {
            const toastEl = document.createElement('div');
            toastEl.id = promptToastId;
            toastEl.className = 'toast align-items-center border-0 shadow-lg text-bg-dark';
            toastEl.setAttribute('role', 'alert');
            toastEl.setAttribute('aria-live', 'assertive');
            toastEl.setAttribute('aria-atomic', 'true');
            toastEl.innerHTML = `
              <div class="d-flex align-items-center justify-content-between p-2">
                <div class="toast-body d-flex align-items-center gap-2 py-1">
                  <i class="bi bi-bell-fill text-warning fs-5"></i>
                  <div class="small">
                    <strong>Enable Alerts:</strong> Get desktop notifications for urgent emails.
                  </div>
                </div>
                <div class="d-flex align-items-center gap-2 me-2">
                  <button type="button" class="btn btn-sm btn-primary py-0 px-2 fw-semibold" id="quickEnableNotifBtn" style="font-size: 0.8rem;">Enable</button>
                  <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
              </div>
            `;
            container.appendChild(toastEl);
            if (window.bootstrap && bootstrap.Toast) {
              const bsToast = new bootstrap.Toast(toastEl, { delay: 15000 });
              bsToast.show();
              document.getElementById('quickEnableNotifBtn')?.addEventListener('click', () => {
                bsToast.hide();
                requestDesktopNotificationPermission();
              });
              toastEl.addEventListener('hidden.bs.toast', () => {
                sessionStorage.setItem('notif_prompt_dismissed', 'true');
                toastEl.remove();
              });
            }
          }
        }
      }, 1500);
    }
  });

})();
