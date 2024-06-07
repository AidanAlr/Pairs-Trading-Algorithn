import os
import sys
import time
import logging
import yfinance
from alpaca.data import StockLatestQuoteRequest
from utils.countdown import countdown
from utils.formatting_and_logs import green_bold_print, red_bold_print, blue_bold_print
import pandas as pd
from alpaca.trading import OrderSide, TimeInForce, PositionSide, Position
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.stream import TradingStream
from trading.account_details import AccountDetails
from alpaca.data.historical import StockHistoricalDataClient

os.environ["APCA_API_BASE_URL"] = AccountDetails.BASE_URL.value

# Configure the logging; you can adjust the level and format as needed
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def connect_to_trading_stream():
    """
    Connects to the Alpaca trading Stream using predefined API credentials.
    Returns a TradingStream object if successful, else prints an error message.
    """
    try:
        return TradingStream(
            AccountDetails.API_KEY.value, AccountDetails.API_SECRET.value, paper=True
        )
    except Exception as e:
        logging.error(e)


def pause_algo(seconds):
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(
            "\r" + "Paused Algorithm: {:2d} seconds remaining.".format(remaining)
        )
        time.sleep(1)


def get_asset_price(symbol: str) -> float:
    """
    Retrieves the current price of the given asset.
    Args:
        symbol: The symbol of the asset to retrieve the price for.
    Returns:
        The current price of the asset.
    """

    symbol = symbol.upper()
    # no keys required
    client = StockHistoricalDataClient(
        "PKNWSWFGL7X6F50PJ8UH", "1qpcAmhEmzxONh3Im0V6lzgqtVOX2xD3k7mViYLX"
    )

    # single symbol request
    request_params = StockLatestQuoteRequest(symbol_or_symbols=symbol)

    latest_quote = client.get_stock_latest_quote(request_params)

    # must use symbol to access even though it is single symbol
    price = latest_quote[symbol].ask_price
    if price == 0:
        price = round(
            yfinance.download(tickers=symbol, period="1d", interval="1m")[
                "Adj Close"
            ].iloc[-1],
            2,
        )

    return price


class Alpaca:
    """
    Alpaca class to manage trading activities.
    It handles connection to Alpaca API, managing positions, entering hedge positions,
    retrieving and displaying position data, profit calculation, and order management.
    """

    def __init__(self):
        """
        Constructor for Alpaca class.
        Initializes connection to Alpaca API, retrieves current positions,
        and sets up trading stream.
        """
        self.connected = False
        self.client = self.connect_to_alpaca(
            AccountDetails.API_KEY.value, AccountDetails.API_SECRET.value, paper=True
        )
        self.in_position = bool(self.client.get_all_positions())
        self.positions = self.client.get_all_positions()
        self.balance = self.account.buying_power

    def connect_to_alpaca(
        self, api_key: str, api_secret: str, paper: bool
    ) -> TradingClient:
        """
        Establishes a connection to the Alpaca trading service using API credentials.
        If successful, prints the connection status and available buying power.
        Returns a TradingClient object.

        Args:
        api_key (str): Alpaca API key.
        api_secret (str): Alpaca API secret.
        paper (bool): Flag for paper trading (True for paper trading, False for live trading).

        Returns:
        TradingClient: A client object to interact with Alpaca's trading services.
        """
        try:
            trading_client = TradingClient(api_key, api_secret, paper=paper)
            self.account = trading_client.get_account()
            self.connected = True
            return trading_client

        except Exception as e:
            logging.error(e)

    def send_market_order(self, symbol: str, qty: int | float, side: OrderSide | str):
        """
        Send a market order to the Alpaca API

        Args:
        symbol (str): Symbol of the stock to trade.
        qty (int): Quantity of the stock to trade.
        side (OrderSide | str): Side of the order, either 'buy' or 'sell'.

        """
        try:
            self.client.submit_order(
                order_data=MarketOrderRequest(
                    symbol=symbol.upper(),
                    qty=qty,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                )
            )
            red_bold_print(
                "Market order: {} {} shares of {} - EXECUTED AT ${}".format(
                    side, qty, symbol.upper(), get_asset_price(symbol)
                )
            )
        except Exception as e:
            print(e)

    def send_limit_order(
        self,
        symbol: str,
        qty: int | float,
        side: OrderSide | str,
        limit_price: float,
        **kwargs,
    ):
        """
        Sends a limit order to the Alpaca API.

        Args:
        symbol (str): Symbol of the stock to trade.
        qty (int): Quantity of the stock to trade.
        side (OrderSide): Side of the order, either 'buy' or 'sell'.
        limit_price (float): Limit price of the order.
        **kwargs:
            Optional arguments for take profit. Must specify take_profit=TP_PRICE.
            Optional arguments for stop loss. Must specify stop_loss=SL_PRICE.

        """
        try:
            self.client.submit_order(
                order_data=LimitOrderRequest(
                    symbol=symbol.upper(),
                    qty=qty,
                    side=side,
                    limit_price=limit_price,
                    take_profit=kwargs.get("take_profit", None),
                    stop_loss=kwargs.get("stop_loss", None),
                    time_in_force=TimeInForce.DAY,
                )
            )
            logging.info(
                "Limit order placed for {} shares of {} at {}".format(
                    qty, symbol, limit_price
                )
            )

        except Exception as e:
            red_bold_print(e)

    def enter_hedge_position(self, stock_1, stock_2, side, leverage, hr):
        """
        Enters a hedge position by placing market orders on two stocks.
        A hedge position involves buying one stock and selling another.

        Args:
        stock_1 (str): Symbol of the first stock.
        stock_2 (str): Symbol of the second stock.
        side (str): 'buy' or 'sell', indicating the direction of the hedge.
        leverage (float): Leverage factor to apply to the order quantity.
        hr (float): Hedge ratio to calculate the quantity of the second stock.
        """
        stock_2_side = None
        if side == "buy":
            stock_2_side = OrderSide.SELL
            logging.info(
                "This position will purchase {} shares of {} and short {} shares of {} ".format(
                    leverage, stock_1, hr * leverage, stock_2
                )
            )
        elif side == "sell":
            stock_2_side = OrderSide.BUY
            logging.info(
                "This position will short {} shares of {} and purchase {} shares of {} ".format(
                    leverage, stock_1, hr * leverage, stock_2
                )
            )

        side_map = {OrderSide.BUY: "buy", OrderSide.SELL: "sell"}
        try:
            self.send_market_order(stock_1, leverage, side)
            self.send_market_order(
                stock_2, round(hr * leverage, 2), side_map[stock_2_side]
            )
            red_bold_print("Hedge position filled!")
        except Exception as e:
            print(e)

    def get_positions_dict(self):
        if self.in_position:
            return self.client.get_all_positions()

    def get_open_position_for_symbol(self, symbol_or_asset_id) -> Position:
        """
        Get the open position for a symbol or asset ID.

        Args:
            symbol_or_asset_id: The symbol or asset ID to get the open position for.

        Returns:
            The open position for the symbol or asset ID.
        """
        return self.client.get_open_position(symbol_or_asset_id=symbol_or_asset_id)

    def close_position_for_symbol(self, symbol_or_asset_id):
        """
        Close a position for a symbol or asset ID.

        Args:
            symbol_or_asset_id: The symbol or asset ID to close the position for.

        Returns:
            The closed position for the symbol or asset ID.
        """
        return self.client.close_position(symbol_or_asset_id=symbol_or_asset_id)

    def get_positions_df(self):
        """
        Retrieves and formats the current positions into a DataFrame.
        Converts specific string columns to float for numerical analysis.
        Returns a DataFrame of the current positions.

        Returns:
        pandas.DataFrame: DataFrame containing details of current positions.
        """
        assets = pd.DataFrame()
        if self.in_position:
            for n in range(len(self.client.get_all_positions())):
                pos = dict(self.client.get_all_positions()[n])
                pos = pd.DataFrame.from_dict(pos, orient="index").T
                assets = pd.concat([assets, pos])

                # Changing columns from str to float type
                columns_to_convert = [
                    "unrealized_pl",
                    "cost_basis",
                    "market_value",
                    "avg_entry_price",
                    "qty",
                    "unrealized_plpc",
                ]
                for column in columns_to_convert:
                    assets[column] = assets[column].astype(float)
        return assets

    def print_positions(self):
        """
        Prints the details of the current positions held.
        Includes the side (Long/Short), quantity, purchase price, and unrealized profit percentage.
        """
        portfolio = self.client.get_all_positions()
        side_map = {PositionSide.SHORT: "Short", PositionSide.LONG: "Long"}
        print("Current Positions:")
        if portfolio:
            for position in portfolio:
                print(
                    "{} {} shares of {} purchased for {} current unrealised profit_pc is {}%".format(
                        side_map[position.side],
                        position.qty.replace("-", ""),
                        position.symbol,
                        abs(float(position.cost_basis)),
                        self.get_unrealised_profit_pc(),
                    )
                )
        else:
            print("No positions")

    def get_absolute_unrealised_profit(self):
        """
        Calculates the absolute value of unrealized profit or loss across all positions.
        Returns the absolute value of unrealized profit or loss.

        Returns:
        float: The absolute value of unrealized profit or loss.
        """
        try:
            portfolio = self.client.get_all_positions()
            profit = sum([float(position.unrealized_pl) for position in portfolio])
            return profit

        except Exception as e:
            print(e)

    def get_unrealised_profit_pc(self):
        """
        Calculates the percentage of unrealized profit or loss across all positions.
        Returns the percentage value rounded to three decimal places.

        Returns:
        float: The percentage of unrealized profit or loss.
        """
        try:
            portfolio = self.client.get_all_positions()
            cost_basis = sum([float(position.cost_basis) for position in portfolio])

            if cost_basis == 0:
                return 0

            profit_pc = round(
                (self.get_absolute_unrealised_profit() * 100 / cost_basis), 3
            )
            return profit_pc

        except Exception as e:
            print(e)

    def check_and_take_profit(self, tp):
        """
        Executes orders to take profit if the unrealized profit percentage exceeds the specified threshold.

        Args:
        tp (float): The profit threshold percentage to trigger selling.
        """
        assert tp > 0, "Take profit must be a positive value"
        logging.warning("Checking if take profit is triggered...")

        if self.get_unrealised_profit_pc() > tp:
            logging.info("Executing orders to take profit...")
            return self.close_all_positions()

    def check_and_stop_loss(self, sl):
        """
        Executes stop loss orders if the unrealized loss exceeds the specified threshold.

        Args:
        sl (float): The loss threshold percentage to trigger selling.
        """
        sl = abs(sl) * -1
        assert sl <= 0, "Stop loss must be a negative value"
        logging.warning("Checking if stop loss is triggered...")
        if self.get_unrealised_profit_pc() < sl:
            logging.info("Executing stop loss orders...")
            return self.close_all_positions()

    def close_all_positions(self):
        """
        Closes all positions by submitting market or limit orders.
        If unable to submit a market order, it submits a limit order at the current price.
        Returns True if all orders are filled, False otherwise.

        Returns:
        bool: True if all positions are closed successfully, False otherwise.
        """
        self.in_position = bool(self.client.get_all_positions())

        if not self.in_position:
            print("No positions to close")
            return False

        else:
            try:
                close_info = self.client.close_all_positions(cancel_orders=True)
                countdown(2)

                for order in close_info:
                    order = order.body
                    side_map = {OrderSide.BUY: "buy", OrderSide.SELL: "sell"}
                    print(
                        f"Status: {order.status.value} - Attempted to {side_map[order.side]} {order.qty} shares of {order.symbol}"
                        f" at ${get_asset_price(order.symbol)}"
                    )

                countdown(3)
                self.in_position = bool(self.client.get_all_positions())
                print(f"Exited positions: {not self.in_position}")
                return not self.in_position

            except Exception as e:
                print(f"Exception occured closing positions: {e}")

    def live_profit_monitor(self, seconds):
        """
        Prints the current unrealized profit percentage
        """

        count = seconds
        self.in_position = bool(self.client.get_all_positions())

        if self.in_position:
            while count > 0:
                try:
                    clear_terminal()

                    # Format the DataFrame as a table
                    table = self.get_positions_df()
                    table = table[
                        ["symbol", "side", "qty", "avg_entry_price", "unrealized_pl"]
                    ]
                    curr_time = pd.Timestamp.now().time().strftime("%X")
                    output = f"{curr_time} Current Profit: {self.get_unrealised_profit_pc()} %"

                    # Move cursor to the beginning of the line
                    sys.stdout.write("\r")
                    sys.stdout.write(output)
                    sys.stdout.flush()

                    # Move cursor to the beginning of the next line to overwrite old text
                    sys.stdout.write("\n")

                    # Overwrite the line with padding
                    with pd.option_context(
                        "display.max_rows",
                        None,
                        "display.max_columns",
                        None,
                        "display.precision",
                        3,
                    ):
                        print(table)

                    time.sleep(1)
                    count -= 1

                except Exception as e:
                    print(f"An error occurred: {e}")
                    break

        else:
            print("No positions to monitor")


def clear_terminal():
    # For Windows
    if os.name == "nt":
        _ = os.system("cls")
    # For Unix/Linux/MacOS
    else:
        _ = os.system("clear")
