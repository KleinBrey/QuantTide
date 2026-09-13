"""FastAPI 第 10 课：只读访问项目 DuckDB 的完整股票 API。"""

from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "data" / "cn_market.duckdb"


class Stock(BaseModel):
    symbol: str
    name: str
    exchange: str
    market: str


class Bar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float | None = None


class BarsResponse(BaseModel):
    symbol: str
    rows: list[Bar]


class MarketRepository:
    """所有连接都是只读连接，用完立即关闭。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def search_stocks(self, query: str | None, limit: int) -> list[dict]:
        sql = "SELECT symbol, name, exchange, market FROM stocks"
        parameters: list[object] = []

        if query:
            sql += " WHERE symbol ILIKE ? OR name ILIKE ?"
            wildcard = f"%{query.strip()}%"
            parameters.extend([wildcard, wildcard])

        sql += " ORDER BY symbol LIMIT ?"
        parameters.append(limit)
        return self._query(sql, parameters)

    def get_bars(
        self,
        symbol: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[dict]:
        clauses = ["symbol = ?"]
        parameters: list[object] = [symbol]

        if start_date:
            clauses.append("date >= ?")
            parameters.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            parameters.append(end_date)

        parameters.append(limit)
        sql = f"""
            SELECT date, open, high, low, close, volume, amount
            FROM daily_bars
            WHERE {' AND '.join(clauses)}
            ORDER BY date DESC
            LIMIT ?
        """
        return self._query(sql, parameters)

    def _query(self, sql: str, parameters: list[object]) -> list[dict]:
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            result = connection.execute(sql, parameters)
            columns = [description[0] for description in result.description]
            return [dict(zip(columns, row)) for row in result.fetchall()]
        finally:
            connection.close()


repository = MarketRepository(DATABASE_PATH)


def get_repository() -> MarketRepository:
    return repository


Repository = Annotated[MarketRepository, Depends(get_repository)]
app = FastAPI(title="本地 A 股行情 API", version="1.0.0")


def normalize_symbol(value: str) -> str:
    """cn_market.duckdb 使用六位代码，所以完整 thscode 只保留点号前部分。"""

    symbol = value.strip().upper().split(".")[0]
    if len(symbol) != 6 or not symbol.isdigit():
        raise HTTPException(status_code=422, detail="股票代码应为 6 位数字")
    return symbol


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "database_exists": DATABASE_PATH.exists()}


@app.get("/api/stocks", response_model=list[Stock])
def list_stocks(
    repository: Repository,
    query: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    return repository.search_stocks(query, limit)


@app.get("/api/market/bars/{symbol}", response_model=BarsResponse)
def get_bars(
    symbol: str,
    repository: Repository,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(20, ge=1, le=500),
) -> dict:
    normalized = normalize_symbol(symbol)
    rows = repository.get_bars(normalized, start_date, end_date, limit)
    if not rows:
        raise HTTPException(status_code=404, detail=f"没有 {normalized} 的本地日 K")
    return {"symbol": normalized, "rows": rows}


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"数据库不存在：{DATABASE_PATH}")

    client = TestClient(app)
    stocks_response = client.get("/api/stocks", params={"query": "茅台"})
    print("股票搜索：", stocks_response.status_code, stocks_response.json())

    bars_response = client.get("/api/market/bars/000001", params={"limit": 2})
    print("\n日 K 查询：", bars_response.status_code)
    print(bars_response.json())

# 可用 README 中的 uvicorn 命令，把模块名改为 10_stock_api_project 后启动此应用。
