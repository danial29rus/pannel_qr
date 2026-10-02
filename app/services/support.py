import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SupportConversationCreate, SupportMessageCreate
from app.dao.repositories import SupportDAO, UserDAO
from app.db.models import SupportConversation, SupportMessage
from app.services.email_notifications import EmailNotificationService


class SupportService:
    @staticmethod
    async def list_conversations(session: AsyncSession) -> list[dict]:
        return await SupportDAO.list_conversation_summaries(session)

    @staticmethod
    async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[SupportMessage]:
        if not await SupportDAO.get_conversation(session, conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        return await SupportDAO.list_messages(session, conversation_id)

    @staticmethod
    async def create_conversation(session: AsyncSession, payload: SupportConversationCreate) -> SupportConversation:
        if not await UserDAO.get(session, payload.user_id):
            raise HTTPException(status_code=404, detail="User not found")
        conversation = await SupportDAO.create_conversation(session, SupportConversation(user_id=payload.user_id, subject=payload.subject))
        await SupportDAO.create_message(session, SupportMessage(conversation_id=conversation.id, author_type="user", body=payload.message))
        await session.commit()
        await session.refresh(conversation)
        return conversation

    @staticmethod
    async def add_message(session: AsyncSession, conversation_id: uuid.UUID, payload: SupportMessageCreate) -> SupportMessage:
        conversation = await SupportDAO.get_conversation(session, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        message = await SupportDAO.create_message(session, SupportMessage(conversation_id=conversation_id, **payload.model_dump()))
        await session.commit()
        await session.refresh(message)
        if message.author_type == "operator":
            user = await UserDAO.get(session, conversation.user_id)
            await EmailNotificationService.send_support_reply(
                recipient=user.email if user else None, subject=conversation.subject, body=message.body,
            )
        return message
