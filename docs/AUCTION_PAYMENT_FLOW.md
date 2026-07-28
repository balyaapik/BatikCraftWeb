# Auction, Payment, and Minting Flow

## Scope

Two separate charges exist, and they are easy to confuse:

1. **The creator listing fee**, paid up front, before the work goes live.
2. **The buyer invoice**, paid after the auction, for the winning bid.

BatikCraft never stores a card number, PIN, OTP, or banking credential. Payment either
runs through the Xendit gateway or, in the manual flow, the creator states transfer
instructions on the invoice and the buyer submits a reference or proof.

---

## 1. The Creator Listing Fee

Before a listing appears on the market, the creator pays a fee derived from the starting
price.

```text
fee    = max(starting_price × fee_percent, minimum_listing_fee)
vat    = fee × vat_percent
total  = fee + vat
```

Defaults: 5%, minimum Rp10,000, VAT 11%, payable within 48 hours. Rates are managed in
Django Admin under **Payments → Platform Fee Settings** and can change without a
redeploy.

**The fee is non-refundable.** Sold or unsold, the creator pays it.

Invoice states: `pending` → `paid`, or `expired` / `cancelled`.

While the fee is outstanding, `POST /api/v1/nfts/{id}/publish/` answers
`402 Payment Required` with the full breakdown and a `checkout_url`.

Rates are **copied onto the invoice** when it is raised, so a later rate change never
rewrites an existing bill.

---

## 2. Settlement After the Auction

| State | Meaning |
| --- | --- |
| `invoiced` | The creator has billed the highest bid after the auction closed and the reserve was met |
| `accepted` | The buyer approved the invoice |
| `payment_submitted` | The buyer supplied a payment reference or proof |
| `minted` | Funds confirmed; the token was issued and the NFT entered the buyer's collection |
| `declined` | The buyer refused |
| `expired` | The deadline passed |
| `cancelled` | Withdrawn |

The buyer invoice carries `subtotal_amount` (the winning bid), `vat_amount`, and
`amount` (the total).

Every significant transition runs **inside a database transaction with the invoice and
NFT rows locked**. This is the only thing preventing a double verification or a double
mint under concurrent requests. It is not an optimisation; removing it reintroduces a
money bug.

---

## 3. Ownership

- `NFTAsset.owner` keeps the original creator, so attribution and the creator dashboard
  survive the sale.
- `NFTAsset.current_owner` holds the buyer once payment is verified.
- A completed NFT becomes `sold` and appears in the buyer dashboard's collection.

---

## 4. Minting

By default the system uses `BatikCraft Registry`, an internal registry, and generates a
Token ID and a unique mint reference.

**The system does not fabricate a blockchain transaction hash.** If a value looks like an
on-chain hash, it came from a real provider.

```env
BATIKCRAFT_MINT_NETWORK=BatikCraft Registry
BATIKCRAFT_MINT_CONTRACT_ADDRESS=
```

A public blockchain provider can be added later by replacing the mint implementation that
runs after payment, without changing any invoice state.

---

## 5. Creator Payout

After the buyer's invoice is settled, a `CreatorPayout` is recorded for
`subtotal_amount`. VAT is excluded — it is not the creator's money.

Payout states: `pending` → `processing` → `success`, or `failed`.

Automatic disbursement is off by default (`auto_payout_enabled`). The creator's payout
account needs `payout_bank_code`, `payout_account_number`, and `payout_account_holder`;
`User.has_payout_account` is true only when all three are present.

---

## 6. Payment Proof Privacy

Proof files are stored through Django storage under the `payment-proofs/` prefix and are
**never** linked as public media. The proof endpoint verifies that the requester is the
transaction's creator, its buyer, or a superuser.

Two deployment consequences follow:

- With local media, **do not** add a `location /media/payment-proofs/` block to Nginx.
  Doing so serves private financial documents to anyone with the URL.
- With R2, keep the bucket private and signed URLs on.

---

## 7. Closing Expired Auctions

Auctions do not close themselves.

```bash
python manage.py close_expired_auctions
```

Run it on a schedule. Without it, expired auctions stay open and no settlement is ever
raised.

---

## 8. Operational Note

In the manual flow, the creator must confirm that funds actually arrived — in the bank
account or wallet, outside BatikCraft — before pressing **Payment received and mint NFT**.

That button is final. The NFT becomes `sold`, the current owner becomes the buyer, and
the mint registry entry is created. There is no undo.

---

## 9. Deploying a Change to This Flow

```bash
cd /srv/batikcraft
git pull
sudo docker compose -f docker-compose.mysql.yml up -d --build
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py migrate
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py check --database default
sudo docker compose -f docker-compose.mysql.yml exec web python manage.py test core.test_auction_payment_flow
```

Check the logs:

```bash
sudo docker compose -f docker-compose.mysql.yml logs --tail=150 web
```
