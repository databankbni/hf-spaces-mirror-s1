---
title: FAANG Robotrader
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.9.0
app_file: app.py
pinned: false
license: apache-2.0
---

# FAANG-Robotrader Guide

## Application Summary
This application uses the [FAANG Pulse AI](https://huggingface.co/spaces/ML-Owl/FAANG-Pulse-AI) ML inference engine under the hood and is created as a platform to evaluate how well the inference engine performs in the real world over a period of time using previously unseen data. As part of this evaluation, 4 virtual personas, each with a different risk tolerance and stock investment strategy have been created to provide real-world context for the evaluation process.

## Robotrader Architecture and Operation
Top-level architecture of the robotrader is shown in [Figure 1](#fig1-arch-diagram). The following are the 3 core components of the system:

**1 -** FAANG Pulse AI Hugging Face Space  
**2 -** Github Workflows  
**3 -** FAANG Robotrader Hugging Face Space  


<div align=center>

<a id="fig1-arch-diagram"></a>

#### Figure 1 - System Architecture

<img src="docs/Robotrader_diagram.png" alt="Robotrader diagram" width="80%" />

</div>

Next, we will take a closer look at the role of each core component in the system.

**1 - FAANG Pulse AI Hugging Face Space**: This is the machine learning (ML) inference engine where my pre-trained Isolation Forest model runs. It includes a GUI (created using Gradio) and a public API. You can use the GUI to check trending information on each of the FAANG stocks for any given day (starting from 2013). I would encourage you to [try the application](https://huggingface.co/spaces/ML-Owl/FAANG-Pulse-AI) using the GUI to get a better understanding of the API I will be explaining next.

This application exposes the following two API endpoints, which are very easy to use:  
- **/get_prices_on_date:** You provide a date and a list of FAANG stock tickers to this API, which will then return JSON data that includes the OHLCV data for each stock for the selected date. This API makes life easier for developers to acquire stock information without having to deal with the Yahoo Finance API explicitly (note how Pulse AI talks to the Yahoo Finance API as shown in [Figure 1](#fig1-arch-diagram))

- **/run_trend_prediction:** This provides access to the ML inference engine on Pulse AI. You provide the stock ticker, date of interest and the decision threshold (i.e., the level of risk tolerance) to use, and the inference engine makes a prediction on whether the stock is trending up (**TREND_UP**), trending down (**TREND_DOWN**) or not trending at all (**NO_TREND**) based on the preceding 30 days (starting from the selected date) of price movements for that stock.

The robotrader application calls the above two API end points to get all the stock market related data as well as the ML trend predictions for the FAANG stocks.

**2 - GitHub Workflows**: You can think of GitHub Workflows as a programmable "conveyor belt" for your code. Whenever you do something in your repository (e.g., push new code or open a pull request), this conveyor belt automatically kicks in to perform repetitive tasks like testing, building, or deploying your project. Workflows are defined by simple **\*.yml** text files that are stored in a specific folder called *.github/workflows*. Essentially, workflows are your project's personal assistant that never sleeps and follows instructions perfectly.

In this application, as shown in [Figure 1](#fig1-arch-diagram), I created two workflows:

- **sync to HF:** When creating a Space on Hugging Face, you normally use it as your code repository as well as the GUI for your application. However, for people using the free version of Hugging Face, a Space goes to sleep and becomes unresponsive after some time (typically 24 hours but this may vary). This means unless the Space is woken up by a user visiting it, no background process can be executed during sleep. Because the robotrader application needs to automatically access the real-world pricing information and update its internal trader logs once a day after the markets close, this imposed sleep function on Hugging Face had to be managed.

    In order to get around the above issue, I created a GitHub repository, whose mirror is pushed to the Hugging Face repository, where the results are served using the Gradio GUI in the Space created. In this arrangement, I make all my core modifications and updates on my GitHub repository and push my changes to it. When the "sync to HF" workflow notices the change to my GitHub repo (which is almost instantaneous), all changes are automatically pushed to the Hugging Face mirror repository. Any change on the Hugging Face repo triggers an auto-rebuild (which is entirely managed by Hugging Face), after which the Space restarts and displays the updated information. 

- **daily cron:** This workflow executes the *trading_logic.py* script once each day after the US stock market closes, and executes the trades based on each investor's strategy. The trade log of each investor (as a \*.csv file) is also updated automatically.
    
    After the trade log of each investor is updated, these changes are automatically staged, committed and pushed to the Hugging Face (mirror) repository. When the Hugging Face receives the changes, it automatically rebuilds the Space, after which the most up-to-date information is served to the users via the GUI. 

Thanks to the above two workflows, the GitHub repository and Hugging Face repository remain in sync at all times while the visitors of Robotrader always see most up to date information on the progress of the investors.

**3 - FAANG Robotrader Hugging Face Space:** To understand the operation of the Robotrader, let's look at the two core functions it runs as illustrated in [Figure 1](#fig1-arch-diagram).

- **Trading Logic:** This is the script that is auto-executed once a day to fetch the current prices for FAANG stocks and to execute BUY, SELL, or HOLD actions for each investor depending on the risk tolerance and the investment strategy defined for each. This module also keeps track of each trade transaction for each trader in a dedicated \*csv file, which is the central source of information the user interface uses to generate a number of evaluation reports.

    As described in the workflow section above, the trading logic is called and executed automatically on the GitHub repository, which also does not use any Hugging Face compute resources. 😉 Once the required computations are completed on GitHub, the updated \*.csv files are simply pushed to the Hugging Face repository to keep everything in sync.

- **The User Interface (GUI):** The user interface is the mechanism whereby the trade log of each investor is displayed as generated tables on demand. Please note the actions performed on the GUI use the information provided in each \*.csv file, which is updated once daily by the Trading Logic process.

    The GUI is intentionally kept simple with one drop-down menu for the user to interact with. Each menu selection triggers the generation of a table that is displayed below the drop down menu. Next let's take a close look at each menu item and see how to interpret the information displayed on each table.

    - **Trade Actions Summary:** This option generates a table with a high-level view of the executed trades for each investor by the Robotrader. This table includes the following columns:
        - ***Investor***: Includes the name of investors.
        - ***Start Date***: This is the date of the first trade transaction for an investor. This will be the same for all investors to allow a fair comparison.
        - ***End Date***: This is the last date on the transaction record for an investor. End Date for all investors is the same and is updated each day.
        - ***HOLD Trades (%)***: In this column, two information fields per cell are included. The first one gives the total count of all HOLD transactions executed while the second one in parentheses is the percentage of HOLD trades for the investor. Note this count is an aggregation of all of the 5 FAANG stock transactions for the investor.
        - ***SELL Trades (%)***: This is the same as the HOLD column but exclusively for all the SELL transactions for an investor.
        - ***BUY Trades (%)***: This is the same as the HOLD and SELL columns but exclusively for all the BUY transactions for an investor.
        - ***Shares Owned***: The total number of all FAANG shares owned on the End Date for an investor is listed in this column.

    - **Cash Status:** This is the second option in the drop down menu, which generates a table summarizing the cash outlook of each investor. The following columns are included in this table.
        - ***Investor***: Includes the name of investors.
        - ***Start Date***: This is the date of the first trade transaction for an investor. Start Date will be the same for all investors to allow a fair comparison.
        - ***End Date***: This is the last date on the transaction record for an investor. End Date for all investors will be the same and is updated each day.
        - ***Starting Cash ($)***: Each investor's starting cash allocation for the Robotrader is listed in US Dollars in this column. The starting cash is fixed at $500,000 for each investor for a fair comparison.
        - ***Value of Shares Owned ($)***: This is the combined dollar amount for all owned FAANG shares by an investor calculated based on the End Date sell price for each stock.
        - ***Investable Cash ($)***: The remaining cash that is left for investing from the Starting Cash amount (after all the buy and sell trades until the End Date)
        - ***Portfolio Value ($)***: This is the sum of the cash Value of Shares Owned and the Investable Cash. When this amount exceeds the Starting Cash, an investor will have positive ROI.
        - ***Projected Return ($ (%))***: This column summarizes the gain/loss of an investor if they were to sell all the shares they owned at the End Date price for ***each owned FAANG stock***. There are two figures per cell in this column; one is the dollar amount and the other is the percentage relative to the Starting Cash. Gain is color coded with green, while red indicates loss. Orange indicates neutral standing.

    - **Per Stock Returns:** This option in the drop down menu generates a table summarizing the cash outlook of each investor based on each of the FAANG stocks. In other words, this information is a mixture of the Cash Status and the Trade Actions provided on a per stock basis. Following columns are included in this table. Let's take a look at each of the columns in this table to get a clearer understanding of the information presented.
        - ***Investor***: Includes the name of investors.
        - ***Ticker***: The ticker symbol of the FAANG stock.
        - ***Start Date***: This is the date of the first trade transaction for an investor. This will be the same for all investors to allow a fair comparison.
        - ***End Date***: This is the last date on the transaction record for an investor. End Date for all investors is the same and is updated each day.
        - ***Shares Owned***: The number of shares for a given ticker the investor currently owns.
        - ***Buy Total ($)***: Total dollar amount an investor has spent on buying the shares of a FAANG company with the specified ticker.
        - ***Sell Total ($)***: Total dollar amount an investor has earned by selling the shares of a FAANG company with the specified ticker.
        - ***Projected Return ($ (%))***: This column summarizes the gain/loss of an investor ***on a particular stock (specified by the ticker)*** if they were to sell the shares they owned at the End Date price. There are two figures per cell in this column; one is the dollar amount and the other is the percentage relative to the Starting Cash. Gain is color coded with green, while red indicates loss. Orange indicates neutral standing.

## Meet the Traders

There are 4 virtual traders in Robotrader each with a different investment strategy and risk tolerance. Let's meet them and see how they trade using the Robotrader.

- **Safe Sam** is the most cautious of the four traders. He understands how volatile FAANG stocks can be and knows that genuine, sustained trends are relatively rare. Because of that, he stays patient and avoids reacting to noise. He only acts when the model signals a clear directional move, making him a true “sniper” investor: selective, disciplined, and deliberate.

    When Sam sees a strong opportunity, he commits with conviction. His strategy is simple:
    - If the predicted trend is **TREND_UP**, BUY 50 shares  
    - If the predicted trend is **TREND_DOWN**, SELL 100 shares  
    - If the prediction is **NO_TREND**, HOLD  

    Sam's larger sell size reflects his view that meaningful downward moves are less common and can be brief, so he acts decisively to lock in gains when they appear. Although he trades less often than the others, each trade is intentional and relatively large. He does not chase the market. He waits, aims carefully, and acts only when the odds appear strongly in his favor.

- **Optimal Owen** has a higher risk tolerance than Safe Sam and trades more often. Rather than waiting only for the clearest signals, Owen follows the machine learning model’s decision threshold exactly as determined from training, validation, and test performance. He trusts the model to balance missed opportunities against false alarms in a statistically informed way.

    Owen understands that in FAANG stocks, meaningful trend events are often rare and partially buried in market noise. To avoid missing those opportunities, he is willing to accept a higher number of false positives and the occasional losing trade. In other words, Owen prefers a strategy that captures more real trends, even if that means acting on some imperfect signals along the way.

    Owen's strategy is as follows:  
    - If the predicted trend is **TREND_UP**, BUY 20 shares  
    - If the predicted trend is **TREND_DOWN**, SELL 20 shares  
    - If the prediction is **NO_TREND**, HOLD  

    Compared with Sam, Owen trades with smaller position sizes but at a higher frequency. This makes his behavior more balanced and sustainable over time: he commits less capital per trade, preserves flexibility, and gives himself a longer runway to participate in more opportunities while operating with the same starting budget.

- **Brave Beth** is the boldest among all traders. She has a higher risk tolerance than both Owen and Sam and is far more willing to act on imperfect signals. While more cautious traders wait for clearer evidence of a real trend, Beth would rather stay active in the market and accept the possibility of being wrong if it means she has a chance to capture more upside.

    Beth is motivated not only by profit, but also by the fast-moving, high-stakes nature of trading itself. She believes markets are driven as much by human behavior, sentiment, and overreaction as they are by clean mathematical patterns. Because of that, she is less interested in waiting for the model’s most statistically optimal trading region and more comfortable operating in noisier territory where potential opportunities may appear earlier, even if the risk of false positives is higher.

    Beth's strategy is as follows:  
    - If the predicted trend is **TREND_UP**, BUY 10 shares  
    - If the predicted trend is **TREND_DOWN**, SELL 10 shares  
    - If the prediction is **NO_TREND**, HOLD  

    Beth’s higher trading frequency is balanced by her smaller position size. That allows her to stay active for longer, manage cash more carefully, and pursue frequent opportunities without exhausting her capital too quickly. She may not wait for perfect setups, but that is exactly what makes her the most fearless trader in the group.

- **Random Randy** is the skeptic of the group. He has come across research suggesting that randomized portfolios and simple chance-driven strategies can sometimes perform as well as, or even outperform, carefully designed trading strategies. That has made him doubtful that machine learning can consistently deliver an edge in trading. Rather than dismissing the idea outright, Randy has turned his skepticism into an experiment: he uses a fully randomized strategy to test whether FAANG trading outcomes are meaningfully better when decisions are guided by the model instead of chance.

    Randy’s method is intentionally simple and completely independent of the machine learning prediction. To keep the process reproducible, he generates a random seed from the date and the ticker, ensuring that each stock on each trading day produces a consistent random outcome.

    Randy's trading strategy can be summarized as follows:  
    - For each FAANG stock on each trading day, Randy randomly selects one of **TREND_UP**, **TREND_DOWN**, or **NO_TREND**.  
    - If the random outcome is **TREND_UP**, he randomly chooses a number from 1 to 20 and buys that many shares.  
    - If the random outcome is **TREND_DOWN**, he randomly chooses a number from 1 to 20 and sells that many shares.  
    - If the random outcome is **NO_TREND**, he holds the position.  

    Randy caps each buy or sell transaction at 20 shares per stock to keep the strategy bounded and comparable to the others. If his random outcome is anything other than **NO_TREND**, he always executes at least one trade. In effect, *Randy serves as the app’s experimental benchmark*: if a machine learning-driven trader cannot consistently outperform Randy over time, that raises an important question about whether the model is providing real value at all.

## Citation

Use DOI: 10.5281/zenodo.20618232 if you would like to cite this work.

Alternatively, please use the citation format below:

APA Format: Tanriover, C. (2026). FAANG-Robotrader Application v1.0.0 (v1.0.0). https://doi.org/10.5281/zenodo.20618233

