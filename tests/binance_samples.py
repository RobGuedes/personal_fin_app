"""Anonymized Binance records: real field layout and timestamp shapes; invented amounts, ids, addresses and hashes."""

FAKE_ADDRESS = "0xFAKE000000000000000000000000000000009001"

DEPOSIT = {
    "id": "FAKEDEP0000000001",
    "amount": "456.78",
    "coin": "USDT",
    "network": "TRX",
    "status": 1,
    "address": "TFAKE0000000000000000000000000000A",
    "addressTag": "",
    "txId": "FAKETX00000000000000000000000000000000000000000000000000000001",
    "insertTime": 1790834584000,  # 2026-10-01T06:03:04Z
    "completeTime": 1790834590000,
    "transferType": 0,
    "confirmTimes": "1/1",
    "unlockConfirm": 0,
    "walletType": 0,
    "travelRuleStatus": 0,
}

WITHDRAWAL = {
    "id": "FAKEWD0000000000000000000000001",
    "amount": "654.32",
    "transactionFee": "0.01",
    "coin": "USDT",
    "status": 6,
    "address": FAKE_ADDRESS,
    "txId": "0xFAKETX0000000000000000000000000000000000000000000000000000000002",
    "applyTime": "2026-07-06 19:54:29",
    "network": "BSC",
    "transferType": 0,
    "info": "FAKEINFO",
    "confirmNo": 20,
    "walletType": 0,
    "txKey": "",
    "completeTime": "2026-07-06 19:55:10",
}

FIAT_DEPOSIT = {
    "orderNo": "FAKEORDER0001",
    "fiatCurrency": "BRL",
    "indicatedAmount": "1000.00",
    "amount": "990.00",
    "totalFee": "10.00",
    "method": "BankTransfer",
    "status": "Successful",
    "createTime": 1790834584000,
    "updateTime": 1790834590000,
}

# REALTIME rewards on two consecutive days (23:59:59 UTC-ish, i.e. 20:59:59 local)
REWARD_D1 = {"asset": "USDT", "rewards": "0.1", "productId": "USDT001",
             "type": "REALTIME", "time": 1790899199000}  # 2026-10-01T23:59:59Z
REWARD_D2 = {"asset": "USDT", "rewards": "0.1", "productId": "USDT001",
             "type": "REALTIME", "time": 1790985599000}  # 2026-10-02T23:59:59Z

AIRDROP = {
    "id": 1111111111111111111,
    "tranId": 222222222222,
    "asset": "BNB",
    "amount": "0.00000054",
    "divTime": 1793430924000,  # 2026-10-31T07:15:24Z
    "enInfo": "BNB Vault",
    "direction": 1,
}
