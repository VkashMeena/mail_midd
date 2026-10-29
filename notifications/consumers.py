"""
WebSocket Consumer for real-time notifications via Django Channels.
Enforces per-user group isolation and strict authentication checks.
"""
import logging
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Notification

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    Handles authenticated client WebSocket connections for real-time alerts.
    Subscribes exclusively to the user's isolated channel group: user_{user_id}_notifications.
    """

    async def connect(self):
        user = self.scope.get('user')

        # Strictly reject unauthenticated connections
        if not user or not user.is_authenticated:
            logger.warning("Unauthenticated WebSocket connection attempt rejected.")
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f"user_{user.id}_notifications"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        unread_count = await self._get_unread_count()
        await self.send_json({
            'type': 'connection_established',
            'unread_count': unread_count,
            'user': user.email,
        })
        logger.info("WebSocket connected for user %s (group=%s)", user.email, self.group_name)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
            logger.info("WebSocket disconnected for user %s (code=%s)", getattr(self.user, 'email', 'unknown'), close_code)

    async def receive_json(self, content):
        """
        Handles optional incoming client messages (e.g., ping or mark-read requests).
        """
        action = content.get('action')
        if action == 'ping':
            await self.send_json({'type': 'pong'})
        elif action == 'get_unread_count':
            count = await self._get_unread_count()
            await self.send_json({'type': 'unread_count', 'count': count})

    async def notification_broadcast(self, event):
        """
        Handler for messages routed through channel_layer.group_send(group, {'type': 'notification.broadcast', 'data': ...})
        """
        await self.send_json(event.get('data', {}))

    @database_sync_to_async
    def _get_unread_count(self):
        return Notification.objects.filter(user=self.user, is_read=False).count()
