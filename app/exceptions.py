class DomainError(Exception):
    """Базовый класс для доменных ошибок приложения."""


class DatabaseError(DomainError):
    """Базовая ошибка базы данных абстрагированная от конкретной ORM."""


class EntityExistsError(DatabaseError):
    """Ошибка, возникающая при попытке создать сущность, которая уже существует (конфликт уникальности)."""


class EntityNotFoundError(DatabaseError):
    """Ошибка, возникающая, если сущность не найдена."""
