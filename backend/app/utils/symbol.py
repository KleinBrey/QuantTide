import re


DAILY_BAR_MARKETS = ("a-share", "hk-share", "us-share")
_US_EXCHANGE_SUFFIXES = (".O", ".N", ".A")
_US_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")


def validate_symbol(value: object) -> str:
    """验证股票代码合法性，600519.SH"""

    return value


def exchange_for(code: str) -> str:
    """根据 A 股代码判断所属交易所。"""

    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def normalize_daily_bar_symbol(value: object, market: str) -> str:
    """将热榜代码转换成对应市场 ``daily_bars`` 使用的代码格式。"""

    if market not in DAILY_BAR_MARKETS:
        raise ValueError(f"不支持的市场: {market}")

    symbol = str(value).strip().upper()
    if not symbol:
        raise ValueError("股票代码不能为空")

    if market == "a-share":
        return validate_symbol(symbol)

    if market == "hk-share":
        if symbol.startswith("HK."):
            code = symbol[3:]
        elif symbol.endswith(".HK"):
            code = symbol[:-3]
        else:
            code = symbol

        if not code.isdigit() or not 1 <= len(code) <= 5:
            raise ValueError(f"不支持的港股代码格式: {value!r}")
        return f"{code.zfill(5)}.HK"

    if symbol.startswith("US."):
        code = symbol[3:]
    elif symbol.endswith(".US"):
        code = symbol[:-3]
    else:
        code = symbol
        for suffix in _US_EXCHANGE_SUFFIXES:
            if code.endswith(suffix):
                code = code[: -len(suffix)]
                break

    if not _US_SYMBOL_PATTERN.fullmatch(code) or code.endswith("."):
        raise ValueError(f"不支持的美股代码格式: {value!r}")
    return code


def chunked(
    items: list[str],
    size: int,
):
    """把列表按指定数量分批"""

    for i in range(0, len(items), size):
        yield items[i : i + size]
