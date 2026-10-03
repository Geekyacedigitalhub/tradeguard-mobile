RESEARCH_SOURCES = [
    {"name":"CFTC — Forex Frauds / Customer Advisories","url":"https://www.cftc.gov/LearnAndProtect/forexfrauds","type":"risk"},
    {"name":"CME Group — Proper Position Size","url":"https://www.cmegroup.com/education/courses/trade-and-risk-management/proper-position-size","type":"risk"},
    {"name":"CME Group — Risk Management and Your Trade Plan","url":"https://www.cmegroup.com/education/courses/building-a-trade-plan/risk-management-and-your-trade-plan","type":"risk"},
    {"name":"Fidelity — Technical Analysis","url":"https://www.fidelity.com/learning-center/trading-investing/technical-analysis/what-is-technical-analysis","type":"technical"},
    {"name":"Fidelity — Technical Indicator Guide","url":"https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/overview","type":"technical"},
    {"name":"Federal Reserve — FOMC","url":"https://www.federalreserve.gov/fomc/","type":"macro"},
]

INDICATORS = [
    {"slug":"sma","name":"Simple Moving Average (SMA)","category":"Trend","what":"Average closing price over a chosen number of periods.","read":"Price above a rising SMA supports bullish trend context; price below a falling SMA supports bearish context.","best":"Trend direction, dynamic support/resistance and noise reduction.","warning":"It is lagging and can whipsaw in ranges.","source":"Fidelity Technical Analysis"},
    {"slug":"ema","name":"Exponential Moving Average (EMA)","category":"Trend","what":"A moving average that gives more weight to recent prices.","read":"EMA stacks such as 20 > 50 > 200 can show bullish structure; the reverse can show bearish structure.","best":"Trend and pullback context.","warning":"Still lags price and is unreliable by itself in sideways markets.","source":"Fidelity Technical Analysis"},
    {"slug":"rsi","name":"Relative Strength Index (RSI)","category":"Momentum","what":"A 0–100 momentum oscillator based on recent gains versus losses.","read":"Traditionally >70 is overbought and <30 oversold, but strong trends can keep RSI extreme for long periods.","best":"Momentum, trend context and divergence.","warning":"Overbought does not automatically mean sell; oversold does not automatically mean buy.","source":"Fidelity RSI"},
    {"slug":"macd","name":"MACD","category":"Momentum/Trend","what":"Difference between fast and slow EMAs with a signal line.","read":"MACD above zero and bullish signal-line crossover support bullish momentum; the reverse supports bearish momentum.","best":"Trend momentum and momentum shifts.","warning":"Crossovers can whipsaw in ranges.","source":"Fidelity MACD"},
    {"slug":"bollinger","name":"Bollinger Bands","category":"Volatility","what":"A moving average surrounded by bands based on standard deviation.","read":"Band expansion means volatility is increasing; contraction marks quieter conditions. Price can remain outside a band during strong trends.","best":"Volatility regime, breakouts and mean-reversion context.","warning":"Touching a band is not a standalone reversal signal.","source":"Fidelity Bollinger Bands"},
    {"slug":"atr","name":"Average True Range (ATR)","category":"Volatility","what":"Average true range over a selected period; it measures volatility, not direction.","read":"Rising ATR means expanding volatility; falling ATR means quieter conditions.","best":"Stop placement, position sizing and volatility filters.","warning":"ATR does not tell you whether price will rise or fall.","source":"Fidelity ATR"},
    {"slug":"adx","name":"Average Directional Index (ADX)","category":"Trend Strength","what":"A trend-strength measure derived from directional movement.","read":"Higher/rising ADX generally means stronger trend conditions; low ADX often indicates a trendless market.","best":"Choosing trend-following versus range conditions.","warning":"ADX measures strength, not direction; use +DI/-DI or price structure for direction.","source":"Fidelity DMI"},
    {"slug":"stochastic","name":"Stochastic Oscillator","category":"Momentum","what":"Compares the close with the recent high-low range.","read":"Common reference zones are >80 overbought and <20 oversold; crosses need context.","best":"Momentum and range/reversal context.","warning":"Can remain extreme during strong trends.","source":"Fidelity Technical Indicator Guide"},
    {"slug":"cci","name":"Commodity Channel Index (CCI)","category":"Momentum","what":"Measures price relative to its average price over a chosen period.","read":"+100 and -100 are common reference levels, but the oscillator is unbounded and should be confirmed.","best":"Momentum and divergence context.","warning":"Extreme readings can persist in trends.","source":"Fidelity CCI"},
    {"slug":"roc","name":"Rate of Change (ROC)","category":"Momentum","what":"Measures percentage change from an earlier price.","read":"Positive ROC means price is above its comparison point; negative means below.","best":"Momentum acceleration and deceleration.","warning":"It can be noisy around zero.","source":"Technical-analysis convention"},
    {"slug":"williams-r","name":"Williams %R","category":"Momentum","what":"A bounded oscillator comparing the close with a recent high-low range.","read":"Values near 0 indicate closes near the top of the range; values near -100 indicate closes near the bottom.","best":"Momentum and range context.","warning":"Extreme readings can persist in trends.","source":"Technical-analysis convention"},
    {"slug":"obv","name":"On-Balance Volume (OBV)","category":"Volume","what":"A cumulative volume measure that adds/subtracts volume based on price direction.","read":"Rising OBV can confirm accumulation; falling OBV can confirm distribution.","best":"Volume confirmation where volume is meaningful.","warning":"Spot FX volume is usually broker/tick volume rather than centralized exchange volume.","source":"Fidelity Technical Indicator Guide"},
    {"slug":"mfi","name":"Money Flow Index (MFI)","category":"Volume/Momentum","what":"A volume-weighted momentum oscillator using typical price and volume.","read":"Common reference zones are >80 and <20, but context matters.","best":"Momentum plus volume confirmation.","warning":"Volume quality differs across markets, especially OTC FX.","source":"Fidelity Technical Indicator Guide"},
    {"slug":"fibonacci","name":"Fibonacci Retracement","category":"Support/Resistance","what":"Price levels derived from Fibonacci ratios used to map possible retracement areas.","read":"Common reference levels include 23.6%, 38.2%, 50%, 61.8% and 78.6%.","best":"Mapping potential pullback and reaction zones after a defined swing.","warning":"Levels are reference zones, not guaranteed reversal points.","source":"Fidelity Technical Indicator Guide"},
    {"slug":"vwap","name":"VWAP","category":"Price/Volume","what":"Volume-weighted average price over a defined session.","read":"Price above VWAP can indicate stronger intraday positioning; below can indicate weaker positioning.","best":"Intraday context where reliable volume exists.","warning":"Spot FX has no single centralized volume feed, so broker/tick-volume VWAP is an approximation.","source":"Technical-analysis convention"},
    {"slug":"ichimoku","name":"Ichimoku Cloud","category":"Trend","what":"A multi-line trend, momentum and support/resistance system.","read":"Cloud position, Tenkan/Kijun relationship and cloud thickness provide several layers of context.","best":"Structured trend and support/resistance analysis.","warning":"It is information-dense and should not be reduced to one crossover.","source":"Technical-analysis convention"},
]

CANDLES = [
    {"slug":"doji","name":"Doji","group":"Single candle","what":"Open and close are very close relative to the candle range.","meaning":"Indecision or balance between buyers and sellers.","confirmation":"Needs location and following-candle confirmation; a doji alone is not a reversal signal."},
    {"slug":"hammer","name":"Hammer","group":"Single candle","what":"Small real body with a long lower wick after a decline.","meaning":"Rejection of lower prices; can support bullish reversal when it appears at meaningful support.","confirmation":"Look for support and bullish follow-through."},
    {"slug":"shooting-star","name":"Shooting Star","group":"Single candle","what":"Small real body with a long upper wick after an advance.","meaning":"Rejection of higher prices; can support bearish reversal at resistance.","confirmation":"Look for resistance and bearish follow-through."},
    {"slug":"bullish-engulfing","name":"Bullish Engulfing","group":"Two candles","what":"A bullish candle's body engulfs the prior bearish body.","meaning":"A shift toward buyer control.","confirmation":"Stronger at support or after a decline; confirmation reduces false signals."},
    {"slug":"bearish-engulfing","name":"Bearish Engulfing","group":"Two candles","what":"A bearish candle's body engulfs the prior bullish body.","meaning":"A shift toward seller control.","confirmation":"Stronger at resistance or after an advance."},
    {"slug":"inside-bar","name":"Inside Bar","group":"Two candles","what":"The current high and low remain inside the previous candle's range.","meaning":"Compression/temporary balance.","confirmation":"Breakout direction and market context matter."},
    {"slug":"outside-bar","name":"Outside Bar","group":"Two candles","what":"The current candle exceeds the previous candle's high and low.","meaning":"Expansion and a stronger shift in short-term control.","confirmation":"Direction, close location and nearby structure matter."},
    {"slug":"morning-star","name":"Morning Star","group":"Three candles","what":"A three-candle bullish reversal formation after a decline.","meaning":"Potential transition from selling pressure to buying pressure.","confirmation":"Best treated as a setup that needs location and follow-through."},
    {"slug":"evening-star","name":"Evening Star","group":"Three candles","what":"A three-candle bearish reversal formation after an advance.","meaning":"Potential transition from buying pressure to selling pressure.","confirmation":"Best treated as a setup that needs location and follow-through."},
    {"slug":"marubozu","name":"Marubozu / Strong Body Candle","group":"Single candle","what":"A candle with a large body and little wick relative to its range.","meaning":"Strong directional participation during that bar.","confirmation":"Continuation is more credible when aligned with trend and structure."},
    {"slug":"pin-bar","name":"Pin Bar","group":"Single candle","what":"A candle with a prominent rejection wick and smaller body.","meaning":"Rejection of a price area.","confirmation":"Location, trend and the next candle are essential."},
]

SIGNALS = [
    {"slug":"trend-continuation","name":"Trend Continuation","meaning":"Trend direction, structure and momentum remain aligned after a pullback.","avoid":"Avoid when higher timeframes conflict or price is already stretched into major resistance/support."},
    {"slug":"breakout","name":"Breakout","meaning":"Price closes beyond a defined structure level with evidence of participation.","avoid":"Avoid treating a wick through a level as a confirmed breakout; watch for failed breaks."},
    {"slug":"retest","name":"Breakout Retest","meaning":"Price returns toward a broken level and holds it as the new side of support/resistance.","avoid":"Avoid assuming every retest will hold."},
    {"slug":"reversal","name":"Reversal","meaning":"A change in directional structure supported by location, momentum and price action.","avoid":"Avoid countertrend entries based on one oscillator reaching an extreme."},
    {"slug":"divergence","name":"Divergence","meaning":"Price and an oscillator move out of sync, suggesting momentum may be changing.","avoid":"Divergence is an alert, not a guarantee of reversal."},
    {"slug":"range","name":"Range / Mean Reversion","meaning":"Price repeatedly respects upper and lower boundaries while trend strength is weak.","avoid":"Avoid trend-following breakouts in a compressed range without confirmation."},
    {"slug":"volatility-expansion","name":"Volatility Expansion","meaning":"Range/volatility increases after compression and may accompany a directional move.","avoid":"Expansion can occur in either direction; ATR is not directional."},
    {"slug":"no-trade","name":"NO TRADE","meaning":"Evidence is conflicting, incomplete, too volatile, too stretched, or the risk cannot be justified.","avoid":"Do not force a position simply because a market is moving."},
]

MACRO_TOPICS = [
    {"slug":"interest-rates","name":"Interest Rates","what":"Central-bank policy can influence currency demand, yields and broader financial conditions.","source":"Federal Reserve FOMC"},
    {"slug":"inflation","name":"Inflation / CPI","what":"Inflation data can alter expectations for monetary policy and therefore affect currencies and rates.","source":"Federal Reserve / CME Group"},
    {"slug":"employment","name":"Employment / NFP","what":"Employment data can cause rapid repricing and volatility in FX markets.","source":"CME Group economic research"},
    {"slug":"gdp","name":"GDP","what":"Growth data helps shape expectations about economic conditions and policy.","source":"Economic-calendar convention"},
    {"slug":"central-banks","name":"Central-bank decisions and guidance","what":"Rate decisions and forward guidance can materially change currency expectations.","source":"Federal Reserve FOMC"},
]

TRADING_PRINCIPLES = [
    "No indicator is a crystal ball. TradeGuard treats indicators as evidence that must agree with market context.",
    "A signal is not a trade. A trade needs a defined invalidation point, position size, acceptable cost and risk approval.",
    "NO TRADE is a valid and often preferable decision when evidence conflicts.",
    "Overbought and oversold readings are context-dependent; strong trends can stay extreme.",
    "Volatility tools such as ATR measure movement size, not direction.",
    "Backtests are evidence, not proof. Results can fail when market conditions change and costs/slippage differ.",
    "Retail forex is leveraged and risky. TradeGuard must never present a setup as guaranteed profit.",
]

def all_knowledge():
    return {
        "mission":"Research-backed trading intelligence: explain the market, explain the evidence, identify trade and no-trade conditions, and require risk controls before execution.",
        "principles":TRADING_PRINCIPLES,
        "indicators":INDICATORS,
        "candles":CANDLES,
        "signals":SIGNALS,
        "macro_topics":MACRO_TOPICS,
        "sources":RESEARCH_SOURCES,
    }
