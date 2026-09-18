
import os
import statistics
import datetime as dt
import requests
import streamlit as st

TIMEOUT = 12
HEADERS = {"User-Agent": "XRP-Market-Layers-WebApp/1.0"}

st.set_page_config(page_title="XRP Market Layers", page_icon="📊", layout="wide")

def get_json(url, params=None, headers=None):
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def post_json(url, payload):
    r = requests.post(url, json=payload, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def safe(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

def price_volume():
    data = get_json(
        "https://api.coingecko.com/api/v3/coins/ripple",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        },
    )
    md = data["market_data"]
    return {
        "price_usd": md["current_price"]["usd"],
        "change_24h_pct": md.get("price_change_percentage_24h"),
        "volume_24h_usd": md["total_volume"]["usd"],
        "market_cap_usd": md["market_cap"]["usd"],
    }

def coinbase_order_book():
    book = get_json("https://api.exchange.coinbase.com/products/XRP-USD/book", params={"level": 2})
    bids = [(float(p), float(q)) for p, q, *_ in book.get("bids", [])]
    asks = [(float(p), float(q)) for p, q, *_ in book.get("asks", [])]
    if not bids or not asks:
        raise RuntimeError("No order book data returned.")
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    spread_bps = ((best_ask - best_bid) / mid) * 10000

    bid_depth = sum(p*q for p, q in bids if p >= mid * 0.995)
    ask_depth = sum(p*q for p, q in asks if p <= mid * 1.005)

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": spread_bps,
        "bid_depth_usd": bid_depth,
        "ask_depth_usd": ask_depth,
    }

def xrpl_activity():
    info = post_json(
        "https://s1.ripple.com:51234/",
        {"method": "ledger", "params": [{"ledger_index": "validated", "transactions": True, "expand": False}]},
    )
    result = info.get("result", {})
    ledger = result.get("ledger", {})
    return {
        "ledger_index": ledger.get("ledger_index"),
        "tx_count": len(ledger.get("transactions", [])),
        "close_time_human": ledger.get("close_time_human"),
    }

def kraken_ticker():
    d = get_json("https://api.kraken.com/0/public/Ticker", params={"pair": "XRPUSD"})
    if d.get("error"):
        raise RuntimeError(d["error"])
    result = next(iter(d["result"].values()))
    return float(result["c"][0]), float(result["v"][1])

def coinbase_ticker():
    d = get_json("https://api.exchange.coinbase.com/products/XRP-USD/ticker")
    return float(d["price"]), float(d.get("volume", 0))

def cross_exchange():
    venues = []
    try:
        p, v = kraken_ticker()
        venues.append({"venue": "Kraken", "price": p, "volume_xrp": v})
    except Exception:
        pass
    try:
        p, v = coinbase_ticker()
        venues.append({"venue": "Coinbase", "price": p, "volume_xrp": v})
    except Exception:
        pass

    prices = [x["price"] for x in venues]
    spread_pct = None
    if len(prices) >= 2:
        spread_pct = (max(prices) - min(prices)) / statistics.mean(prices) * 100
    return {"venues": venues, "spread_pct": spread_pct}

def stablecoins():
    return get_json(
        "https://api.coingecko.com/api/v3/simple/price",
        params={
            "ids": "tether,usd-coin,ripple-usd",
            "vs_currencies": "usd",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        },
    )

def money(x):
    if x is None:
        return "n/a"
    return f"${x:,.4f}" if abs(x) < 100 else f"${x:,.0f}"

def status_badge(text):
    st.caption(text)

st.title("XRP Market Layers")
st.write(
    "A multi-layer market view based on price, liquidity, derivatives, on-chain activity, "
    "cross-exchange trading, stablecoin liquidity, whale activity, and confirmed catalysts."
)
st.info("This app reports market evidence. It does not generate a buy/sell recommendation.")

if st.button("Generate XRP Report", type="primary", use_container_width=True):
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Generated {generated}")

    pv = safe(price_volume)
    ob = safe(coinbase_order_book)
    xa = safe(xrpl_activity)
    ce = safe(cross_exchange)
    sc = safe(stablecoins)

    st.header("1. Price & Spot Volume")
    if "error" in pv:
        st.error(pv["error"])
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("XRP price", money(pv["price_usd"]))
        c2.metric("24h change", f"{pv['change_24h_pct']:.2f}%")
        c3.metric("24h volume", money(pv["volume_24h_usd"]))
        c4.metric("Market cap", money(pv["market_cap_usd"]))

    st.header("2. Order-Book Liquidity")
    if "error" in ob:
        st.error(ob["error"])
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Best bid", money(ob["best_bid"]))
        c2.metric("Best ask", money(ob["best_ask"]))
        c3.metric("Spread", f"{ob['spread_bps']:.2f} bps")
        c4, c5 = st.columns(2)
        c4.metric("Bid depth within 0.5%", money(ob["bid_depth_usd"]))
        c5.metric("Ask depth within 0.5%", money(ob["ask_depth_usd"]))

    st.header("3. Derivatives")
    if os.getenv("COINGLASS_API_KEY"):
        st.success("CoinGlass API key detected.")
        st.caption("Add the current CoinGlass XRP futures endpoints for your subscription plan.")
    else:
        st.warning("CoinGlass API key not configured. Open interest, funding, and liquidation data are not yet automated.")

    st.header("4. XRP Ledger Activity")
    if "error" in xa:
        st.error(xa["error"])
    else:
        c1, c2 = st.columns(2)
        c1.metric("Validated ledger", xa["ledger_index"] or "n/a")
        c2.metric("Transactions in latest ledger", xa["tx_count"])
        status_badge("Ledger activity confirms what moved on-chain, but not why a participant moved it.")

    st.header("5. Whale Movements")
    if os.getenv("WHALE_ALERT_API_KEY"):
        st.success("Whale Alert API key detected.")
        st.caption("Provider-specific endpoint setup still needs to be added.")
    else:
        st.warning("Whale Alert API key not configured.")
        st.caption("Large transfers should be checked for sender, receiver, and whether an exchange is involved.")

    st.header("6. Cross-Exchange Spot")
    if "error" in ce:
        st.error(ce["error"])
    else:
        for v in ce["venues"]:
            st.write(f"**{v['venue']}**: {money(v['price'])} · 24h XRP volume: {v['volume_xrp']:,.0f}")
        if ce["spread_pct"] is not None:
            st.metric("Price dispersion", f"{ce['spread_pct']:.4f}%")

    st.header("7. Stablecoin / Liquidity Flows")
    if "error" in sc:
        st.error(sc["error"])
    else:
        labels = {"tether": "USDT", "usd-coin": "USDC", "ripple-usd": "RLUSD"}
        for key, vals in sc.items():
            label = labels.get(key, key)
            st.write(
                f"**{label}** · Price: {money(vals.get('usd'))} · "
                f"24h volume: {money(vals.get('usd_24h_vol'))} · "
                f"24h change: {vals.get('usd_24h_change', 0):.3f}%"
            )

    st.header("8. Confirmed News & Catalysts")
    st.markdown(
        "- [Ripple Insights](https://ripple.com/insights/)\n"
        "- [XRPL Blog](https://xrpl.org/blog/)\n"
        "- [SEC Newsroom](https://www.sec.gov/newsroom)\n"
        "- [Coinbase XRP-USD](https://exchange.coinbase.com/trade/XRP-USD)"
    )

    st.header("9. Stocks: Off-Exchange Reference")
    st.write("FINRA ATS/OTC transparency data applies to U.S. securities, not XRP spot trading.")
    st.markdown("[FINRA OTC Transparency](https://otctransparency.finra.org/)")

    st.divider()
    st.subheader("How to read the layers together")
    st.write(
        "A single whale transfer, order-book wall, or price spike is weak evidence by itself. "
        "The useful signal comes from confirmation across independent layers."
    )
    st.write(
        "Suggested sequence: Price & volume → order book → derivatives → liquidations → "
        "XRPL activity → exchange inflows/outflows → identified whale wallets → confirmed news."
    )
