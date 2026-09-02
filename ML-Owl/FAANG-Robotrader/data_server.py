import pandas as pd
import json

class investmentRecords:
    
    def __init__(self):

        self.trader_attrib = json.load(open("data/trader_attributes.json"))

        self.dfDict = {}
        # Get all logged transactions for each investor to help with the calculations
        for trader in self.trader_attrib["investors"]:
            csv_file = self.trader_attrib["investors"][trader]["trade_log_file"]
            self.dfDict[trader] = pd.read_csv(f"data/{csv_file}")

        self.available_charts = ["Trade Actions Summary", "Cash Status", "Per Stock Returns"]

        # GUI Defaults follow
        self.selected_investor = trader  # selection DEFAULT

        # Prebuilding all charts to serve to the GUI
        self.chart_df_lookup = {
            "Trade Actions Summary": self.get_trade_actions_df(),
            "Cash Status": self.get_cash_status_df(),
            "Per Stock Returns": self.get_per_stock_returns_df()
        }

        self.selected_chart = "Trade Actions Summary"  # GUI selection DEFAULT
        self.selected_chart_df = self.chart_df_lookup[self.selected_chart]  # Default chart to serve is the Trade Actions Summary


    def get_investor_names(self):
        return list(self.dfDict.keys())

    def update_selected_investor(self, selected_investor_name):
        # API update call-back function to update the selected investor
        self.selected_investor = selected_investor_name

    def get_available_charts(self):
        return self.available_charts

    def serve_selected_chart(self, selected_chart_name):
        self.selected_chart = selected_chart_name  # update the selected chart name as well
        self.selected_chart_df = self.chart_df_lookup[self.selected_chart]  # update the selected chart dataframe
        return self.selected_chart_df, self.selected_chart

    def get_trade_actions_df(self):
        """
        Create a dataframe with the time related trading info for all investors.
        Columns: Investor, Start Date, End Date, HOLD Trades (%), SELL Trades (%), BUY Trades (%), Shares Owned
        Rows: Each investor
        Values: Start Date, End Date, HOLD Trades (%), SELL Trades (%), BUY Trades (%), Shares Owned
        Returns: Dataframe with the time related trading info for all investors
        """

        columns = ["Investor", "Start Date", "End Date", "HOLD Trades (%)", "SELL Trades (%)", "BUY Trades (%)", "Shares Owned"]

        df = pd.DataFrame(columns=columns)

        for trader in self.dfDict:
            if len(self.dfDict[trader]) == 0:
                # No data available yet
                new_row = {
                    "Investor": trader,
                    "Start Date": "N/A",
                    "End Date": "N/A",
                    "HOLD Trades (%)": "0 (0.00)",
                    "SELL Trades (%)": "0 (0.00)",
                    "BUY Trades (%)": "0 (0.00)",
                    "Shares Owned": 0
                }
            else:
                # There is investor data to process
                total_trades = len(self.dfDict[trader])
                hold_trades = (self.dfDict[trader]["Action"] == "HOLD").sum()
                sell_trades = (self.dfDict[trader]["Action"] == "SELL").sum()
                buy_trades = (self.dfDict[trader]["Action"] == "BUY").sum()

                total_shares_bought = self.dfDict[trader][self.dfDict[trader]["Action"] == "BUY"]["Shares"].sum()
                total_shares_sold = self.dfDict[trader][self.dfDict[trader]["Action"] == "SELL"]["Shares"].sum()
                new_row = {
                    "Investor": trader,
                    "Start Date": self.dfDict[trader]["Date"].iloc[0],  # first date record
                    "End Date": self.dfDict[trader]["Date"].iloc[-1],  # last date record
                    "HOLD Trades (%)": f"{hold_trades} ({(hold_trades/total_trades)*100:.2f})",
                    "SELL Trades (%)": f"{sell_trades} ({(sell_trades/total_trades)*100:.2f})",
                    "BUY Trades (%)": f"{buy_trades} ({(buy_trades/total_trades)*100:.2f})",
                    "Shares Owned": (total_shares_bought - total_shares_sold)
                }

            df.loc[len(df)] = new_row  # append to the end of the data frame

        # We will style the df next before serving it to gradio for a more appealing visual look!
        return self.style_trade_actions_df(df)


    def style_trade_actions_df(self, df):
        """
        Style the trade actions dataframe for a more appealing visual look.
        """

        styled_df = (    
            df.style.apply(
                lambda columnSeries: self.style_apply_color_to_column(columnSeries, "orange"),
                subset=["HOLD Trades (%)"],
            )
            .apply(
                lambda columnSeries: self.style_apply_color_to_column(columnSeries, "green"),
                subset=["SELL Trades (%)"],
            )
            .apply(
                lambda columnSeries: self.style_apply_color_to_column(columnSeries, "blue"),
                subset=["BUY Trades (%)"],
            )
            .set_table_styles([
                {"selector": 'td, th', 'props': [('text-align', 'center'), ('padding', '10px')]}
            ])
        )

        return styled_df

    def style_apply_color_to_column(self, series, color="blue"):
        """
        Helper for `Styler.apply`: returns a style string per element in the column.
        """
        return [f"color: {color}; font-weight: bold"] * len(series)


    def style_red_green_color_format(self, value:str):
        """
        Style the background value in red if it is negative, green if it is positive, orange if zero.
        """

        numeric_part = float(value.split(" ")[0]) # First portion is enough for the comparison

        if numeric_part < 0:
            return f"background-color: red; font-weight: bold"
        elif numeric_part > 0:
            return f"background-color: green; font-weight: bold"
        else:
            return f"background-color: orange; font-weight: bold"


    def get_cash_status_df(self):
        """
        Create a dataframe with the cash status info for all investors.
        Columns: Investor, Start Date, End Date, Starting Cash ($), Value of Shares Owned ($), Investable Cash ($), Portfolio Value ($), "Projected Return ($ (%))"
        Rows: Each investor
        Values: Start Date, End Date, Starting Cash ($), Value of Shares Owned ($), Investable Cash ($), Portfolio Value ($), "Projected Return ($ (%))"
        Returns: Dataframe with the cash status info for all investors
        """

        columns = ["Investor", "Start Date", "End Date", "Starting Cash ($)", "Value of Shares Owned ($)", "Investable Cash ($)", "Portfolio Value ($)", "Projected Return ($ (%))"]

        df = pd.DataFrame(columns=columns)

        for trader in self.dfDict:
            if len(self.dfDict[trader]) == 0:
                # No data available yet
                new_row = {
                    "Investor": trader,
                    "Start Date": "N/A",
                    "End Date": "N/A",
                    "Starting Cash ($)": "N/A",
                    "Value of Shares Owned ($)": "N/A",
                    "Investable Cash ($)": "0.00",
                    "Portfolio Value ($)": "0.00",
                    "Projected Return ($ (%))": "0.00 (0.00)"
                }
            else:
                # there is investor data to process
                total_start_cash = self.dfDict[trader]["Cash Before Trade"].iloc[0]  # the first trade entry for this investor
                investable_cash = self.dfDict[trader]["Cash After Trade"].iloc[-1]  # the last trade entry for this investor
                
                tickers = self.dfDict[trader]["Ticker"].unique()

                # Scanning all tickers in the investor's transaction record.
                value_of_shares_owned = 0
                for ticker in tickers:
                    shares_bought = self.dfDict[trader][(self.dfDict[trader]["Ticker"] == ticker) & (self.dfDict[trader]["Action"] == "BUY")]["Shares"].sum()
                    shares_sold = self.dfDict[trader][(self.dfDict[trader]["Ticker"] == ticker) & (self.dfDict[trader]["Action"] == "SELL")]["Shares"].sum()
                    shares_owned = shares_bought - shares_sold
                
                    last_price_for_ticker = self.dfDict[trader][(self.dfDict[trader]["Ticker"] == ticker)]["Price"].iloc[-1]  # Last pricer for ticker at the end of the transaction record
                    value_of_shares_owned += shares_owned * last_price_for_ticker

                portfolio_value = value_of_shares_owned + investable_cash

                total_cash_invested = total_start_cash - investable_cash
                total_return = value_of_shares_owned - total_cash_invested
                if total_cash_invested == 0:
                    percentage_return = "0.00"  # no investment means zero return.
                else:
                    percentage_return = f"{(total_return/total_cash_invested)*100:.2f}%"

                new_row = {
                    "Investor": trader,
                    "Start Date": self.dfDict[trader]["Date"].iloc[0],
                    "End Date": self.dfDict[trader]["Date"].iloc[-1],
                    "Starting Cash ($)": f"{total_start_cash:.2f}",
                    "Value of Shares Owned ($)": f"{value_of_shares_owned:.2f}",
                    "Investable Cash ($)": f"{investable_cash:.2f}",
                    "Portfolio Value ($)": f"{portfolio_value:.2f}",
                    "Projected Return ($ (%))": f"{total_return:.2f} ({percentage_return})"
                }


            df.loc[len(df)] = new_row  # append to the end of the data frame

        # We will style the df next before serving it to gradio for a more appealing visual look!
        return self.style_cash_status_df(df)


    def style_cash_status_df(self, df):
        """
        Style the cash status dataframe for a more appealing visual look.
        """
        styled_df = df.style.map(
                self.style_red_green_color_format,
                subset=["Projected Return ($ (%))"]
                )

        return styled_df


    def get_per_stock_returns_df(self):
        """
        Create a dataframe with the per stock returns info for all investors.
        Columns: Investor, Ticker, Start Date, End Date, Shares Owned, Buy Total ($), Sell Total ($), Projected Return ($ (%))
        Rows: Each stock
        Values: Investor, Ticker, Start Date, End Date, Shares Owned, Buy Total ($), Sell Total ($), Projected Return ($ (%))
        Returns: Dataframe with the per stock returns info for all investors
        """
        columns = ["Investor", "Ticker", "Start Date", "End Date", "Shares Owned", "Buy Total ($)", "Sell Total ($)", "Projected Return ($ (%))"]

        df = pd.DataFrame(columns=columns)

        if len(self.dfDict[self.selected_investor]["Ticker"])==0:
            for trader in self.dfDict:
                # No data available yet
                new_row = {
                    "Investor": trader,
                    "Ticker": "N/A",
                    "Start Date": "N/A",
                    "End Date": "N/A",
                    "Shares Owned": 0,
                    "Buy Total ($)": "0.00",
                    "Sell Total ($)": "0.00",
                    "Projected Return ($ (%))": "0.00 (0.00)"
                }

                df.loc[len(df)] = new_row  # append to the end of the data frame

            # We will style the df next before serving it to gradio for a more appealing visual look!
            return self.style_per_stock_returns_df(df) 


        # There is ticker data to process for investors
        for ticker in self.dfDict[self.selected_investor]["Ticker"].unique():

            for trader in self.dfDict:
                sub_df = self.dfDict[trader][(self.dfDict[trader]["Ticker"] == ticker) & (self.dfDict[trader]["Action"] == "BUY")]
                total_spent_on_buy = (sub_df["Price"]*sub_df["Shares"]).sum()
                total_shares_bought = sub_df["Shares"].sum()

                sub_df = self.dfDict[trader][(self.dfDict[trader]["Ticker"] == ticker) & (self.dfDict[trader]["Action"] == "SELL")]
                total_earned_on_sell = (sub_df["Price"]*sub_df["Shares"]).sum()
                total_shares_sold = sub_df["Shares"].sum()

                last_price_for_ticker = self.dfDict[trader][(self.dfDict[trader]["Ticker"] == ticker)]["Price"].iloc[-1]  # Last pricer for ticker at the end of the transaction record
                total_shares_owned = total_shares_bought - total_shares_sold
                unrealized_earnings = total_shares_owned*last_price_for_ticker

                projected_return = unrealized_earnings + total_earned_on_sell - total_spent_on_buy

                if total_spent_on_buy == 0:
                    projected_return_percentage = 0   # no investment means zero return.
                else:
                    projected_return_percentage = (projected_return/total_spent_on_buy)*100

                new_row = {
                    "Investor": trader,
                    "Ticker": ticker,
                    "Start Date": self.dfDict[trader]["Date"].iloc[0],
                    "End Date": self.dfDict[trader]["Date"].iloc[-1],
                    "Shares Owned": total_shares_owned,
                    "Buy Total ($)": f"{total_spent_on_buy:.2f}",
                    "Sell Total ($)": f"{total_earned_on_sell:.2f}",
                    "Projected Return ($ (%))": f"{projected_return:.2f} ({projected_return_percentage:.2f})"
                }


                df.loc[len(df)] = new_row  # append to the end of the data frame

        # We will style the df next before serving it to gradio for a more appealing visual look!
        return self.style_per_stock_returns_df(df)


    def style_per_stock_returns_df(self, df):
        """
        Style the per stock returns dataframe for a more appealing visual look.
        """
        styled_df = df.style.map(
                self.style_red_green_color_format,
                subset=["Projected Return ($ (%))"]
                )

        return styled_df


### Display returns for each FAANG stock (e.g. for each stock: total spent via BUY actions, total return via SELL actions, %return = (SELL-BUY)/BUY)

if __name__ == "__main__":
    invObj = investmentRecords()
    df = invObj.get_trade_actions_df()
    print(df)
    df = invObj.get_cash_status_df()
    print(df)
    df = invObj.get_per_stock_returns_df()
    print(df)