"""Loads and indexes the 9 Olist CSVs once per process (cached)."""

from __future__ import annotations

import functools
from dataclasses import dataclass

import pandas as pd

from src.config import DATA_DIR

_TIMESTAMP_COLS = {
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "order_reviews": ["review_creation_date", "review_answer_timestamp"],
}


@dataclass(frozen=True)
class DataBundle:
    customers: pd.DataFrame
    order_items: pd.DataFrame
    order_payments: pd.DataFrame
    orders: pd.DataFrame
    products: pd.DataFrame
    sellers: pd.DataFrame
    category_translation: pd.DataFrame


def _read(name: str, timestamp_cols: list[str] | None = None) -> pd.DataFrame:
    path = DATA_DIR / f"olist_{name}_dataset.csv"
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in timestamp_cols or []:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


@functools.lru_cache(maxsize=1)
def load_data() -> DataBundle:
    customers = _read("customers")
    order_items = _read("order_items", _TIMESTAMP_COLS["order_items"])
    order_payments = _read("order_payments")
    orders = _read("orders", _TIMESTAMP_COLS["orders"])
    products = _read("products")
    sellers = _read("sellers")
    category_translation = pd.read_csv(
        DATA_DIR / "product_category_name_translation.csv", encoding="utf-8-sig"
    )
    return DataBundle(
        customers=customers,
        order_items=order_items,
        order_payments=order_payments,
        orders=orders,
        products=products,
        sellers=sellers,
        category_translation=category_translation,
    )


def get_order_row(order_id: str) -> pd.Series | None:
    data = load_data()
    rows = data.orders[data.orders["order_id"] == order_id]
    if rows.empty:
        return None
    return rows.iloc[0]


def get_customer_row(customer_id: str) -> pd.Series | None:
    data = load_data()
    rows = data.customers[data.customers["customer_id"] == customer_id]
    if rows.empty:
        return None
    return rows.iloc[0]


def get_order_items(order_id: str) -> pd.DataFrame:
    data = load_data()
    return data.order_items[data.order_items["order_id"] == order_id].sort_values(
        "order_item_id"
    )


def get_order_payments(order_id: str) -> pd.DataFrame:
    data = load_data()
    return data.order_payments[
        data.order_payments["order_id"] == order_id
    ].sort_values("payment_sequential")


def get_products(product_ids: list[str]) -> pd.DataFrame:
    data = load_data()
    return data.products[data.products["product_id"].isin(product_ids)]


def get_sellers(seller_ids: list[str]) -> pd.DataFrame:
    data = load_data()
    return data.sellers[data.sellers["seller_id"].isin(seller_ids)]


def category_name_english(category_name_pt: str | None) -> str | None:
    if not category_name_pt or (isinstance(category_name_pt, float)):
        return None
    data = load_data()
    row = data.category_translation[
        data.category_translation["product_category_name"] == category_name_pt
    ]
    if row.empty:
        return category_name_pt
    return row.iloc[0]["product_category_name_english"]


def get_related_order_ids(customer_unique_id: str, exclude_order_id: str) -> list[str]:
    """Other order_ids belonging to the same customer_unique_id (repeat-customer history)."""
    data = load_data()
    cust_ids = data.customers[
        data.customers["customer_unique_id"] == customer_unique_id
    ]["customer_id"]
    related_orders = data.orders[
        data.orders["customer_id"].isin(cust_ids)
        & (data.orders["order_id"] != exclude_order_id)
    ]
    return related_orders["order_id"].tolist()
