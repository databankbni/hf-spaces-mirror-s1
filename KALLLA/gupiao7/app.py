import gradio as gr
import pandas as pd
import numpy as np
from yahooquery import Ticker
import datetime
import pytz
import threading
import time
import requests
import json
from collections import deque

# ==========================================
# 1. 全局配置
# ==========================================

RAW_HK_TICKERS = [
   '700', '1810', '1299', '981', '3690', '388', '2388',  '1787', '3303','3986', '2888', '6082', '2359', '3750', '3308', '2513', '100','2328', '6809','9961', '267', '1378', '1024', '9992', '16', '762', '3692', '2020', '1', '1698', '788', '6618', '175', '669', '1928', '1801', '2423', '9868', '688', '1113', '12', '2015', '1929', '2269', '2057', '992', '9660', '1177', '1972', '1913', '916', '288', '1876', '1208', '2313', '823', '1093', '291', '241', '20', '2618', '2799', '6969', '285', '6862', '2382', '2577', '1530', '960', '1508', '966', '1258', '9880', '3998', '9698', '780', '1193', '1359', '6963', '3931', '268', '101', '2018', '2331', '2228', '2367', '3888', '3323', '425', '868', '3800', '772', '1888', '1585', '1882', '6088', '2096', '1357', '1128', '552', '2590', '2400', '1133', '867', '1548', '522', '2357', '696', '666', '1833', '1729', '3320', '968', '2245', '2689', '512', '179', '881', '1070', '1060', '551', '1164', '1788', '3933', '6060', '1066', '9636', '2252', '6682', '3918', '3900', '1860', '853', '579', '2232', '6110', '13', '817', '586', '2432', '17', '697', '123', '9688', '2233', '2162', '1798', '2498', '165', '1030', '6666', '1316', '2128', '354', '376', '667', '1672', '1428', '2533', '336', '3339', '1277', '2314', '694', '2142', '460', '1579', '2186', '975', '856', '6616', '1686', '3738', '1478', '2157', '1117', '990', '3868', '412', '1286', '1883', '1783', '1931', '3380', '819', '2342', '839', '826', '2616', '1896', '1302', '604', '308', '2013', '1675', '6078', '119', '2722', '2192', '1951', '2105', '2469', '1167', '1523', '1691', '2225', '6683', '6955', '272', '1050', '327', '2410', '2431', '558', '3833', '2158', '405', '1516', '1773', '931', '1873', '2587', '2522', '2582', '710', '2197', '2198', '580', '1995', '1815', '1115', '2169', '434', '182', '9922', '815', '1268', '2339', '370', '884', '1140', '2001', '6978', '3383', '31', '661', '813', '838', '1765', '2562', '3377', '232', '720', '2878', '1372', '2438', '493', '1943', '361', '78', '616', '1942', '2322', '2503', '3883', '1725', '1393', '632', '757', '858', '3313', '1750', '1792', '2358', '1894',
]

# 雅虎财经的港股需要补齐4位并加 .HK 后缀 (例如: 700 -> 0700.HK)
SYMBOLS = [str(t).zfill(4) + '.HK' for t in RAW_HK_TICKERS]
SYMBOLS = list(set(SYMBOLS))

DISCORD_WEBHOOK = "https://discord.bydsemi-distributor.com/api/webhooks/1447557568124682323/xJgMHLNypaD7m0yfshc28vnhRCZXp-hGQ8aVQvclTUuwKub-2C36XJ7V9cIHYmlXWj54"
# 全局时区修正为香港/北京时间
HK_TZ = pytz.timezone('Asia/Hong_Kong')

ICONS = {
    'multi_res_buy': '💎', 'multi_res_sell': '💣',
    'win_supp': '🛡️', 'win_res': '🧱',
    'ladder_col': '💥',
    'ladder_cross': '🪜',
    'trend_dip': '🌊',
    'macro_buy': '🐋', 'macro_sell': '🦅',
    'market_buy': '🚨', 'market_sell': '🩸',
    'breakdown': '🔻'
}

class GlobalState:
    status = "Init..."
    progress = "Wait..."
    logs = deque(maxlen=200)
    active_alerts = []
    last_scan_time = "N/A"
    data_health = "N/A"
    signal_history = []
    sent_cache = set()
    force_run_once = True
    breakdown_triggered = {}
    realtime_prices = {}
    last_breadth_buy_count = 0
    last_breadth_sell_count = 0

state = GlobalState()

def log(msg):
    ts = datetime.datetime.now(HK_TZ).strftime('%H:%M:%S')
    entry = f"[{ts}] {msg}"
    print(entry)
    state.logs.append(entry)

def get_period_key(symbol, strategy, direction, tf):
    """根据周期生成去重key，确保每根K线只触发一次"""
    now = datetime.datetime.now(HK_TZ)
    
    if tf == '1d' or tf == '1h' or tf == '4h' or tf == '2h' or tf == '3h' or tf == '30m' or tf == '15m' or tf == '5m' or tf == '10m':
        period_key = f"{symbol}_{strategy}_{direction}_{tf}_{now.strftime('%Y-%m-%d')}"
    elif tf == '1wk' or tf == 'wk' or tf.startswith('1wk_'):
        year, week, _ = now.isocalendar()
        period_key = f"{symbol}_{strategy}_{direction}_{tf}_{year}_{week}"
    elif tf == '1mo' or tf == 'mo' or tf.startswith('1mo_'):
        period_key = f"{symbol}_{strategy}_{direction}_{tf}_{now.strftime('%Y-%m')}"
    elif tf == '3mo' or tf == 'quarter' or tf.startswith('3mo_'):
        quarter = (now.month - 1) // 3 + 1
        period_key = f"{symbol}_{strategy}_{direction}_{tf}_{now.year}_Q{quarter}"
    else:
        period_key = f"{symbol}_{strategy}_{direction}_{tf}_{now.strftime('%Y-%m-%d')}"
    return period_key

# ==========================================
# 2. 数据管理
# ==========================================
class DataManager:
    def __init__(self):
        self.micro_data = {}
        self.hourly_data = {}
        self.macro_data = {}

    def is_market_open(self):
        if state.force_run_once:
            return True
        now = datetime.datetime.now(HK_TZ)
        if now.weekday() >= 5: # 周六周日休市
            return False
        
        # 港股精确开盘时间：上午 09:30 - 12:00, 下午 13:00 - 16:00
        current_time = now.time()
        morning_start = datetime.time(9, 30)
        morning_end = datetime.time(12, 0)
        afternoon_start = datetime.time(13, 0)
        afternoon_end = datetime.time(16, 0)
        
        if (morning_start <= current_time <= morning_end) or (afternoon_start <= current_time <= afternoon_end):
            return True
        return False

    def fetch_realtime_prices(self):
        """使用1分钟K线收盘价作为实时价格近似"""
        try:
            chunk_size = 20
            all_prices = {}
            for i in range(0, len(SYMBOLS), chunk_size):
                batch = SYMBOLS[i:i+chunk_size]
                for attempt in range(3):
                    try:
                        t = Ticker(batch, asynchronous=True)
                        df = t.history(period='2d', interval='1m', adj_ohlc=True)
                        if df is not None and not df.empty:
                            df = df.reset_index()
                            if 'adjclose' in df.columns:
                                df = df.rename(columns={'adjclose': 'close'})
                            for symbol in batch:
                                symbol_df = df[df['symbol'] == symbol]
                                if not symbol_df.empty:
                                    last_close = symbol_df.iloc[-1]['close']
                                    all_prices[symbol] = last_close
                                else:
                                    all_prices[symbol] = None
                        else:
                            for symbol in batch:
                                all_prices[symbol] = None
                        break
                    except Exception as e:
                        if attempt == 2:
                            log(f"1分钟数据批次失败 {batch[:3]}...: {e}")
                        else:
                            time.sleep(1)
                time.sleep(0.5)
            state.realtime_prices = all_prices
            success = sum(1 for p in all_prices.values() if p is not None)
            log(f"1分钟收盘价作为实时价格获取: {success}/{len(SYMBOLS)} 成功")
            return success > 0
        except Exception as e:
            log(f"❌ 实时价格获取失败: {e}")
            return False

    def _fetch_chunked(self, symbols, period, interval, max_retries=3):
        chunk_size = 20
        total_count = 0
        for i in range(0, len(symbols), chunk_size):
            batch = symbols[i:i+chunk_size]
            for attempt in range(max_retries):
                try:
                    t = Ticker(batch, asynchronous=True)
                    df = t.history(period=period, interval=interval, adj_ohlc=True)
                    count = self._process(df, interval)
                    total_count += count
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        log(f"批次下载失败 {interval} {batch[:3]}...: {e}")
                    else:
                        time.sleep(2)
            time.sleep(0.5)
        return total_count

    def fetch_all(self):
        state.status = "📥 Fetching..."
        counts = {'5m':0, '15m':0, '30m':0, '1h':0, '1d':0, '1wk':0, '1mo':0, '3mo':0}
        try:
            state.progress = "DL Micro..."
            counts['5m'] = self._fetch_chunked(SYMBOLS, '60d', '5m')
            self._fetch_chunked(SYMBOLS, '60d', '15m')
            counts['30m'] = self._fetch_chunked(SYMBOLS, '60d', '30m')

            state.progress = "DL Hourly..."
            counts['1h'] = self._fetch_chunked(SYMBOLS, '730d', '1h')

            state.progress = "DL Macro..."
            counts['1d'] = self._fetch_chunked(SYMBOLS, '5y', '1d')
            counts['1wk'] = self._fetch_chunked(SYMBOLS, 'max', '1wk')
            counts['1mo'] = self._fetch_chunked(SYMBOLS, 'max', '1mo')

            state.progress = "DL Quarterly..."
            counts['3mo'] = self._fetch_chunked(SYMBOLS, 'max', '3mo')

            self.fetch_realtime_prices()

            state.data_health = f"5m:{counts['5m']}|1h:{counts['1h']}|1d:{counts['1d']}|3mo:{counts['3mo']}|实时:{len([p for p in state.realtime_prices.values() if p])}"
            if counts['5m'] == 0 and counts['1h'] == 0:
                log("❌ Critical: No Data Fetched!")
                return False
            return True
        except Exception as e:
            log(f"❌ Global Fetch Error: {e}")
            return False

    def _process(self, df, interval):
        if df is None or (isinstance(df, dict) and not df) or df.empty:
            return 0
        if isinstance(df, dict):
            return 0
        try:
            df = df.reset_index()
            if 'symbol' not in df.columns:
                return 0
            count = len(df['symbol'].unique())
            if 'adjclose' in df.columns:
                df = df.rename(columns={'adjclose': 'close'})
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], utc=True)
                df['date'] = df['date'].dt.tz_convert(HK_TZ)
            for symbol, group in df.groupby('symbol'):
                group = group.set_index('date').sort_index()
                if interval in ['5m', '15m', '30m']:
                    self.micro_data.setdefault(symbol, {})[interval] = group
                elif interval == '1h':
                    self.hourly_data[symbol] = group
                else:
                    self.macro_data.setdefault(symbol, {})[interval] = group
            return count
        except:
            return 0

    def resample_data(self):
        state.progress = "🔄 Resampling..."
        for s in SYMBOLS:
            try:
                if s in self.micro_data and '5m' in self.micro_data[s]:
                    df = self.micro_data[s]['5m']
                    if not df.empty:
                        logic = {'open':'first', 'high':'max', 'low':'min', 'close':'last', 'volume':'sum'}
                        self.micro_data[s]['10m'] = df.resample('10T', offset='0T').agg(logic).dropna()
                if s in self.hourly_data:
                    df = self.hourly_data[s]
                    if not df.empty:
                        logic = {'open':'first', 'high':'max', 'low':'min', 'close':'last', 'volume':'sum'}
                        self.hourly_data.setdefault(s + '_synth', {})
                        for h in [2,3,4]:
                            self.hourly_data[s + '_synth'][f'{h}h'] = df.resample(f'{h}H', offset='30T').agg(logic).dropna()
            except Exception:
                continue

# ==========================================
# 3. 指标引擎
# ==========================================
class IndicatorEngine:
    @staticmethod
    def calc_ladder(df):
        if df is None:
            return df
        df = df.copy()
        
        # 【修改重点】：移除 if len(df) < 89 的判断。
        # 无论数据长短，Pandas 的 ewm(span=N, adjust=False) 完美等价于 TradingView 的 ta.ema 逻辑。
        # TV源码：ema = na(ema[1]) ? src : alpha * src + (1 - alpha) * ema[1]
        # 这意味着TV会从第一根可用的K线就开始平滑计算（即使数据不够89根），我们这里完全复刻此逻辑。
        
        df['UP1'] = df['high'].ewm(span=26, adjust=False).mean()
        df['DW1'] = df['low'].ewm(span=26, adjust=False).mean()
        df['UP2'] = df['high'].ewm(span=89, adjust=False).mean()
        df['DW2'] = df['low'].ewm(span=89, adjust=False).mean()
        return df

    @staticmethod
    def calc_macd_cd_strict(df, realtime_price=None):
        # 满足：“抄底，卖出信号的len值还是50不要变，逻辑不变，保持原样”
        if df is None or len(df) < 50:
            return df, False, False
        if realtime_price is not None:
            df = df.copy()
            df.iloc[-1, df.columns.get_loc('close')] = realtime_price
        close = df['close']
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        m = (dif - dea) * 2

        df = df.copy()
        df['D'] = dif
        df['A'] = dea
        df['M'] = m
        m_vals = m.values
        d_vals = dif.values
        c_vals = close.values

        segments = []
        if len(m_vals) == 0:
            return df, False, False

        curr_type = 'red' if m_vals[0] >= 0 else 'green'
        start_idx = 0
        for i in range(1, len(m_vals)):
            new_type = 'red' if m_vals[i] >= 0 else 'green'
            if new_type != curr_type:
                seg_slice = slice(start_idx, i)
                seg = {
                    'type': curr_type,
                    'min_c': np.min(c_vals[seg_slice]),
                    'max_c': np.max(c_vals[seg_slice]),
                    'min_d': np.min(d_vals[seg_slice]),
                    'max_d': np.max(d_vals[seg_slice])
                }
                segments.append(seg)
                curr_type = new_type
                start_idx = i

        seg_slice = slice(start_idx, len(m_vals))
        last_seg = {
            'type': curr_type,
            'min_c': np.min(c_vals[seg_slice]),
            'max_c': np.max(c_vals[seg_slice]),
            'min_d': np.min(d_vals[seg_slice]),
            'max_d': np.max(d_vals[seg_slice])
        }
        segments.append(last_seg)

        is_buy = False
        is_sell = False
        curr_d = d_vals[-1]
        prev_d = d_vals[-2]

        if curr_type == 'green' and curr_d < 0:
            if (abs(prev_d) >= abs(curr_d) * 1.01) and (curr_d > prev_d):
                green_segs = [s for s in segments if s['type'] == 'green']
                if len(green_segs) >= 2:
                    cur = green_segs[-1]
                    prev = green_segs[-2]
                    aaa = (cur['min_c'] < prev['min_c']) and (cur['min_d'] > prev['min_d'])
                    bbb = False
                    if len(green_segs) >= 3:
                        prev2 = green_segs[-3]
                        bbb = (cur['min_c'] < prev2['min_c']) and (cur['min_d'] < prev['min_d']) and (cur['min_d'] > prev2['min_d'])
                    if aaa or bbb:
                        is_buy = True

        if curr_type == 'red' and curr_d > 0:
            if (prev_d >= curr_d * 1.01):
                red_segs = [s for s in segments if s['type'] == 'red']
                if len(red_segs) >= 2:
                    cur = red_segs[-1]
                    prev = red_segs[-2]
                    zjdbl = (cur['max_c'] > prev['max_c']) and (cur['max_d'] < prev['max_d'])
                    gxdbl = False
                    if len(red_segs) >= 3:
                        prev2 = red_segs[-3]
                        gxdbl = (cur['max_c'] > prev2['max_c']) and (cur['max_d'] > prev['max_d']) and (cur['max_d'] < prev2['max_d'])
                    if zjdbl or gxdbl:
                        is_sell = True

        return df, is_buy, is_sell

# ==========================================
# 4. 策略分析
# ==========================================
class StrategyAnalyzer:
    def __init__(self):
        self.ie = IndicatorEngine()

    def _is_data_fresh(self, df, tf):
        if df is None or df.empty:
            return False
        last_dt = df.index[-1]
        now = datetime.datetime.now(HK_TZ)
        delta = (now - last_dt).days
        if tf == '1d': return delta <= 7
        if tf == '1wk': return delta <= 10
        if tf == '1mo': return delta <= 45
        if tf == '3mo': return delta <= 120
        return True

    def _is_data_fresh_for_macro(self, df, tf):
        if df is None or df.empty:
            return False
        last_dt = df.index[-1]
        now = datetime.datetime.now(HK_TZ)
        delta = (now - last_dt).days
        if tf == '1d': return delta <= 1
        if tf == '1wk': return delta <= 7
        if tf == '1mo': return delta <= 35
        if tf == '3mo': return delta <= 100
        if tf == '4h': return delta <= 1
        return True

    def _check_breakdown(self, symbol, tf_name, tf_key, df, realtime_price, alerts):
        if df is None or len(df) < 2:
            return
        if realtime_price is None:
            return

        up2 = df['UP2'].iloc[-1]
        dw1 = df['DW1'].iloc[-1]
        
        # 防错保护
        if pd.isna(up2) or pd.isna(dw1):
            return
            
        prev_close = df['close'].iloc[-2]
        threshold = up2 * 1.015

        if not (prev_close > threshold and realtime_price <= threshold):
            return
        if not (dw1 > up2):
            return

        n = len(df)
        for i in range(-2, max(-10, -n)-1, -1):
            hist_up2 = df['UP2'].iloc[i]
            hist_dw1 = df['DW1'].iloc[i]
            hist_low = df['low'].iloc[i]
            if hist_up2 == 0 or pd.isna(hist_up2) or pd.isna(hist_dw1):
                continue
            if hist_low <= hist_up2 * 1.015 and hist_dw1 > hist_up2:
                return

        period_key = get_period_key(symbol, f"{tf_name}下穿UP2", "卖出", tf_key)
        if period_key not in state.breakdown_triggered:
            state.breakdown_triggered[period_key] = True
            price = realtime_price
            alerts.append(self._make_alert(symbol, f"{tf_name}下穿UP2", "卖出", price, tf_key, 'breakdown', period_key))

    def run_all(self, dm: DataManager):
        state.status = "🧠 Scanning..."
        alerts = []
        stats = {'analyzed': 0, 'buy': 0, 'sell': 0}

        for symbol in SYMBOLS:
            try:
                realtime_price = state.realtime_prices.get(symbol)
                if realtime_price is None:
                    continue

                has_micro = symbol in dm.micro_data
                has_hourly = symbol in dm.hourly_data
                has_macro = symbol in dm.macro_data
                if not (has_micro or has_hourly or has_macro):
                    continue

                raw_tfs = {}
                if has_micro: raw_tfs.update(dm.micro_data[symbol])
                if has_hourly: raw_tfs['1h'] = dm.hourly_data[symbol]
                if symbol + '_synth' in dm.hourly_data:
                    raw_tfs.update(dm.hourly_data[symbol + '_synth'])
                if has_macro: raw_tfs.update(dm.macro_data[symbol])

                stats['analyzed'] += 1
                processed = {}
                signals = {}
                ladders = {}

                for tf, df in raw_tfs.items():
                    if tf == '3mo':
                        if len(df) < 2:
                            continue
                    else:
                        # 满足：“抄底，卖出信号的len值还是50不要变”
                        if len(df) < 50:
                            continue
                    
                    if tf in ['1d', '1wk', '1mo', '3mo'] and not self._is_data_fresh(df, tf):
                        continue

                    df = self.ie.calc_ladder(df)
                    df, buy, sell = self.ie.calc_macd_cd_strict(df, realtime_price)

                    if tf in ['4h', '1d', '1wk', '1mo', '3mo']:
                        if not self._is_data_fresh_for_macro(df, tf):
                            buy = False
                            sell = False

                    processed[tf] = df
                    signals[tf] = {'buy': buy, 'sell': sell}
                    if buy: stats['buy'] += 1
                    if sell: stats['sell'] += 1

                    ladders[tf] = {
                        'UP1': df['UP1'].iloc[-1],
                        'DW1': df['DW1'].iloc[-1],
                        'UP2': df['UP2'].iloc[-1],
                        'DW2': df['DW2'].iloc[-1],
                        'prev_UP1': df['UP1'].iloc[-2] if len(df) >= 2 else np.nan,
                        'prev_UP2': df['UP2'].iloc[-2] if len(df) >= 2 else np.nan,
                        'low': df['low'].iloc[-1],
                        'close': df['close'].iloc[-1]
                    }

                    if buy: self._record_signal(symbol, 'buy', tf)
                    if sell: self._record_signal(symbol, 'sell', tf)

                # 下穿UP2
                self._check_breakdown(symbol, "日线", "1d", processed.get('1d'), realtime_price, alerts)
                self._check_breakdown(symbol, "周线", "1wk", processed.get('1wk'), realtime_price, alerts)
                self._check_breakdown(symbol, "月线", "1mo", processed.get('1mo'), realtime_price, alerts)
                self._check_breakdown(symbol, "季线", "3mo", processed.get('3mo'), realtime_price, alerts)

                # 支撑/压力窗口（不受严格新鲜度影响，使用原始 signals 中的小周期信号）
                self._check_window(symbol, processed, ladders, signals, alerts)
                self._check_resonance(symbol, alerts)
                
                # 大级别单点（实时信号，带周期去重）
                for tf in ['4h', '1d', '1wk', '1mo', '3mo']:
                    if signals.get(tf, {}).get('buy'):
                        period_key = get_period_key(symbol, "大级别单点", "抄底", tf)
                        if period_key not in state.sent_cache:
                            price = ladders.get(tf, {}).get('close', realtime_price)
                            alerts.append(self._make_alert(symbol, "大级别单点", "抄底", price, tf, 'macro_buy', period_key))
                    if signals.get(tf, {}).get('sell'):
                        period_key = get_period_key(symbol, "大级别单点", "卖出", tf)
                        if period_key not in state.sent_cache:
                            price = ladders.get(tf, {}).get('close', realtime_price)
                            alerts.append(self._make_alert(symbol, "大级别单点", "卖出", price, tf, 'macro_sell', period_key))

            except Exception:
                continue

        self._check_breadth(alerts)
        log(f"📊 Rep: B{stats['buy']}/S{stats['sell']} | Alerts: {len(alerts)}")
        return alerts

    def _validate_support(self, df, dw_col, up_col):
        if len(df) < 2:
            return False
        hist = df.iloc[:-1]
        c = hist['close'].values
        u = hist[up_col].values
        d = hist[dw_col].values
        for i in range(len(hist)-1, -1, -1):
            if pd.isna(u[i]) or pd.isna(d[i]):
                return False
            if c[i] > u[i]:
                if i == len(hist)-1:
                    return True
                return np.all(c[i+1:] >= d[i+1:])
            if c[i] < d[i]:
                return False
        return False

    def _validate_resistance(self, df, dw_col, up_col):
        if len(df) < 2:
            return False
        hist = df.iloc[:-1]
        c = hist['close'].values
        u = hist[up_col].values
        d = hist[dw_col].values
        for i in range(len(hist)-1, -1, -1):
            if pd.isna(u[i]) or pd.isna(d[i]):
                return False
            if c[i] < d[i]:
                if i == len(hist)-1:
                    return True
                return np.all(c[i+1:] <= u[i+1:])
            if c[i] > u[i]:
                return False
        return False

    def _check_window(self, symbol, tfs, ladders, signals, alerts):
        levels = [('1d','日线'), ('1wk','周线'), ('1mo','月线'), ('3mo','季线')]
        buy_tfs_map = {
            '1d': ['5m','15m','30m','1h','2h'],
            '1wk': ['5m','15m','30m','1h','4h','1d'],
            '1mo': ['5m','15m','30m','1d','1wk'],
            '3mo': ['5m','15m','30m','1d','1wk']
        }
        sell_tfs_map = {
            '1d': ['1h','2h'],
            '1wk': ['1h','2h','4h','1d'],
            '1mo': ['1h','2h','1d','1wk'],
            '3mo': ['1h','2h','1d','1wk']
        }

        for tf, name in levels:
            if tf not in tfs:
                continue
            df = tfs[tf]
            lad = ladders[tf]
            low = df['low'].iloc[-1]
            high = df['high'].iloc[-1]
            price = df['close'].iloc[-1]

            if self._validate_support(df, 'DW1', 'UP1') and low <= lad['DW1'] * 1.015:
                for s_tf in buy_tfs_map[tf]:
                    if signals.get(s_tf, {}).get('buy'):
                        combined_tf = f"{tf}_{s_tf}"
                        period_key = get_period_key(symbol, f"支撑窗口({name}蓝)", "抄底", combined_tf)
                        if period_key not in state.sent_cache:
                            alerts.append(self._make_alert(symbol, f"支撑窗口({name}蓝)", "抄底", price, s_tf, 'win_supp', period_key))
            if self._validate_resistance(df, 'DW1', 'UP1') and high >= lad['UP1'] * 0.985:
                for s_tf in sell_tfs_map[tf]:
                    if signals.get(s_tf, {}).get('sell'):
                        combined_tf = f"{tf}_{s_tf}"
                        period_key = get_period_key(symbol, f"压力窗口({name}蓝)", "卖出", combined_tf)
                        if period_key not in state.sent_cache:
                            alerts.append(self._make_alert(symbol, f"压力窗口({name}蓝)", "卖出", price, s_tf, 'win_res', period_key))
            if self._validate_support(df, 'DW2', 'UP2') and low <= lad['DW2'] * 1.015:
                for s_tf in buy_tfs_map[tf]:
                    if signals.get(s_tf, {}).get('buy'):
                        combined_tf = f"{tf}_{s_tf}"
                        period_key = get_period_key(symbol, f"支撑窗口({name}黄)", "抄底", combined_tf)
                        if period_key not in state.sent_cache:
                            alerts.append(self._make_alert(symbol, f"支撑窗口({name}黄)", "抄底", price, s_tf, 'win_supp', period_key))
            if self._validate_resistance(df, 'DW2', 'UP2') and high >= lad['UP2'] * 0.985:
                for s_tf in sell_tfs_map[tf]:
                    if signals.get(s_tf, {}).get('sell'):
                        combined_tf = f"{tf}_{s_tf}"
                        period_key = get_period_key(symbol, f"压力窗口({name}黄)", "卖出", combined_tf)
                        if period_key not in state.sent_cache:
                            alerts.append(self._make_alert(symbol, f"压力窗口({name}黄)", "卖出", price, s_tf, 'win_res', period_key))

    def _record_signal(self, symbol, type_, tf):
        now = datetime.datetime.now(HK_TZ)
        state.signal_history.append({'time': now, 'symbol': symbol, 'type': type_, 'tf': tf})
        cutoff = now - datetime.timedelta(hours=4)
        state.signal_history = [x for x in state.signal_history if x['time'] > cutoff]

    def _check_resonance(self, symbol, alerts):
        hist = [x for x in state.signal_history if x['symbol'] == symbol]
        buy = set(x['tf'] for x in hist if x['type'] == 'buy')
        sell = set(x['tf'] for x in hist if x['type'] == 'sell')
        if {'1h','2h','3h','4h'}.issubset(buy):
            period_key = get_period_key(symbol, "多周期共振", "抄底", "1h..4h")
            if period_key not in state.sent_cache:
                alerts.append(self._make_alert(symbol, "多周期共振", "抄底", 0, "1h..4h", 'multi_res_buy', period_key))
        if {'1h','2h','3h','4h'}.issubset(sell):
            period_key = get_period_key(symbol, "多周期共振", "卖出", "1h..4h")
            if period_key not in state.sent_cache:
                alerts.append(self._make_alert(symbol, "多周期共振", "卖出", 0, "1h..4h", 'multi_res_sell', period_key))

    def _check_breadth(self, alerts):
        hist = state.signal_history
        ub = set(x['symbol'] for x in hist if x['type'] == 'buy' and x['tf'] in ['30m','1h','2h','3h','4h','1d'])
        us = set(x['symbol'] for x in hist if x['type'] == 'sell' and x['tf'] in ['1h','2h','3h','4h','1d'])
        limit = len(SYMBOLS) * 0.2

        buy_count = len(ub)
        if buy_count >= limit:
            if state.last_breadth_buy_count == 0 or buy_count >= state.last_breadth_buy_count + 5:
                state.last_breadth_buy_count = buy_count
                period_key = get_period_key("MARKET", "集体抄底", "抄底", f"All_{buy_count}")
                alerts.append(self._make_alert("MARKET", f"集体抄底({buy_count})", "抄底", 0, "All", 'market_buy', period_key))
        else:
            state.last_breadth_buy_count = 0

        sell_count = len(us)
        if sell_count >= limit:
            if state.last_breadth_sell_count == 0 or sell_count >= state.last_breadth_sell_count + 5:
                state.last_breadth_sell_count = sell_count
                period_key = get_period_key("MARKET", "集体卖出", "卖出", f"All_{sell_count}")
                alerts.append(self._make_alert("MARKET", f"集体卖出({sell_count})", "卖出", 0, "All", 'market_sell', period_key))
        else:
            state.last_breadth_sell_count = 0

    def _make_alert(self, symbol, strategy, direction, price, tf, icon_key, period_key=None):
        return {
            'time': datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S'),
            'symbol': symbol,
            'strategy': strategy,
            'direction': direction,
            'price': round(price, 2),
            'tf': tf,
            'icon': ICONS.get(icon_key, '🔔'),
            'period_key': period_key
        }

# ==========================================
# 5. Discord 发送与后台任务
# ==========================================
def send_discord_alerts(alerts):
    if not alerts:
        return
    count = 0
    for a in alerts:
        if a['period_key'] is None:
            period_key = get_period_key(a['symbol'], a['strategy'], a['direction'], a['tf'])
        else:
            period_key = a['period_key']
        if period_key in state.sent_cache:
            continue
        content = f"{a['icon']} **{a['symbol']}** | {a['strategy']} | {a['direction']} | {a['tf']}"
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": content})
            state.sent_cache.add(period_key)
            state.active_alerts.insert(0, a)
            count += 1
        except Exception as e:
            log(f"Discord Fail: {e}")
    if count > 0:
        log(f"🚀 Sent {count} alerts")

def background_task():
    dm = DataManager()
    sa = StrategyAnalyzer()
    log("🔵 HK Monitor Start (大级别单点严格新鲜度，支撑窗口保留T,T+1)")
    while True:
        try:
            if dm.is_market_open():
                state.last_scan_time = datetime.datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M:%S')
                if state.force_run_once:
                    log("⚡ Force Run...")
                else:
                    log("=== Scan ===")
                if dm.fetch_all():
                    dm.resample_data()
                    alerts = sa.run_all(dm)
                    send_discord_alerts(alerts)
                if state.force_run_once:
                    state.force_run_once = False
                    log("⚡ Done.")
                log("=== Sleep 60s ===")
            else:
                state.status = "🌙 Sleep"
            time.sleep(60)
        except Exception as e:
            log(f"❌ Crash: {e}")
            time.sleep(60)

t = threading.Thread(target=background_task, daemon=True)
t.start()

def get_dash():
    df = pd.DataFrame(state.active_alerts)
    if df.empty:
        df = pd.DataFrame(columns=['time', 'symbol', 'strategy', 'direction', 'price', 'tf'])
    status = f"St: {state.status} | {state.progress} | Dat: {state.data_health} | Upd: {state.last_scan_time}"
    return status, "\n".join(list(state.logs)), df

with gr.Blocks(title="HK Quant Pro") as demo:
    gr.Markdown("# 🇭🇰 港股量化 (大级别单点严格新鲜度)")
    status_box = gr.Textbox(label="Status", interactive=False)
    with gr.Row():
        log_box = gr.TextArea(label="Logs", lines=20, max_lines=20, interactive=False)
        alert_table = gr.Dataframe(label="Alerts", headers=['time', 'symbol', 'strategy', 'direction', 'price', 'tf'])
    gr.Timer(2).tick(get_dash, outputs=[status_box, log_box, alert_table])

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)