
from pathlib import Path
from gradio_client import Client
import pandas as pd
from datetime import datetime, timedelta
import json
import random
import time


def _with_retry(fn, max_attempts=3, delay=30):
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if attempt < max_attempts - 1:
                print(f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise

DATA_DIR = Path(__file__).parent / "data"

TRADER_ATTRIBUTES_FILE = DATA_DIR / "trader_attributes.json"

class TradingEngine:
    def __init__(self):

        self.ticker_map = {"AAPL": "APPLE", "AMZN": "AMAZON", "GOOG": "GOOGLE", "NFLX": "NETFLIX", "META": "META (a.k.a. Facebook)"}
        self.api_client = _with_retry(lambda: Client("ML-Owl/FAANG-Pulse-AI"))

        with open(TRADER_ATTRIBUTES_FILE, 'r') as f:
            self.trader_attributes = json.load(f)

        self.backtesting_mode = False
        self.stock_tickers = ["AAPL", "AMZN", "GOOG", "NFLX", "META"]


    def get_stock_prices(self, tickers:list[str], date:str):
        #tickers_list = self.ticker_map.keys()  # tickers for all supported stocks
        
        result = _with_retry(lambda: self.api_client.predict(
            stock_ticker_list=tickers,
            date_selected=date,
            api_name="/get_prices_on_date"
        ))

        return result


    def upload_logfile(self):
        result = _with_retry(lambda: self.api_client.predict(
            api_name="/upload_logfile"
        ))
        print(f"Log file upload result: {result}")
        return result


    def get_sellable_shares(self, df_log:pd.DataFrame, ticker:str):
        # Returns the number of shares than can be sold for a stock in the portfolio.
        # Works as expected even when "ticker" is absent in df_log ! (i.e., returns 0)
        ticker_df = df_log[df_log["Ticker"] == ticker]  # sub-dataframe with transactions including "ticker" only.
        shares_bought = ticker_df[ticker_df["Action"] == "BUY"]["Shares"].sum()
        shares_sold = ticker_df[ticker_df["Action"] == "SELL"]["Shares"].sum()
        
        return shares_bought - shares_sold


    def run_trade_execution(self, stock_prices:dict):

        for eachInvestor in self.trader_attributes["investors"]:
            decision_threshold = self.trader_attributes["investors"][eachInvestor]["decision_threshold"]
            trade_log_file = self.trader_attributes["investors"][eachInvestor]["trade_log_file"]
            trade_log_file_path = DATA_DIR / trade_log_file
            df_log = pd.read_csv(trade_log_file_path)

            for eachStock in stock_prices:
                # Get trend prediction from AI using FAANG Pulse AI API
                predicted_trend, _ = self.api_client.predict(
                    stocks_dropdown=self.ticker_map[eachStock],
                    calendar_item=stock_prices[eachStock]["Date"], # using the actual date reported by the API for which there is price data!
                    risk_slider=decision_threshold,
                    api_name="/run_trend_prediction"
                )

                strategy_fn = self.get_trading_strategy(eachInvestor)  # get the relevant function to call for the investor
                df_log = strategy_fn(
                    investor_name=eachInvestor,
                    ticker=eachStock,
                    stock_prices=stock_prices,
                    date=stock_prices[eachStock]["Date"],
                    predicted_trend=predicted_trend,
                    df_log=df_log
                    )

                df_log.to_csv(trade_log_file_path, index=False)  # replace CSV with full updated log for this investor


    def get_trading_strategy(self, investor_name:str):
        # Returns the investment strategy function to caller to use for this investor
        investor_strategy_map = {
            "Safe_Sam": self.safe_strategy,
            "Optimal_Owen": self.optimal_strategy,
            "Brave_Beth": self.brave_strategy,
            "Random_Randy": self.random_strategy
        }

        return investor_strategy_map[investor_name]


    def build_new_transaction_row(self, new_row:dict, df_log:pd.DataFrame, investor_name:str, max_shares_to_buy:int, max_shares_to_sell:int):
        """
        Builds a new transaction row for the transaction log based on common trading logic.
        """

        # Readback pre-populated values from new_row
        predicted_trend = new_row["Direction"]
        price_per_share = new_row["Price"]  # We use (Adjusted) Close price to calculate the cost of the trade
        ticker = new_row["Ticker"]

        if df_log.empty:
            # First ever trade for this investor
            available_cash = self.trader_attributes["investors"][investor_name]["cash_allocated"]  # Initial budget
        else:
            # There are trade transactions in the log file already.
            available_cash = df_log.iloc[-1]["Cash After Trade"]  # Last entry keeps track of the available cash.


        if predicted_trend == "TREND_UP":
            # Opportunity to BUY
            shares_to_buy = min(max_shares_to_buy, available_cash // price_per_share)
            if shares_to_buy > 0:
                new_row["Action"] = "BUY"
                new_row["Shares"] = shares_to_buy
                new_row["Cash Before Trade"] = available_cash
                new_row["Cash After Trade"] = available_cash - (shares_to_buy * price_per_share)

        if predicted_trend == "TREND_DOWN":
            sellable_shares = self.get_sellable_shares(df_log, ticker)
            shares_to_sell = min(max_shares_to_sell, sellable_shares)
            if shares_to_sell > 0:
                new_row["Action"] = "SELL"
                new_row["Shares"] = shares_to_sell
                new_row["Cash Before Trade"] = available_cash
                new_row["Cash After Trade"] = available_cash + (shares_to_sell * price_per_share)

        if new_row["Action"] == "NONE":
            # If Action is still invalid at this point, a HOLD transaction is the only valid action.
            # Log this as a HOLD transaction. Since there is no cash to buy.
            new_row["Action"] = "HOLD"
            new_row["Shares"] = 0
            new_row["Cash Before Trade"] = available_cash
            new_row["Cash After Trade"] = available_cash

        return new_row



    def safe_strategy(self, investor_name:str, ticker: str, stock_prices:dict, date: str, predicted_trend:str, df_log:pd.DataFrame):
        """
        Safe Sam strategy:
        - If date is the same as the last trade date in log, do nothing and exit the function. (this happens when markets are closed!)
        - If the predicted trend is TREND_UP, BUY 50 shares.
        - else if the predicted trend is TREND_DOWN SELL 100 shares
        - else (if NO_TREND) HOLD the position.

        The BUY actions will be executed ONLY if there is enough cash available. If not, BUY as much as possible and then HOLD the position.
        """

        # If date is the same as the last trade date in log AND the ticker is the same as the last trade ticker,
        # then do nothing and exit the function. (this happens when markets are closed!)
        if date in df_log[df_log['Ticker']==ticker]['Date'].values:
            return df_log

        max_shares_to_buy, max_shares_to_sell = 50, 100

        price_per_share = stock_prices[ticker]["Close"]  # We use (Adjusted) Close price to calculate the cost of the trade

        # Initialize new row for the transaction log.
        # Following columns will be added to df_log regardless of the action taken.
        new_row = {
            "Date": date,
            "Ticker": ticker,
            "Price": price_per_share,
            "Direction": predicted_trend,
            "Action": "NONE"  # initialized to an invalid entry to simplify code below.
        }

        # Following is the common trading logic for all investors.
        new_row = self.build_new_transaction_row(new_row,df_log, investor_name, max_shares_to_buy, max_shares_to_sell)

        # New transaction log created.
        df_log.loc[len(df_log)] = new_row  # Added to the end of df_log dataframe
        
        return df_log


    def optimal_strategy(self, investor_name:str, ticker: str, stock_prices:dict, date: str, predicted_trend:str, df_log:pd.DataFrame):
        """
        Optimal Owen strategy:
        - If date is the same as the last trade date in log, do nothing and exit the function. (this happens when markets are closed!)
        - If the predicted trend is TREND_UP BUY 20 shares.
        - else if the predicted trend is TREND_DOWN SELL 20 shares
        - else (if NO_TREND) HOLD the position.

        The BUY actions will be executed ONLY if there is enough cash available. If not, BUY as much as possible and then HOLD the position.
        """

        # If date is the same as the last trade date in log AND the ticker is the same as the last trade ticker,
        # then do nothing and exit the function. (this happens when markets are closed!)
        if date in df_log[df_log['Ticker']==ticker]['Date'].values:
            return df_log

        max_shares_to_buy, max_shares_to_sell = 20, 20
        price_per_share = stock_prices[ticker]["Close"]  # We use (Adjusted) Close price to calculate the cost of the trade

        # Initialize new row for the transaction log.
        # Following columns will be added to df_log regardless of the action taken.
        new_row = {
            "Date": date,
            "Ticker": ticker,
            "Price": price_per_share,
            "Direction": predicted_trend,
            "Action": "NONE"  # initialized to an invalid entry to simplify code below.
        }

        # Following is the common trading logic for all investors.
        new_row = self.build_new_transaction_row(new_row,df_log, investor_name, max_shares_to_buy, max_shares_to_sell)

        # New transaction log created.
        df_log.loc[len(df_log)] = new_row  # Added to the end of df_log dataframe
        
        return df_log



    def brave_strategy(self, investor_name:str, ticker: str, stock_prices:dict, date: str, predicted_trend:str, df_log:pd.DataFrame):
        """
        Brave Beth strategy:
        - If date is the same as the last trade date in log, do nothing and exit the function. (this happens when markets are closed!)
        - If the predicted trend is TREND_UP BUY 10 shares.
        - else if the predicted trend is TREND_DOWN SELL 10 shares.
        - else (if NO_TREND) HOLD the position.

        The BUY actions will be executed ONLY if there is enough cash available. If not, BUY as much as possible and then HOLD the position.
        """   
        # If date is the same as the last trade date in log AND the ticker is the same as the last trade ticker,
        # then do nothing and exit the function. (this happens when markets are closed!)
        if date in df_log[df_log['Ticker']==ticker]['Date'].values:
            return df_log

        max_shares_to_buy, max_shares_to_sell = 10, 10

        price_per_share = stock_prices[ticker]["Close"]  # We use (Adjusted) Close price to calculate the cost of the trade

        # Initialize new row for the transaction log.
        # Following columns will be added to df_log regardless of the action taken.
        new_row = {
            "Date": date,
            "Ticker": ticker,
            "Price": price_per_share,
            "Direction": predicted_trend,
            "Action": "NONE"  # initialized to an invalid entry to simplify code below.
        }

        # Following is the common trading logic for all investors.
        new_row = self.build_new_transaction_row(new_row, df_log, investor_name, max_shares_to_buy, max_shares_to_sell)

        # New transaction log created.
        df_log.loc[len(df_log)] = new_row  # Added to the end of df_log dataframe
        
        return df_log


    def random_strategy(self, investor_name:str, ticker: str, stock_prices:dict, date: str, predicted_trend:str, df_log:pd.DataFrame):
        """
        Random Randy strategy:
        - If date is the same as the last trade date in log, do nothing and exit the function. (this happens when markets are closed!)
        - A random seed is generated using the "date" and the "ticker"arguments. 
        - The predicted trend is randomly selected from TREND_UP, TREND_DOWN AND  NO_TREND. Incoming predicted_trend is ignored!
        - The number of shares to buy and sell is randomly selected within a range of 1 to 20.
        - else (if NO_TREND) HOLD the position.

        The BUY actions will be executed ONLY if there is enough cash available. If not, BUY as much as possible and then HOLD the position.
        """

        # If date is the same as the last trade date in log AND the ticker is the same as the last trade ticker,
        # then do nothing and exit the function. (this happens when markets are closed!)
        if date in df_log[df_log['Ticker']==ticker]['Date'].values:
            return df_log

        ticker_seed = sum([ord(char) for char in ticker])  # To make sure random seed is a function of ticker symbol
        dateFormatted = datetime.strptime(date, "%Y-%m-%d")
        random_seed = dateFormatted.year + dateFormatted.month + dateFormatted.day + ticker_seed  # random seed is a function of date and ticker symbol!
        random.seed(random_seed)  # will be incremented by 1 for each new trade

        rand_predicted_trend = random.choice(["TREND_UP", "TREND_DOWN", "NO_TREND"])
        max_shares_to_buy, max_shares_to_sell = random.randint(1, 20), random.randint(1, 20)  # random selection of shares to sell/buy within a range

        price_per_share = stock_prices[ticker]["Close"]  # We use (Adjusted) Close price to calculate the cost of the trade

        # Initialize new row for the transaction log.
        # Following columns will be added to df_log regardless of the action taken.
        new_row = {
            "Date": date,
            "Ticker": ticker,
            "Price": price_per_share,
            "Direction": rand_predicted_trend,  # will be used to execute the trade randomly below
            "Action": "NONE"  # initialized to an invalid entry to simplify code below.
        }

        # Following is the common trading logic for all investors.
        new_row = self.build_new_transaction_row(new_row, df_log, investor_name, max_shares_to_buy, max_shares_to_sell)

        # EXCEPTION FOR RANDOM TRADE: After the random trade is logged, the predicted trend is updated to the actual trend for correct comparison with other traders.
        new_row["Direction"] = predicted_trend

        # New transaction log created.
        df_log.loc[len(df_log)] = new_row  # Added to the end of df_log dataframe
        
        return df_log



def live_trading():
    trading_engine = TradingEngine()
    tickers_list = list(trading_engine.ticker_map.keys())  # price data for all available stock tickers requested
    date_selected = datetime.now().strftime("%Y-%m-%d")  # get today's date at each call

    # API call to get FAANG stock OHLCV data for today
    stock_prices = trading_engine.get_stock_prices(tickers_list, date_selected)
 
    # Run trade execution logic using stock_prices
    trading_engine.run_trade_execution(stock_prices)

    # Trigger HF Space to upload the updated trade log
    trading_engine.upload_logfile()


def test_trading():
    
    trading_engine = TradingEngine()

    tickers_list = list(trading_engine.ticker_map.keys())  # price data for all available stock tickers requested
    date_selected = trading_engine.trader_attributes["next_trade_date"]  # trade date of interest as string

    num_days_to_trade = 15
    day_counter = 0

    while day_counter < num_days_to_trade:

        # Fetch stock data of interest from FAANG Pulse AI API
        temp_date_selected = datetime.strptime(date_selected, "%Y-%m-%d") + timedelta(days=day_counter)  # datetime type operation

        stock_prices = trading_engine.get_stock_prices(tickers_list, datetime.strftime(temp_date_selected, "%Y-%m-%d"))
        #print(stock_prices)

        # Run trade execution logic using stock_prices
        trading_engine.run_trade_execution(stock_prices)

        day_counter += 1
        print(f"Day {day_counter} of {num_days_to_trade} completed.")


def test_upload_logfile():
    trading_engine = TradingEngine()
    print("Testing upload_logfile API call...")
    result = trading_engine.upload_logfile()
    print(f"Upload result: {result}")


if __name__ == "__main__":

    live_trading()
    #test_trading()
    #test_upload_logfile()

