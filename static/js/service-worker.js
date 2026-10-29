/**
 * Service Worker for AI Smart Mail Manager
 * Handles Web Push notifications and notification click actions.
 */

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = {
        title: 'Important Email Alert',
        body: event.data.text()
      };
    }
  } else {
    data = {
      title: 'Important Email Alert',
      body: 'New urgent correspondence received in your SmartMail inbox.'
    };
  }

  const title = data.title || 'SmartMail Alert';
  const options = {
    body: data.body || 'You have received an important email.',
    icon: data.icon || '/static/images/logo-192.png',
    badge: data.badge || '/static/images/badge-72.png',
    data: data.data || { url: '/inbox/' },
    vibrate: [200, 100, 200],
    tag: 'smartmail-important-email',
    renotify: true,
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/inbox/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // Check if a client window matching origin is already open
      for (let client of windowClients) {
        if ('focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      // If no window is open, open a new window
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
