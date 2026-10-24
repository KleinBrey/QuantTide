"""通达信行情最小连通性测试。"""

import pandas as pd

from backend.app.provider.tdx_provider import TdxProvider


def main() -> None:
    provider = TdxProvider()

    data = provider.fetch_index_constituents("000300.SH")["data"]["item"]

    frame = pd.DataFrame(data)

    print(f"共返回 {len(frame)} 条结果，以下展示前 20 条：\n{frame.head(20)}")


if __name__ == "__main__":
    main()
