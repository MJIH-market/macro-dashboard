"""
매크로 지표 대시보드 생성 스크립트
- 지표별로 소스를 우선순위대로 시도하고, 모두 실패하면 직전 저장 데이터를 사용한다.
- 결과: data/*.csv (지표별 시계열), docs/index.html (대시보드)
"""
import io
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests

YEARS = 5
TODAY = pd.Timestamp.today().normalize()
START = TODAY - pd.DateOffset(years=YEARS)
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
DOCS_DIR = os.path.join(BASE, "docs")
UA = {"User-Agent": "Mozilla/5.0 (macro-dashboard)"}
KST = timezone(timedelta(hours=9))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("macro")

# ---------------------------------------------------------------------------
# 지표 정의: sources는 우선순위 순서. kind = level(%) | rate(bp)
# ---------------------------------------------------------------------------
INDICATORS = [
    dict(key="SPX", name="S&P 500", group="주가지수", unit="pt", kind="level",
         sources=[("fred", "SP500"), ("yahoo", "^GSPC")]),
    dict(key="NDX", name="나스닥100", group="주가지수", unit="pt", kind="level",
         sources=[("fred", "NASDAQ100"), ("yahoo", "^NDX")]),
    dict(key="USDKRW", name="원/달러", group="환율", unit="원", kind="level",
         sources=[("ecos", "731Y001/0000001"), ("yahoo", "KRW=X"), ("fred", "DEXKOUS")]),
    dict(key="USDJPY", name="엔/달러", group="환율", unit="엔", kind="level",
         sources=[("yahoo", "JPY=X"), ("fred", "DEXJPUS")]),
    dict(key="DXY", name="달러인덱스", group="환율", unit="pt", kind="level",
         sources=[("yahoo", "DX-Y.NYB")]),
    dict(key="UST2", name="미국채 2년", group="금리", unit="%", kind="rate",
         sources=[("fred", "DGS2")]),
    dict(key="UST10", name="미국채 10년", group="금리", unit="%", kind="rate",
         sources=[("fred", "DGS10")]),
    dict(key="JGB30", name="일본국채 30년", group="금리", unit="%", kind="rate",
         sources=[("mof", "30Y")]),
    dict(key="WTI", name="WTI 선물", group="원자재", unit="$/bbl", kind="level",
         sources=[("yahoo", "CL=F")]),
    dict(key="GOLD", name="금 선물", group="원자재", unit="$/oz", kind="level",
         sources=[("yahoo", "GC=F")]),
    dict(key="VIX", name="VIX", group="위험지표", unit="pt", kind="level",
         sources=[("fred", "VIXCLS"), ("yahoo", "^VIX")]),
]

SOURCE_LABEL = {
    "fred": ("FRED", "공식"),
    "ecos": ("한국은행 ECOS", "공식"),
    "mof": ("일본 재무성", "공식"),
    "yahoo": ("Yahoo Finance", "비공식"),
}


# ---------------------------------------------------------------------------
# 소스별 수집 함수: 모두 날짜 인덱스(tz-naive)의 float Series 반환
# ---------------------------------------------------------------------------
def fetch_fred(series_id):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY 미설정")
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params=dict(series_id=series_id, api_key=key, file_type="json",
                    observation_start=START.strftime("%Y-%m-%d")),
        timeout=30,
    )
    r.raise_for_status()
    obs = r.json()["observations"]
    data = {pd.Timestamp(o["date"]): float(o["value"])
            for o in obs if o["value"] not in (".", "")}
    return pd.Series(data, dtype=float)


def fetch_ecos(code):
    key = os.environ.get("ECOS_API_KEY")
    if not key:
        raise RuntimeError("ECOS_API_KEY 미설정")
    stat, item = code.split("/")
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/"
           f"{stat}/D/{START:%Y%m%d}/{TODAY:%Y%m%d}/{item}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    body = r.json()
    if "StatisticSearch" not in body:
        raise RuntimeError(f"ECOS 응답 오류: {body.get('RESULT', body)}")
    rows = body["StatisticSearch"]["row"]
    data = {pd.Timestamp(row["TIME"]): float(row["DATA_VALUE"].replace(",", ""))
            for row in rows if row.get("DATA_VALUE") not in (None, "", "-")}
    return pd.Series(data, dtype=float)


def fetch_yahoo(ticker):
    import yfinance as yf
    df = yf.download(ticker, start=START.strftime("%Y-%m-%d"),
                     progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError("Yahoo 응답 없음")
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna().astype(float)
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s


MOF_URLS = [
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv",
]


def _decode(raw):
    for enc in ("utf-8-sig", "shift_jis", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def fetch_mof(tenor):
    parts, errors = [], []
    for url in MOF_URLS:  # 과거 전체(전월까지) + 당월 파일
        try:
            r = requests.get(url, timeout=60, headers=UA)
            r.raise_for_status()
            lines = _decode(r.content).splitlines()
            head = next(i for i, l in enumerate(lines) if l.strip().lower().startswith("date"))
            df = pd.read_csv(io.StringIO("\n".join(lines[head:])))
            df.columns = [str(c).strip() for c in df.columns]
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"])
            s = pd.to_numeric(df[tenor], errors="coerce")
            s.index = df["Date"]
            parts.append(s.dropna())
        except Exception as e:  # 한 파일 실패는 허용
            errors.append(f"{url.rsplit('/', 1)[-1]}: {e}")
    if not parts:
        raise RuntimeError("; ".join(errors))
    s = pd.concat(parts)
    return s[~s.index.duplicated(keep="last")]


FETCHERS = {"fred": fetch_fred, "ecos": fetch_ecos, "yahoo": fetch_yahoo, "mof": fetch_mof}


# ---------------------------------------------------------------------------
# 수집 + 저장 데이터 병합
# ---------------------------------------------------------------------------
def load_saved(key):
    path = os.path.join(DATA_DIR, f"{key}.csv")
    if not os.path.exists(path):
        return None, None
    df = pd.read_csv(path, parse_dates=["date"])
    src = df["source"].iloc[-1] if "source" in df and len(df) else None
    return df.set_index("date")["value"].astype(float), src


def save(key, s, src):
    os.makedirs(DATA_DIR, exist_ok=True)
    out = pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.values, "source": src})
    out.to_csv(os.path.join(DATA_DIR, f"{key}.csv"), index=False)


def collect(ind):
    errors = []
    for src, arg in ind["sources"]:
        try:
            s = FETCHERS[src](arg)
            s = s.sort_index()
            s = s[s.index >= START]
            if len(s) < 20:
                raise RuntimeError(f"데이터 부족({len(s)}건)")
            tag = f"{src}:{arg}"
            save(ind["key"], s, tag)
            log.info("OK   %-7s %s (%d건, 최종 %s)", ind["key"], tag, len(s), s.index[-1].date())
            return s, tag, "live", errors
        except Exception as e:
            errors.append(f"{src}:{arg} → {e}")
            log.warning("FAIL %-7s %s:%s → %s", ind["key"], src, arg, e)
    saved, tag = load_saved(ind["key"])
    if saved is not None and len(saved):
        return saved, tag, "cached", errors
    return None, None, "failed", errors


def change(s, days, kind):
    last_date, last = s.index[-1], s.iloc[-1]
    base = s.asof(last_date - pd.Timedelta(days=days))
    if pd.isna(base):
        return None
    return round((last - base) * 100, 1) if kind == "rate" else round((last / base - 1) * 100, 2)


def build_payload():
    items = []
    for ind in INDICATORS:
        s, tag, status, errors = collect(ind)
        item = {k: ind[k] for k in ("key", "name", "group", "unit", "kind")}
        item.update(status=status, errors=errors)
        if s is not None:
            src = tag.split(":", 1)[0] if tag else ""
            label, nature = SOURCE_LABEL.get(src, (src, ""))
            primary = ind["sources"][0][0]
            item.update(
                dates=s.index.strftime("%Y-%m-%d").tolist(),
                values=[round(float(v), 4) for v in s.values],
                last=round(float(s.iloc[-1]), 4),
                last_date=s.index[-1].strftime("%Y-%m-%d"),
                stale=(TODAY - s.index[-1]).days > 7,
                d1=change(s, 1, ind["kind"]), m1=change(s, 30, ind["kind"]),
                y1=change(s, 365, ind["kind"]),
                source=f"{label} {tag.split(':', 1)[1] if tag else ''}".strip(),
                nature=nature, fallback=(src != primary),
            )
        items.append(item)
    return {"generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "items": items}


def render(payload):
    with open(os.path.join(BASE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    payload = build_payload()
    render(payload)
    ok = sum(i["status"] == "live" for i in payload["items"])
    log.info("완료: 신규 %d / 전체 %d → docs/index.html", ok, len(payload["items"]))
