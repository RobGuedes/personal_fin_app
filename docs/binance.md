# Binance integration (read-only)

Binance is one more account in the same ledger as the Pluggy accounts: classification, rules, the review
queue, aggregation and the web app work unchanged. Enabled when `BINANCE_API_KEY` is set in `.env`.

## Endpoints (read-only key, signed GETs unless noted)

| Data | Endpoint | Notes |
|---|---|---|
| Crypto deposits | `/sapi/v1/capital/deposit/hisrec` | 90-day windows. Included when `status = 1`. |
| Crypto withdrawals | `/sapi/v1/capital/withdraw/history` | 90-day windows. Included when `status = 6`. |
| Fiat orders (BRL in/out) | `/sapi/v1/fiat/orders` | Very heavy weight: HTTP 429 after a few calls; paced ~1 call/min (shared pacer), honour `Retry-After`. |
| Fiat buys | `/sapi/v1/fiat/payments` | Movement inside Binance: not written. |
| Convert | `/sapi/v1/convert/tradeFlow` | 30-day windows. Movement inside Binance: not written. |
| Simple Earn rewards | `/sapi/v1/simple-earn/{flexible,locked}/history/rewardsRecord` | 30-day windows; history only from when Earn was first used. Fetch `type=REALTIME` only. |
| Distributions | `/sapi/v1/asset/assetDividend` | 180-day windows, 500/page. BONUS tiers + airdrops; identical to `rewardsRecord?type=BONUS`, so BONUS is not fetched separately. |
| Pay | `/sapi/v1/pay/transactions` | 89-day windows, ~18 months back. |
| Wallet transfers | `/sapi/v1/asset/transfer` | Only the last 6 months are queryable. |
| Balances | `/api/v3/account`, `/sapi/v1/asset/wallet/balance`, `/sapi/v1/simple-earn/flexible/position` | `LD*` spot assets are Earn positions mirrored in Spot: excluded. The per-asset Funding endpoint is a POST; the client is GET-only, so Funding is one BTC-valued row from `wallet/balance`. |
| Key permissions | `/sapi/v1/account/apiRestrictions` | Sync refuses keys with any write permission and warns if the key is not IP-restricted. |
| Prices | `GET /api/v3/klines?symbol=<PAIR>&interval=1d&timeZone=-3` | Public, unsigned. Close of the local day. |

HTTP 418 (IP ban) stops the Binance sync immediately with the ban duration.

## Data model

- `items` / `accounts`: one row each with id `'binance'` (`subtype = 'BINANCE'`, `role = 'investment'` on insert,
  never overwritten). `accounts.balance` = BRL value of the latest positions.
- `fx_rates(date, pair, close)`: local calendar day (America/Sao_Paulo).
- `binance_positions(snapshot_at, wallet, asset, amount, brl_value)`: `brl_value` NULL when unpriced.

## Rows written to `transactions`

`amount` = coin units (in > 0, out < 0), `currency` = coin, `amount_normalized` = BRL at the local day's close
(stored to 6 dp), `date` = local day of the event, `payment_method = 'other'`, `raw_json` = the Binance record.

| Event | id | description |
|---|---|---|
| Crypto deposit | `binance:dep:<id>` | `Binance deposit USDT (TRX)` |
| Crypto withdrawal | `binance:wd:<id>` | `Binance withdrawal USDT (BSC) → …1234` (amount includes the fee) |
| Fiat order | `binance:fiat:<orderNo>` | `Binance BRL deposit` / `Binance BRL withdrawal` |
| Earn & distributions | `binance:earn:<YYYY-MM>:<asset>` | `Binance Earn interest <asset> <YYYY-MM>` (monthly roll-up; each day converted at its own rate) |

- Only the last 4 characters of an address are shown (`counterparty_name = "…1234"`); full addresses, tx hashes
  and ids stay in `raw_json`.
- Sync never deletes Binance rows (all included statuses are final).

## Prices

`<ASSET>BRL` when listed, else `<ASSET>USDT × USDTBRL`; `BRL` = 1. 3-day previous-close fallback, else
`amount_normalized = 0` and a warning (once per asset). "Unpriced" = `amount != 0 and amount_normalized == 0`
(`binance_normalize.is_unpriced`): re-priced on every sync, classified at confidence 0.5 (review queue). The last
stored close of each pair is re-fetched on the next sync, so a partial close of "today" never sticks.

## Sync and classification

- `finance sync` runs Pluggy first, then Binance (`--skip-binance` to opt out). A Binance failure is reported and
  never fails or rolls back the Pluggy part (exit code 1).
- First run: full history (~18 months); later runs: from the earlier of now and the last successful sync, minus
  `--window-days`. Earn windows start at the month's first day.
- Binance rows carry no CPF/name, so the transfer detector does not pair them. Use rules on `account: "Binance"`
  (see `config/rules.example.yaml`: `binance_fiat`, `binance_earn`, `binance_pix`); add your own for deposits or
  withdrawal addresses (matched by the masked `…1234` suffix).
