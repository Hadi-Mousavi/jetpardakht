from .unread import count_unread_messages


def unread_messages(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return {'unread_message_count': count_unread_messages(request.user)}
    return {'unread_message_count': 0}
