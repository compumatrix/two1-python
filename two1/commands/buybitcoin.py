import click
from datetime import datetime

from two1.commands.config import TWO1_HOST, TWO1_WEB_HOST
from two1.lib.util.exceptions import TwoOneError, UnloggedException
from two1.lib.server import rest_client
from two1.lib.server.analytics import capture_usage
from two1.lib.util.decorators import json_output
from two1.lib.util.uxstring import UxString


@click.group(invoke_without_command=True)
@click.option('-e', '--exchange', default='coinbase', type=click.Choice(['coinbase']),
              help="Select the exchange to buy Bitcoins from")
@click.option('--pair', is_flag=True, default=False,
              help="Shows instructions on how to connect you Bitcoin Computer to an exchange "
                   "account")
@click.option('--status', is_flag=True, default=False,
              help="Shows the current status of your exchange integrations")
@click.argument('amount', default=0, type=click.FLOAT)
@click.argument('unit', default='satoshi', type=click.Choice(['usd', 'btc', 'satoshi']))
@json_output
def buybitcoin(click_config, pair, status, exchange, amount, unit):
    """Buy Bitcoins from an exchange
    """
    return _buybitcoin(click_config, pair, status, exchange, amount, unit)


@capture_usage
def _buybitcoin(click_config, pair, status, exchange, amount, unit):
    client = rest_client.TwentyOneRestClient(TWO1_HOST,
                                             click_config.machine_auth,
                                             click_config.username)

    if pair:
        return buybitcoin_config(click_config, client, exchange)
    else:
        if amount <= 0 or status:
            return buybitcoin_show_status(click_config, client, exchange)
        else:
            return buybitcoin_buy(click_config, client, exchange, amount, unit)


def buybitcoin_show_status(config, client, exchange):
    resp = client.get_coinbase_status()
    if not resp.ok:
        raise TwoOneError("Failed to get exchange status")

    coinbase = resp.json()["coinbase"]

    if not coinbase:
        # Not linked, prompt user to pair
        return buybitcoin_config(config, client, exchange)
    else:
        payment_method_string = click.style("No Payment Method linked yet.", fg="red", bold=True)
        if coinbase["payment_method"] is not None:
            payment_method_string = coinbase["payment_method"]["name"]

        click.secho(UxString.exchange_info_header)
        click.secho(UxString.exchange_info.format(exchange.capitalize(), coinbase["name"],
                                                  coinbase["account_name"], payment_method_string))
        if coinbase["payment_method"] is None:
            ADD_PAYMENT_METHOD_URL = "https://coinbase.com/quickstarts/payment"
            config.log(UxString.buybitcoin_no_payment_method.format(
                    exchange.capitalize(),
                    click.style(ADD_PAYMENT_METHOD_URL, fg="blue", bold=True)
            ))
        else:
            click.secho(UxString.buybitcoin_instruction_header)
            config.log(UxString.buybitcoin_instructions.format(exchange.capitalize()))
        return coinbase


def buybitcoin_config(config, client, exchange):
    config.log(UxString.buybitcoin_pairing.format(click.style(exchange.capitalize()),
                                                  config.username))


def buybitcoin_buy(config, client, exchange, amount, unit):

    deposit_type = get_deposit_info()
    get_price_quote(client, amount, unit, deposit_type)

    try:
        buy_bitcoin(client, amount, unit, deposit_type)
    except click.exceptions.Abort:
        click.secho("\nPurchase canceled", fg="magenta")


def get_price_quote(client, amount, unit, deposit_type):
    # first get a quote
    resp = client.buy_bitcoin_from_exchange(amount, unit, commit=False)

    if not resp.ok:
        raise TwoOneError("Failed to execute buybitcoin {} {}".format(amount, unit))

    buy_result = resp.json()
    if "err" in buy_result:
        click.secho(
                UxString.buybitcoin_error.format(
                    click.style(buy_result["err"], bold=True, fg="red")))
        raise TwoOneError("Failed to execute buybitcoin {} {}".format(amount, unit))

    fees = buy_result["fees"]
    total_fees = ["{} {}".format(float(f["amount"]["amount"]), f["amount"]["currency"]) for f in
                  fees]
    total_fees = click.style(" + ".join(total_fees), bold=True)
    total_amount = buy_result["total"]
    total = click.style("{} {}".format(total_amount["amount"], total_amount["currency"]), bold=True)
    bitcoin_amount = click.style("{} {}".format(amount, unit), bold=True)

    deposit_type = {"TO_BALANCE": "21.co balance", "WALLET": "Blockchain balance"}[deposit_type]
    click.secho(UxString.buybitcoin_confirmation.format(total, bitcoin_amount, total, total_fees,
                                                        deposit_type))


def buy_bitcoin(client, amount, unit, deposit_type):
    if click.confirm(UxString.buybitcoin_confirmation_prompt):
        click.secho(UxString.coinbase_purchase_in_progress)
        resp = client.buy_bitcoin_from_exchange(amount, unit, commit=True, deposit_type=deposit_type)
        buy_result = resp.json()
        if buy_result["status"] == "canceled":
            click.secho(UxString.buybitcoin_error.format(
                click.style("Buy was canceled.", bold=True, fg="red")))

            return buy_result

        btc_bought = "{} {}".format(buy_result["amount"]["amount"],
                                    buy_result["amount"]["currency"])

        dollars_paid = "{} {}".format(buy_result["total"]["amount"],
                                      buy_result["total"]["currency"])

        click.secho(UxString.buybitcoin_success.format(btc_bought, dollars_paid))

        if deposit_type == "TO_BALANCE":
            click.secho(UxString.buybitcoin_21_balance_success)
            if "payout_at" in buy_result:
                payout_time = datetime.fromtimestamp(buy_result["payout_at"]).strftime("%Y-%m-%d "
                                                                                       "%H:%M:%S")

                click.secho(UxString.buybitcoin_21_balance_time.format(payout_time, amount, unit))

        elif "instant" in buy_result and buy_result["instant"]:
            click.secho(UxString.buybitcoin_success_instant)
        elif "payout_at" in buy_result:
            payout_time = datetime.fromtimestamp(buy_result["payout_at"]).strftime("%Y-%m-%d "
                                                                                   "%H:%M:%S")

            click.secho(UxString.buybitcoin_success_payout_time.format(payout_time))
    else:
        click.secho("\nPurchase canceled", fg="magenta")


def get_deposit_info():

    click.secho(UxString.deposit_type_question)
    deposit_types = [{"msg": UxString.deposit_type_off_chain, "value": "TO_BALANCE"},
                     {"msg": UxString.deposit_type_on_chain, "value": "WALLET"}]
    index_to_deposit = {}
    for i, deposit_type in enumerate(deposit_types):
        click.secho("{}. {}".format(i + 1, deposit_type["msg"]))
        index_to_deposit[i] = deposit_types[i]["value"]

    click.secho(UxString.deposit_type_explanation)
    try:
        deposit_index = -1
        while deposit_index <= 0 or deposit_index > len(deposit_types):
            deposit_index = click.prompt(UxString.deposit_type_prompt, type=int)
            if deposit_index <= 0 or deposit_index > len(deposit_types):
                click.secho(UxString.deposit_type_invalid_index.format(1, len(deposit_types)))

        deposit_type = index_to_deposit[deposit_index - 1]
        return deposit_type

    except click.exceptions.Abort:
        click.secho("\nPurchase canceled", fg="magenta")
        raise UnloggedException()


