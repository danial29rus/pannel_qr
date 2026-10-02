"""Generate safe, visually useful demo users and support dialogues.

All generated mailboxes use the RFC-reserved .test zone. This command does not
send email, create payment transactions, or call an external service.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.dao.repositories import SupportDAO, UserDAO
from app.db.models import SupportConversation, SupportMessage, User
from app.db.session import SessionLocal, engine

PEOPLE = (
    ("Алексей Иванов", "alexey.ivanov"), ("Мария Иванова", "maria.ivanova"),
    ("Дмитрий Петров", "dmitry.petrov"), ("Анна Петрова", "anna.petrova"),
    ("Илья Смирнов", "ilya.smirnov"), ("Елена Смирнова", "elena.smirnova"),
    ("Максим Волков", "maxim.volkov"), ("Ольга Волкова", "olga.volkova"),
    ("Кирилл Соколов", "kirill.sokolov"), ("София Лебедева", "sofia.lebedeva"),
    ("Артём Орлов", "artem.orlov"), ("Виктория Новикова", "victoria.novikova"),
)
BUSINESSES = (
    "ООО «Лазурный Маяк»", "ООО «Северный Контур»", "ИП Анна Петрова",
    "ООО «Точка Роста»", "ООО «Городская Лавка»", "ООО «Прометей Лаб»",
    "ИП Максим Волков", "ООО «Ритм Сервиса»",
)
SAFE_EMAIL_DOMAINS = (
    "clients.localhost", "gmail.localhost", "yandex.localhost",
    "outlook.localhost", "mail.localhost", "company.localhost",
)
TOPICS = (
    "Проверка статуса платежа", "Вопрос по заказу", "Не открывается платёжная ссылка",
    "Нужен чек по заказу", "Изменение данных покупателя", "Вопрос по возврату",
)
OPENING_MESSAGES = (
    "Здравствуйте! Подскажите, пожалуйста, текущий статус заказа?",
    "Оплата прошла, но подтверждение пока не пришло. Можете проверить?",
    "Подскажите, где можно скачать чек по этой покупке?",
    "Не получается открыть страницу оплаты с телефона.",
)
OPERATOR_MESSAGES = (
    "Здравствуйте! Проверяем информацию по заказу, вернёмся с ответом в ближайшее время.",
    "Спасибо за обращение. Платёж виден в системе, обновление статуса занимает несколько минут.",
    "Отправили данные коллегам. Пожалуйста, не создавайте повторную оплату до ответа.",
    "Готово: информация обновлена. Если вопрос останется, напишите нам в этом диалоге.",
)
FOLLOW_UP_MESSAGES = (
    "Спасибо, буду ждать.", "Понял, благодарю за помощь.", "Проверил — теперь всё отображается.",
)


def build_user(index: int, namespace: str, email_domain: str, rng: random.Random, *, user_id: uuid.UUID | None = None) -> User:
    full_name, email_login = rng.choice(PEOPLE)
    unique = f"{namespace}.{index:05d}"
    domain = email_domain or rng.choice(SAFE_EMAIL_DOMAINS)
    return User(
        id=user_id or uuid.uuid4(), full_name=full_name,
        email=f"{email_login}.{unique}@{domain}",
        phone=f"+7 (000) 000-{index // 100:02d}-{index % 100:02d}",
        telegram_username=f"{email_login.replace('.', '_')}_{unique}".replace("-", "_").replace(".", "_"),
        business_name=rng.choice(BUSINESSES),
    )


async def seed(users_count: int, conversations_count: int, namespace: str, email_domain: str, seed_value: int, batch_size: int, refresh_namespace: bool) -> dict:
    settings = get_settings()
    if settings.environment.lower() not in {"development", "test"}:
        raise RuntimeError("Demo seeding is allowed only when ENVIRONMENT is development or test")
    if conversations_count > users_count:
        raise ValueError("conversations cannot exceed users")
    if email_domain and email_domain not in SAFE_EMAIL_DOMAINS:
        raise ValueError("email-domain must be one of the safe local demo domains")

    rng = random.Random(seed_value)
    async with SessionLocal() as session:
        if refresh_namespace:
            users = await UserDAO.list_by_email_marker(session, namespace)
            if not users:
                raise ValueError(f"No existing users found for namespace {namespace!r}")
            # Unique usernames can swap between rows during a refresh. Move them
            # to temporary values first so PostgreSQL never observes a collision.
            for user in users:
                user.telegram_username = f"refresh_{user.id.hex}"
            await session.flush()
            for index, user in enumerate(sorted(users, key=lambda item: str(item.id)), start=1):
                refreshed = build_user(index, namespace, email_domain, rng, user_id=user.id)
                user.full_name = refreshed.full_name
                user.email = refreshed.email
                user.phone = refreshed.phone
                user.telegram_username = refreshed.telegram_username
                user.business_name = refreshed.business_name
            await session.commit()
            return {"users": len(users), "conversations": 0, "namespace": namespace, "mode": "refreshed"}

        users = [build_user(index, namespace, email_domain, rng) for index in range(1, users_count + 1)]
        for start in range(0, len(users), batch_size):
            await UserDAO.create_many(session, users[start:start + batch_size])
            await session.commit()

        now = datetime.now(timezone.utc)
        records: list[SupportConversation | SupportMessage] = []
        for index, user in enumerate(rng.sample(users, conversations_count), start=1):
            created_at = now - timedelta(days=rng.randrange(0, 28), minutes=rng.randrange(0, 1_440))
            conversation = SupportConversation(
                id=uuid.uuid4(), user_id=user.id, subject=rng.choice(TOPICS),
                status="open" if index % 4 else "closed",
                created_at=created_at,
                closed_at=None if index % 4 else created_at + timedelta(minutes=12),
            )
            records.extend((
                conversation,
                SupportMessage(id=uuid.uuid4(), conversation_id=conversation.id, author_type="user", body=rng.choice(OPENING_MESSAGES), created_at=created_at),
                SupportMessage(id=uuid.uuid4(), conversation_id=conversation.id, author_type="operator", body=rng.choice(OPERATOR_MESSAGES), created_at=created_at + timedelta(minutes=3)),
            ))
            if index % 3:
                records.append(SupportMessage(id=uuid.uuid4(), conversation_id=conversation.id, author_type="user", body=rng.choice(FOLLOW_UP_MESSAGES), created_at=created_at + timedelta(minutes=6)))

            if len(records) >= batch_size:
                await SupportDAO.create_many(session, records)
                await session.commit()
                records.clear()
        if records:
            await SupportDAO.create_many(session, records)
            await session.commit()
    return {"users": users_count, "conversations": conversations_count, "namespace": namespace, "mode": "created"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed safe demo users and support conversations")
    parser.add_argument("--users", type=int, default=200, choices=range(1, 100_001))
    parser.add_argument("--conversations", type=int, default=40, choices=range(0, 100_001))
    parser.add_argument("--namespace", default=f"demo-{secrets.token_hex(4)}", help="Unique run label, used in generated login/email identifiers")
    parser.add_argument("--email-domain", default="", help="Optional safe local domain; omit to mix local gmail/yandex/outlook-style domains")
    parser.add_argument("--seed", type=int, default=20261001, help="Makes names and dialogue selection repeatable")
    parser.add_argument("--batch-size", type=int, default=500, choices=range(50, 5_001))
    parser.add_argument("--refresh-namespace", action="store_true", help="Update existing demo users in this namespace without creating more records")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    result = await seed(args.users, args.conversations, args.namespace, args.email_domain, args.seed, args.batch_size, args.refresh_namespace)
    print(f"{result['mode'].title()}: {result['users']} demo users and {result['conversations']} support conversations (namespace: {result['namespace']}).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
