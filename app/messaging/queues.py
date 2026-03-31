"""Имена очередей RabbitMQ (relay и consumer)."""

PAYMENTS_NEW_QUEUE = "payments.new"
PAYMENTS_DLQ_QUEUE = "payments.new.dlq"
RETRY_HEADER = "x-retry-count"
