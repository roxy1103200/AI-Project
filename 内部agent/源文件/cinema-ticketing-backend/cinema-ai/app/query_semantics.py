"""Shared deterministic business meanings for planning and answer verification."""

import re

MOVIE_FIELDS = {
    "director": ("导演", "谁拍", "谁导"),
    "duration": ("片长", "时长", "多长", "多久", "多少分钟"),
    "actors": ("主演", "演员"),
    "description": ("简介", "介绍", "剧情"),
    "release_date": ("上映日期", "上映时间"),
}
GENERAL_POLICY_WORDS = ("会员", "优惠", "折扣", "学生票", "积分", "优惠券")


def prose(question: str) -> str:
    """Remove quoted film names before interpreting business keywords."""
    return re.sub(r"《[^》]+》", "", question)


def movie_fields(question: str) -> list[str]:
    """Recognize requested film properties, including common conversational forms."""
    text = prose(question)
    fields = [field for field, words in MOVIE_FIELDS.items() if any(word in text for word in words)]
    if not re.search(r"片长|时长|多长|看多久|得看|多少分钟", text):
        fields = [field for field in fields if field != "duration"]
    return fields


def policy_kind(question: str) -> str:
    """Keep unsupported membership/promotion sources separate from ticket rules."""
    text = prose(question)
    general = any(word in text for word in GENERAL_POLICY_WORDS)
    ticket = bool(re.search(r"退票|退款|退钱|退改|购票须知|购票规则|取票规则", text))
    return "mixed" if general and ticket else "general_policy" if general else "ticket_policy"


def query_domains(question: str, has_order: bool = False) -> set[str]:
    """Disambiguate an order's amount from a new screening price lookup."""
    text = prose(question)
    domains = set()
    if has_order or re.search(r"订单|单号|我的票|购票记录|买的那张票", text):
        domains.add("order")
    if movie_fields(question):
        domains.add("movies")
    if re.search(r"座位|空座|空位|选座|余座|几个座|占上|(?:还剩|还空|空着|剩下).{0,5}(?:座|位)", text):
        domains.add("seats")
    slot_text = re.sub(r"场次\s*(?:编号|ID|id|号)?\s*[:：#]?\s*\d+|\d+\s*(?:这一?场|号场|场次)", "", text)
    if re.search(
        r"场次|排期|排片|排场|排(?:了)?[啥哪]场|排上了|票价|哪几场|几号场|安排.*影院|电影院.*放[啥哪].*片", slot_text
    ):
        domains.add("screenings")
    if not has_order and not movie_fields(question) and re.search(r"多少钱|几点开演|开场时间", text):
        domains.add("screenings")
    if re.search(
        r"规则|须知|政策|退票期限|退票截止|提前多久|最晚.*(?:分钟|多久)|啥时候不能退|退票.*提前.*(?:分钟|多久)", text
    ):
        domains.add("policy")
    if any(word in text for word in GENERAL_POLICY_WORDS):
        domains.add("general_policy")
    if re.search(r"推荐|喜欢|适合", text):
        domains.add("recommend")
    return domains
