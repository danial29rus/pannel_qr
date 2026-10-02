"""Read-only adapter for the WorkKit SQLite catalogue schema."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


class CatalogAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalProduct:
    sku: str
    name: str
    description: str | None
    price: Decimal
    is_active: bool


class WorkKitSqliteAdapter:
    """Maps WorkKit's products/product_variants tables to panel products.

    The database is opened with SQLite's immutable read-only URI. No writes,
    migrations, locks, or schema changes are ever made to the shop database.
    """

    def __init__(self, settings: dict):
        configured_path = settings.get("db_path")
        if not isinstance(configured_path, str) or not configured_path:
            raise CatalogAdapterError("workkit_sqlite requires settings.db_path")
        self.path = Path(configured_path)

    def fetch_products(self) -> list[ExternalProduct]:
        if not self.path.is_file():
            raise CatalogAdapterError(f"SQLite catalogue file is not available: {self.path}")

        try:
            connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro&immutable=1", uri=True)
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise CatalogAdapterError(f"Cannot open WorkKit SQLite catalogue: {exc}") from exc

        try:
            rows = connection.execute(
                """
                SELECT p.title, p.short_description, p.description, p.active,
                       v.name AS variant_name, v.sku, v.price
                FROM products AS p
                JOIN product_variants AS v ON v.product_id = p.id
                WHERE v.sku IS NOT NULL AND trim(v.sku) <> ''
                ORDER BY p.id, v.id
                """
            ).fetchall()
        except sqlite3.Error as exc:
            raise CatalogAdapterError(f"WorkKit SQLite schema is incompatible: {exc}") from exc
        finally:
            connection.close()

        products: list[ExternalProduct] = []
        for row in rows:
            try:
                price = Decimal(str(row["price"]))
            except (InvalidOperation, TypeError) as exc:
                raise CatalogAdapterError(f"Invalid price for SKU {row['sku']!r}") from exc
            if price <= 0:
                continue
            product_name = row["title"]
            if row["variant_name"]:
                product_name = f"{product_name} — {row['variant_name']}"
            description = row["description"] or row["short_description"]
            products.append(ExternalProduct(
                sku=str(row["sku"]), name=str(product_name), description=description,
                price=price, is_active=bool(row["active"]),
            ))
        return products
