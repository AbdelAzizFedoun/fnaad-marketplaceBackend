import requests
from .models import Notification

EXPO_PUSH_URL = "http://exp.host/--/api/v2/push/send"


def send_push_notification(token, title, body, data=None):
    """
    Sends a push notification via Expo's push service.
    `token` should be an Expo push token like ExponentPushToken[xxxxxxxx].
    Fails silently (logs) so a notification failure never breaks the calling view.
    """
    print(f"[push] attempting to send: token={token}, title={title}, body={body}")
    
    if not token:
        print("[push] no token, skipping")
        return

    payload = {
        "to": token,
        "title": title,
        "body": body,
        "sound": "default",
        "data": data or {},
    }

    try:
        print(f"[push] posting to {EXPO_PUSH_URL}")
        response = requests.post(
            EXPO_PUSH_URL,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=5,
        )
        response.raise_for_status()
        print(f"[push] success! response status: {response.status_code}")
    except requests.RequestException as e:
        # TODO: swap for proper logging once you have a logger configured
        print(f"[push] failed to send to {token}: {e}")


def create_notification(user, title, body, notification_type, data=None):
    notification = Notification.objects.create(
        user=user, title=title, body=body, notification_type=notification_type, data=data or {}
    )
    send_push_notification(user.expo_push_token, title, body, {"type": notification_type, **(data or {})})
    return notification
