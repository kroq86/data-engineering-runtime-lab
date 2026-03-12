from __future__ import annotations

import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable


def declared_heuristics() -> dict[str, dict[str, Any]]:
    return {
        "pain_structure": {
            "description": "Cluster recurring pain themes from text-heavy Telegram exports.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["cluster_summary", "example_messages"],
        },
        "naive_bias": {
            "description": "Find over-generalization patterns and naive-bias candidate claims.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["pattern_counts", "example_messages"],
        },
        "price_distribution": {
            "description": "Extract sale-like price mentions and build rough category price bands.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["price_stats", "category_price_stats"],
        },
        "liquidity_signals": {
            "description": "Estimate message-level liquidity using offer/status heuristics.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["signal_ratios", "category_liquidity_summary"],
        },
        "price_liquidity_matrix": {
            "description": "Cross price bands with message-level liquidity signals by category.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["price_band_liquidity", "category_band_matrix"],
        },
        "cross_category": {
            "description": "Compare sale, buy, and status activity across coarse content categories.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["category_market_matrix", "category_demand_supply"],
        },
        "sale_format": {
            "description": "Measure which structural sale-post fields are present across offer messages.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["field_prevalence", "format_examples"],
        },
        "speed_signals": {
            "description": "Estimate speed-related pressure and closure proxies for sale offers.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["speed_signal_summary", "band_speed_matrix"],
        },
        "trust_signals": {
            "description": "Estimate buyer trust cues and risk markers in sale offers.",
            "supported_source_kinds": ["telegram_html_export"],
            "outputs": ["trust_signal_summary", "signal_examples"],
        },
    }


class TelegramHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict[str, str]] = []
        self.in_message = False
        self.message_depth = 0
        self.current: dict[str, Any] | None = None
        self.capture: str | None = None
        self.capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {k: v or "" for k, v in attrs}
        if tag == "div":
            classes = attrs_map.get("class", "").split()
            if not self.in_message and {"message", "default", "clearfix"}.issubset(
                set(classes)
            ):
                self.in_message = True
                self.message_depth = 1
                self.current = {
                    "author": "Unknown",
                    "text_parts": [],
                    "date": attrs_map.get("title", ""),
                    "id": attrs_map.get("id", ""),
                }
                self.capture = None
                self.capture_depth = 0
                return
            if self.in_message:
                self.message_depth += 1
                if self.capture:
                    self.capture_depth += 1
                if "from_name" in classes:
                    self.capture = "author"
                    self.capture_depth = 1
                elif "text" in classes:
                    self.capture = "text"
                    self.capture_depth = 1
                elif "date" in classes and "title" in attrs_map:
                    assert self.current is not None
                    self.current["date"] = attrs_map["title"]
        elif self.in_message and self.capture == "text" and tag == "br":
            assert self.current is not None
            self.current["text_parts"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self.in_message:
            return
        if self.capture:
            self.capture_depth -= 1
            if self.capture_depth == 0:
                self.capture = None
        self.message_depth -= 1
        if self.message_depth == 0:
            assert self.current is not None
            text = re.sub(r"\s+", " ", "".join(self.current["text_parts"])).strip()
            author = re.sub(r"\s+", " ", self.current["author"]).strip() or "Unknown"
            if text:
                self.messages.append(
                    {
                        "author": author,
                        "text": text,
                        "date": str(self.current["date"]),
                        "id": str(self.current["id"]),
                    }
                )
            self.in_message = False
            self.current = None
            self.capture = None
            self.capture_depth = 0

    def handle_data(self, data: str) -> None:
        if not self.in_message or not self.capture or self.current is None:
            return
        if self.capture == "author":
            self.current["author"] += data
        elif self.capture == "text":
            self.current["text_parts"].append(data)


def _telegram_files(source_path: Path) -> list[Path]:
    if source_path.is_dir():
        return sorted(
            source_path.glob("messages*.html"),
            key=lambda p: int(re.search(r"(\d+)", p.stem).group(1))
            if re.search(r"(\d+)", p.stem)
            else 1,
        )
    if source_path.is_file():
        return [source_path]
    raise FileNotFoundError(source_path)


def load_telegram_messages(source_path: str) -> list[dict[str, str]]:
    path = Path(source_path)
    messages: list[dict[str, str]] = []
    for file in _telegram_files(path):
        parser = TelegramHTMLParser()
        parser.feed(file.read_text(encoding="utf-8", errors="ignore"))
        for row in parser.messages:
            row["file"] = file.name
        messages.extend(parser.messages)
    return messages


PAIN_PATTERNS = {
    "market_access_cost": [r"достав", r"растамож", r"тамож", r"пошлин", r"import", r"shipping", r"дорог", r"цена", r"лари"],
    "infrastructure_access": [r"репет", r"репточ", r"студи", r"база", r"зал", r"помещен"],
    "collaboration_matching": [r"ищу.*(музыкант|барабан|гитар|басист|вокал)", r"нужен.*(музыкант|барабан|гитар|басист|вокал)", r"коллаб", r"собрать группу"],
    "recording_production": [r"запис", r"сведение", r"мастер", r"интерфейс", r"звукарь", r"микрофон"],
    "marketplace_liquidity": [r"продам", r"продаю", r"куплю", r"купит", r"барахол", r"рынок", r"магазин", r"налич"],
}
PRICE_PATTERNS = [
    re.compile(r"(\d{2,7})\s*(лари|gel|₾)\b", re.I),
    re.compile(r"\$(\d{2,7})\b", re.I),
    re.compile(r"(\d{2,7})\s*\$", re.I),
]
SALE_OFFER_PATTERNS = [r"\bпродаю\b", r"\bпродам\b", r"\bраспродаю\b", r"\bотдам\b", r"\bотдаю\b", r"\bобменяю\b", r"\bобмен\b"]
BUY_PATTERNS = [r"\bкуплю\b", r"\bищу\b"]
STATUS_PATTERNS = [r"\bпродано\b", r"\bпродан\b", r"\bsold\b", r"\bбронь\b", r"\bзабронировано\b", r"\bснято\b", r"\bзабрали\b", r"\bзабрал[иа]?\b"]
LOCATION_PATTERNS = [r"\bтбилиси\b", r"\bбатуми\b", r"\bсабуртал", r"\bваке\b", r"\bисани\b", r"\bдигоми\b", r"\bрустaв", r"\bсамовывоз\b"]
CONDITION_PATTERNS = [r"состояни", r"\bнов(ый|ая|ое|ые)\b", r"\bидеал", r"\bкак нов", r"\bбу\b", r"\b8/10\b", r"\b9/10\b", r"\b10/10\b", r"дефект", r"царап"]
CONTACT_PATTERNS = [r"\bлс\b", r"\bличк", r"\bdm\b", r"direct", r"пишите", r"связ", r"telegram", r"whatsapp"]
MEDIA_PATTERNS = [r"фото", r"видео", r"фотк", r"пришлю фото"]
DELIVERY_PATTERNS = [r"достав", r"курьер", r"подвез", r"отправ"]
REASON_PATTERNS = [r"переезд", r"отъезд", r"срочно", r"не подош", r"не польз", r"распрода"]
RECEIPT_PATTERNS = [r"чек", r"гаранти", r"коробк", r"документ"]
AUTHENTICITY_PATTERNS = [r"оригинал", r"original", r"подлинн"]
CHECK_PATTERNS = [r"можно проверить", r"проверить", r"тест", r"осмотр"]
DISCOUNT_PATTERNS = [r"торг", r"скидк", r"дешевле", r"цена ниже", r"отдам за"]
URGENCY_PATTERNS = [r"срочно", r"сегодня", r"завтра", r"до \d+", r"переезд", r"отъезд"]
RISK_PATTERNS = [r"предоплат", r"фейк", r"мошенн", r"кид(а|ок)", r"без проверки"]
MARKET_TERMS = [r"рын(ок|ка)", r"сцен", r"музык", r"грузи", r"тбилиси", r"батуми", r"заработ", r"концерт", r"гиг", r"репточ"]
GENERALIZATION_TERMS = [r"\bвсе\b", r"\bникто\b", r"\bникому\b", r"\bвсегда\b", r"\bникогда\b", r"\bневозможно\b", r"\bнет\b", r"\bникак\b", r"\bлюбой\b"]
NAIVE_CATEGORIES = {
    "market_absence_claim": [r"рын(ка|ок).{0,20}нет", r"сцен(ы|а).{0,20}нет", r"нет.{0,20}(рынка|сцены)"],
    "everyone_nobody_claim": [r"\bвсе\b.{0,40}(музыкан|игра|ищут|хотят)", r"\bникто\b.{0,40}(не )?(ходит|слуша|игра|платит)", r"\bникому\b.{0,40}(не )?(нужн|интересн)"],
    "economic_impossibility_claim": [r"невозможно.{0,50}(заработ|жить|снимать)", r"не заработа", r"все дорого", r"слишком дорого"],
    "infrastructure_totalizing_claim": [r"нет.{0,40}(репточ|студи|магазин)", r"в грузии.{0,40}нет", r"в тбилиси.{0,40}нет"],
}
CATEGORY_PATTERNS = {
    "electronics": [r"iphone", r"macbook", r"ноутбук", r"laptop", r"телефон", r"смартфон", r"ipad", r"airpods", r"playstation", r"xbox", r"монитор", r"камера", r"объектив", r"видеокарт"],
    "clothing_shoes": [r"куртк", r"кроссов", r"ботин", r"плать", r"футбол", r"джинс", r"брюк", r"обув", r"кеды", r"сапог", r"размер"],
    "home_furniture": [r"диван", r"стол", r"стул", r"кресл", r"матрас", r"шкаф", r"тумб", r"зеркал", r"ламп", r"кровать", r"комод"],
    "appliances_household": [r"пылесос", r"утюг", r"чайник", r"блендер", r"кофемаш", r"микроволнов", r"холодильник", r"стирал", r"посуда", r"фен"],
    "baby_kids": [r"детск", r"коляск", r"игрушк", r"кроватк", r"малыш", r"ребенк"],
    "pets": [r"кот", r"кошка", r"собак", r"корм", r"переноск", r"когтеточ"],
    "sports_outdoor": [r"велосипед", r"самокат", r"ролик", r"спорт", r"рюкзак", r"палатк", r"лыж"],
    "books_hobby": [r"книг", r"энциклопед", r"настолк", r"lego", r"пазл"],
}


def _classify_category(text: str) -> str:
    lower = text.lower()
    for category, patterns in CATEGORY_PATTERNS.items():
        if any(re.search(pattern, lower) for pattern in patterns):
            return category
    return "other"


def _extract_prices(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for pattern in PRICE_PATTERNS:
        for match in pattern.finditer(text):
            amount = int(match.group(1))
            if not (20 <= amount <= 200000):
                continue
            currency = "GEL" if ("лари" in match.group(0).lower() or "gel" in match.group(0).lower() or "₾" in match.group(0)) else "USD"
            out.append((amount, currency))
    return out


def _stats(values: list[int]) -> dict[str, int] | None:
    if not values:
        return None
    values = sorted(values)
    return {"count": len(values), "min": values[0], "median": values[len(values) // 2], "p75": values[(len(values) * 3) // 4], "max": values[-1]}


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _collect_sale_offers(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    sale_offers: list[dict[str, Any]] = []
    index_map: dict[tuple[str, str, str, str], int] = {}
    for idx, msg in enumerate(messages):
        index_map[(msg["author"], msg["text"], msg["date"], msg["file"])] = idx
        lower = msg["text"].lower()
        if _has_any(lower, SALE_OFFER_PATTERNS):
            sale_offers.append({**msg, "lower": lower, "category": _classify_category(msg["text"]), "prices": _extract_prices(msg["text"]), "has_inline_status": _has_any(lower, STATUS_PATTERNS), "author_followup_status": False})
    for offer in sale_offers:
        if offer["has_inline_status"]:
            continue
        idx = index_map.get((offer["author"], offer["text"], offer["date"], offer["file"]))
        if idx is None:
            continue
        for next_msg in messages[idx + 1 : idx + 6]:
            next_lower = next_msg["text"].lower()
            if next_msg["author"] == offer["author"] and _has_any(next_lower, STATUS_PATTERNS) and not _has_any(next_lower, SALE_OFFER_PATTERNS):
                offer["author_followup_status"] = True
                break
    return sale_offers


def _run_pain_structure(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    counter = Counter()
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    for msg in messages:
        lower = msg["text"].lower()
        for cluster, patterns in PAIN_PATTERNS.items():
            if _has_any(lower, patterns):
                counter[cluster] += 1
                if len(examples[cluster]) < max_examples:
                    examples[cluster].append({"author": msg["author"], "text": msg["text"][:220], "file": msg["file"]})
    total = sum(counter.values()) or 1
    return {"message_count": len(messages), "cluster_count": len(counter), "clusters": [{"cluster_id": cluster, "count": count, "share_of_matches": round(count / total, 4), "examples": examples[cluster]} for cluster, count in counter.most_common()]}


def _run_naive_bias(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    candidate_count = 0
    counter = Counter()
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    for msg in messages:
        lower = msg["text"].lower()
        if _has_any(lower, MARKET_TERMS) and _has_any(lower, GENERALIZATION_TERMS):
            candidate_count += 1
            for pattern_id, patterns in NAIVE_CATEGORIES.items():
                if _has_any(lower, patterns):
                    counter[pattern_id] += 1
                    if len(examples[pattern_id]) < max_examples:
                        examples[pattern_id].append({"author": msg["author"], "text": msg["text"][:260], "file": msg["file"]})
    return {"message_count": len(messages), "candidate_message_count": candidate_count, "patterns": [{"pattern_id": pattern_id, "count": count, "examples": examples[pattern_id]} for pattern_id, count in counter.most_common()]}


def _run_price_distribution(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    sale_offers = []
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "examples": [], "gel": [], "usd": []})
    all_gel: list[int] = []
    all_usd: list[int] = []
    for msg in messages:
        lower = msg["text"].lower()
        if not _has_any(lower, SALE_OFFER_PATTERNS):
            continue
        category = _classify_category(msg["text"])
        prices = _extract_prices(msg["text"])
        sale_offers.append(msg)
        row = by_category[category]
        row["count"] += 1
        if len(row["examples"]) < max_examples:
            row["examples"].append({"author": msg["author"], "text": msg["text"][:220], "file": msg["file"]})
        for amount, currency in prices:
            if currency == "GEL":
                row["gel"].append(amount)
                all_gel.append(amount)
            else:
                row["usd"].append(amount)
                all_usd.append(amount)
    return {"message_count": len(messages), "sale_offer_count": len(sale_offers), "gel_overall": _stats(all_gel), "usd_overall": _stats(all_usd), "categories": [{"category": category, "count": payload["count"], "examples": payload["examples"], "gel_stats": _stats(payload["gel"]), "usd_stats": _stats(payload["usd"])} for category, payload in sorted(by_category.items(), key=lambda item: item[1]["count"], reverse=True)]}


def _run_liquidity_signals(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    sale_offers = _collect_sale_offers(messages)
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"offers": 0, "strong": 0, "weak": 0, "examples_strong": [], "examples_weak": [], "gel_prices": []})
    for offer in sale_offers:
        row = by_category[offer["category"]]
        row["offers"] += 1
        if offer["has_inline_status"]:
            row["strong"] += 1
            if len(row["examples_strong"]) < max_examples:
                row["examples_strong"].append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
        elif offer["author_followup_status"]:
            row["weak"] += 1
            if len(row["examples_weak"]) < max_examples:
                row["examples_weak"].append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
        for amount, currency in offer["prices"]:
            if currency == "GEL":
                row["gel_prices"].append(amount)
    top_categories = [{"category": category, "offers": row["offers"], "strong_status_signals": row["strong"], "weak_status_signals": row["weak"], "strong_signal_ratio": round(row["strong"] / row["offers"], 4) if row["offers"] else 0.0, "all_signal_ratio": round((row["strong"] + row["weak"]) / row["offers"], 4) if row["offers"] else 0.0, "gel_stats": _stats(row["gel_prices"]), "examples_strong": row["examples_strong"], "examples_weak": row["examples_weak"]} for category, row in by_category.items()]
    top_categories.sort(key=lambda item: (item["all_signal_ratio"], item["offers"]), reverse=True)
    overall = {"offer_count": len(sale_offers), "strong_status_offer_count": sum(1 for item in sale_offers if item["has_inline_status"]), "weak_status_offer_count": sum(1 for item in sale_offers if item["author_followup_status"])}
    offer_count = overall["offer_count"] or 1
    overall["strong_signal_ratio"] = round(overall["strong_status_offer_count"] / offer_count, 4)
    overall["all_signal_ratio"] = round((overall["strong_status_offer_count"] + overall["weak_status_offer_count"]) / offer_count, 4)
    return {"message_count": len(messages), "liquidity_method": {"strong_signal": "status marker appears inside sale offer text", "weak_signal": "same author posts status-only update within next 5 messages", "caveat": "Heuristic liquidity signal, not true thread-linked sell-through."}, "overall": overall, "top_liquidity_categories": top_categories[:10], "top_volume_categories": sorted(top_categories, key=lambda item: item["offers"], reverse=True)[:10]}


def _price_band_gel(amount: int) -> str:
    if amount < 50:
        return "<50"
    if amount < 100:
        return "50-99"
    if amount < 250:
        return "100-249"
    if amount < 500:
        return "250-499"
    if amount < 1000:
        return "500-999"
    return "1000+"


def _run_price_liquidity_matrix(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    sale_offers = _collect_sale_offers(messages)
    band_summary: dict[str, dict[str, Any]] = defaultdict(lambda: {"offers": 0, "strong": 0, "weak": 0})
    category_band_summary: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"offers": 0, "strong": 0, "weak": 0, "examples": []}))
    for offer in sale_offers:
        gel_prices = [amount for amount, currency in offer["prices"] if currency == "GEL"]
        if not gel_prices:
            continue
        band = _price_band_gel(min(gel_prices))
        band_row = band_summary[band]
        band_row["offers"] += 1
        if offer["has_inline_status"]:
            band_row["strong"] += 1
        elif offer["author_followup_status"]:
            band_row["weak"] += 1
        category_row = category_band_summary[offer["category"]][band]
        category_row["offers"] += 1
        if offer["has_inline_status"]:
            category_row["strong"] += 1
        elif offer["author_followup_status"]:
            category_row["weak"] += 1
        if (offer["has_inline_status"] or offer["author_followup_status"]) and len(category_row["examples"]) < max_examples:
            category_row["examples"].append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
    band_order = ["<50", "50-99", "100-249", "250-499", "500-999", "1000+"]
    band_rows = [{"price_band_gel": band, "offers": row["offers"], "strong_status_signals": row["strong"], "weak_status_signals": row["weak"], "strong_signal_ratio": round(row["strong"] / (row["offers"] or 1), 4), "all_signal_ratio": round((row["strong"] + row["weak"]) / (row["offers"] or 1), 4)} for band, row in sorted(band_summary.items(), key=lambda item: band_order.index(item[0]))]
    category_rows = []
    for category, bands in category_band_summary.items():
        total_offers = sum(item["offers"] for item in bands.values())
        category_rows.append({"category": category, "offers": total_offers, "bands": [{"price_band_gel": band, "offers": row["offers"], "strong_status_signals": row["strong"], "weak_status_signals": row["weak"], "strong_signal_ratio": round(row["strong"] / (row["offers"] or 1), 4), "all_signal_ratio": round((row["strong"] + row["weak"]) / (row["offers"] or 1), 4), "examples": row["examples"]} for band, row in sorted(bands.items(), key=lambda item: band_order.index(item[0]))]})
    category_rows.sort(key=lambda item: item["offers"], reverse=True)
    return {"message_count": len(messages), "band_summary": band_rows, "category_band_matrix": category_rows[:10], "note": "Price x liquidity matrix uses GEL offer price bands crossed with heuristic status signals."}


def _run_cross_category(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    by_category: dict[str, dict[str, Any]] = defaultdict(lambda: {"sale_offers": 0, "buy_requests": 0, "status_updates": 0, "examples_sale": [], "examples_buy": []})
    for msg in messages:
        lower = msg["text"].lower()
        category = _classify_category(msg["text"])
        row = by_category[category]
        if _has_any(lower, SALE_OFFER_PATTERNS):
            row["sale_offers"] += 1
            if len(row["examples_sale"]) < max_examples:
                row["examples_sale"].append({"author": msg["author"], "text": msg["text"][:220], "file": msg["file"]})
        if _has_any(lower, BUY_PATTERNS):
            row["buy_requests"] += 1
            if len(row["examples_buy"]) < max_examples:
                row["examples_buy"].append({"author": msg["author"], "text": msg["text"][:220], "file": msg["file"]})
        if _has_any(lower, STATUS_PATTERNS):
            row["status_updates"] += 1
    rows = [{"category": category, "sale_offers": row["sale_offers"], "buy_requests": row["buy_requests"], "status_updates": row["status_updates"], "demand_supply_ratio": round(row["buy_requests"] / (row["sale_offers"] or 1), 4), "status_offer_ratio": round(row["status_updates"] / (row["sale_offers"] or 1), 4), "examples_sale": row["examples_sale"], "examples_buy": row["examples_buy"]} for category, row in by_category.items()]
    rows.sort(key=lambda item: item["sale_offers"], reverse=True)
    return {"message_count": len(messages), "category_market_matrix": rows[:15]}


def _run_sale_format(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    sale_offers = _collect_sale_offers(messages)
    field_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    counter = Counter()
    combo_counter = Counter()
    field_map = {"price_present": lambda offer: bool(offer["prices"]), "location_present": lambda offer: _has_any(offer["lower"], LOCATION_PATTERNS), "condition_present": lambda offer: _has_any(offer["lower"], CONDITION_PATTERNS), "contact_present": lambda offer: _has_any(offer["lower"], CONTACT_PATTERNS), "media_present": lambda offer: _has_any(offer["lower"], MEDIA_PATTERNS), "delivery_present": lambda offer: _has_any(offer["lower"], DELIVERY_PATTERNS), "reason_present": lambda offer: _has_any(offer["lower"], REASON_PATTERNS)}
    for offer in sale_offers:
        present_fields = []
        for field_name, checker in field_map.items():
            if checker(offer):
                counter[field_name] += 1
                present_fields.append(field_name)
                if len(field_examples[field_name]) < max_examples:
                    field_examples[field_name].append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
        combo_counter[tuple(sorted(present_fields))] += 1
    offer_count = len(sale_offers) or 1
    return {"message_count": len(messages), "offer_count": len(sale_offers), "field_prevalence": [{"field": field, "count": count, "ratio": round(count / offer_count, 4)} for field, count in counter.most_common()], "top_field_combinations": [{"fields": list(combo), "count": count} for combo, count in combo_counter.most_common(10) if combo], "format_examples": dict(field_examples)}


def _run_speed_signals(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    sale_offers = _collect_sale_offers(messages)
    by_band: dict[str, dict[str, Any]] = defaultdict(lambda: {"offers": 0, "urgent": 0, "discount": 0, "status": 0, "examples": []})
    band_order = ["no_price", "<50", "50-99", "100-249", "250-499", "500-999", "1000+"]
    for offer in sale_offers:
        gel_prices = [amount for amount, currency in offer["prices"] if currency == "GEL"]
        band = _price_band_gel(min(gel_prices)) if gel_prices else "no_price"
        row = by_band[band]
        row["offers"] += 1
        urgent = _has_any(offer["lower"], URGENCY_PATTERNS)
        discount = _has_any(offer["lower"], DISCOUNT_PATTERNS)
        status_hit = offer["has_inline_status"] or offer["author_followup_status"]
        if urgent:
            row["urgent"] += 1
        if discount:
            row["discount"] += 1
        if status_hit:
            row["status"] += 1
        if (urgent or discount or status_hit) and len(row["examples"]) < max_examples:
            row["examples"].append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
    rows = [{"price_band_gel": band, "offers": row["offers"], "urgency_ratio": round(row["urgent"] / (row["offers"] or 1), 4), "discount_ratio": round(row["discount"] / (row["offers"] or 1), 4), "status_ratio": round(row["status"] / (row["offers"] or 1), 4), "examples": row["examples"]} for band, row in sorted(by_band.items(), key=lambda item: band_order.index(item[0]))]
    return {"message_count": len(messages), "offer_count": len(sale_offers), "speed_signal_summary": {"urgent_offer_count": sum(1 for offer in sale_offers if _has_any(offer["lower"], URGENCY_PATTERNS)), "discount_offer_count": sum(1 for offer in sale_offers if _has_any(offer["lower"], DISCOUNT_PATTERNS)), "status_offer_count": sum(1 for offer in sale_offers if offer["has_inline_status"] or offer["author_followup_status"])}, "band_speed_matrix": rows}


def _run_trust_signals(messages: list[dict[str, str]], *, max_examples: int) -> dict[str, Any]:
    sale_offers = _collect_sale_offers(messages)
    signals = {"condition_disclosure": CONDITION_PATTERNS, "location_disclosure": LOCATION_PATTERNS, "contact_path": CONTACT_PATTERNS, "media_available": MEDIA_PATTERNS, "receipt_or_warranty": RECEIPT_PATTERNS, "authenticity_claim": AUTHENTICITY_PATTERNS, "inspection_invite": CHECK_PATTERNS}
    positive_counts = Counter()
    positive_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    risk_examples: list[dict[str, str]] = []
    risk_count = 0
    for offer in sale_offers:
        for signal_name, patterns in signals.items():
            if _has_any(offer["lower"], patterns):
                positive_counts[signal_name] += 1
                if len(positive_examples[signal_name]) < max_examples:
                    positive_examples[signal_name].append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
        if _has_any(offer["lower"], RISK_PATTERNS):
            risk_count += 1
            if len(risk_examples) < max_examples:
                risk_examples.append({"author": offer["author"], "text": offer["text"][:220], "file": offer["file"]})
    offer_count = len(sale_offers) or 1
    return {"message_count": len(messages), "offer_count": len(sale_offers), "trust_signal_summary": [{"signal": signal, "count": count, "ratio": round(count / offer_count, 4)} for signal, count in positive_counts.most_common()], "risk_signal_count": risk_count, "signal_examples": {"positive": dict(positive_examples), "risk": risk_examples}}


HEURISTIC_RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "pain_structure": _run_pain_structure,
    "naive_bias": _run_naive_bias,
    "price_distribution": _run_price_distribution,
    "liquidity_signals": _run_liquidity_signals,
    "price_liquidity_matrix": _run_price_liquidity_matrix,
    "cross_category": _run_cross_category,
    "sale_format": _run_sale_format,
    "speed_signals": _run_speed_signals,
    "trust_signals": _run_trust_signals,
}
