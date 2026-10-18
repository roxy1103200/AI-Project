"""Extract ticket budgets as decimal amounts, independently of genre preferences."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

PRICE_FIELDS = ("max_ticket_price", "price_upper_inclusive")
AMOUNT = r"(?P<amount>\d+(?:\.\d{1,2})?)\s*(?:块钱|块|元)"
CLEAR_PRICE = re.compile(r"不限(?:制)?(?:票价|价格|预算)|(?:票价|价格|预算)不限|不限制价格|取消(?:票价|价格|预算)(?:限制)?")
UPPER_PRICE = re.compile(
    rf"(?:不超过|不高于|不大于|最多|至多|低于|不到|少于|预算(?:是|为)?\s*){AMOUNT}"
    rf"|{AMOUNT.replace('amount', 'suffix_amount')}\s*(?:以内|以下|之内|封顶)"
)


def price_followup(question: str) -> bool:
    """Only inherit query context for an explicit budget correction."""
    return bool(CLEAR_PRICE.search(question) or re.fullmatch(
        rf"(?:那|改成|换成|预算改为|预算改成)\s*{AMOUNT}(?:以内|以下)?(?:呢)?[？?。]?",
        question.strip(),
    ))


def ticket_budget(question: str) -> tuple[str | None, bool, bool]:
    """Return amount, inclusive boundary, and whether the user changed the budget."""
    if CLEAR_PRICE.search(question):
        return None, True, True
    matches = list(UPPER_PRICE.finditer(question))
    if not matches and price_followup(question):
        match = re.search(AMOUNT, question)
        matches = [match] if match else []
    if not matches:
        return None, True, False
    limits = []
    for match in matches:
        raw = match.groupdict().get("amount") or match.groupdict().get("suffix_amount")
        amount = Decimal(raw)
        inclusive = not bool(re.search(r"低于|不到|少于", match[0]))
        limits.append((amount, inclusive))
    amount, inclusive = min(limits)
    return format(amount, ".2f"), inclusive, True


def invalid_ticket_budget(question: str) -> bool:
    """Do not silently reinterpret a negative or overprecise money amount."""
    for raw in re.findall(r"(-?\d+(?:\.\d+)?)\s*(?:块钱|块|元)", question):
        amount = Decimal(raw)
        if amount < 0 or amount > 1_000_000 or amount.as_tuple().exponent < -2:
            return True
    return False


def unsupported_ticket_budget(question: str) -> bool:
    """Ask before converting an unsupported range or total into a per-ticket ceiling."""
    money = r"\d+(?:\.\d+)?\s*(?:块钱|块|元)"
    return bool(
        re.search(rf"(?:不低于|不少于|不要低于|至少|(?<!不)高于|(?<!不)大于|(?<!不)超过)\s*{money}|{money}\s*(?:以上|左右)", question)
        or re.search(rf"\d+(?:\.\d+)?\s*(?:元|块钱|块)?\s*[-~～至到]\s*{money}", question)
        or re.search(r"总预算|总共|一共|[二两三四五六七八九十2-9]\s*张", question) and re.search(money, question)
        or re.search(r"[一二两三四五六七八九十百]+\s*(?:元|块钱|块)\s*(?:以内|以下)", question)
    )


def price_arguments(entities: dict[str, Any]) -> dict[str, Any]:
    if entities.get("max_ticket_price") is None:
        return {}
    return {"max_ticket_price": entities["max_ticket_price"],
            "price_upper_inclusive": entities.get("price_upper_inclusive", True)}


def valid_ticket_prices(rows: list[dict[str, Any]], entities: dict[str, Any]) -> bool:
    """Reject missing evidence and every displayed slot exceeding the user budget."""
    if entities.get("max_ticket_price") is None:
        return True
    maximum = Decimal(str(entities["max_ticket_price"]))
    for row in rows:
        slots = row.get("screenings")
        if not isinstance(slots, list) or not slots:
            return False
        for slot in slots:
            try:
                price = Decimal(str(slot["price"]))
                if not price.is_finite() or price < 0 or price > maximum:
                    return False
                if price == maximum and not entities.get("price_upper_inclusive", True):
                    return False
            except (KeyError, TypeError, InvalidOperation):
                return False
    return True
