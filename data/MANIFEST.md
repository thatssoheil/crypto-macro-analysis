# Data MANIFEST

Updated: 2026-07-24

## FTMO symbol dump
- Raw: `data/ftmo_symbols.csv` (167 symbols; descriptions contain commas)
- Clean: `data/ftmo_symbols_clean.csv`
- Status: **done 2026-07-24**

### Categories
Forex 28 | Exotics 15 | Cash CFD indices 5 | Cash II 10 | Metals 9 | Crypto ~31 | Equities ~59 | Ag 7 | other

### Primary trade names (exact MT5)
| FTMO name | Class | Contract | Research proxy |
|-----------|-------|----------|----------------|
| **US30.cash** | Dow CFD | 1 | data/US30_D1.csv |
| **US100.cash** | NAS100 | 1 | data/US100_D1.csv |
| **US500.cash** | SPX | 1 | data/US500_D1.csv |
| US2000.cash | RUT | 1 | (fetch later) |
| GER40.cash | DAX | 1 | data/GER40_D1.csv |
| XAUUSD | Gold | 100 | data/XAUUSD_D1.csv |
| USOIL.cash | WTI | 100 | data/USOIL_D1.csv |
| EURUSD / GBPUSD | FX | 100000 | existing H1/D1 |
| AUDCAD | FX | 100000 | data/AUDCAD_D1.csv |
| BTCUSD / ETHUSD | Crypto CFD | 1 / 10 | optional later |

**Lead strategy symbol: `US30.cash`** (spike 001 validated on proxy).

## Yahoo D1 (20y proxies → FTMO-style names)

| File | Rows | Start | End | Proxy for |
|------|------|-------|-----|-----------|
| data/US30_D1.csv | 5031 | 2006-07-25 | 2026-07-24 | FTMO US30 CFD |
| data/US500_D1.csv | 5031 | 2006-07-25 | 2026-07-24 | FTMO US500 |
| data/US100_D1.csv | 5031 | 2006-07-25 | 2026-07-24 | FTMO US100/NAS100 |
| data/GER40_D1.csv | 5075 | 2006-07-24 | 2026-07-24 | GER40 |
| data/UK100_D1.csv | 5053 | 2006-07-24 | 2026-07-24 | UK100 |
| data/JP225_D1.csv | 4891 | 2006-07-24 | 2026-07-23 | JP225 |
| data/XAUUSD_D1.csv | 5032 | 2006-07-24 | 2026-07-24 | XAUUSD (GC=F) |
| data/XAGUSD_D1.csv | 5032 | 2006-07-24 | 2026-07-24 | XAGUSD |
| data/USOIL_D1.csv | 5033 | 2006-07-24 | 2026-07-24 | USOIL |
| data/UKOIL_D1.csv | 4725 | 2007-07-30 | 2026-07-24 | UKOIL |
| data/EURUSD_D1.csv | 5188 | 2006-07-24 | 2026-07-24 | EURUSD |
| data/GBPUSD_D1.csv | 5200 | 2006-07-24 | 2026-07-24 | GBPUSD |
| data/USDJPY_D1.csv | 5188 | 2006-07-24 | 2026-07-24 | USDJPY |
| data/AUDUSD_D1.csv | 5203 | 2006-07-24 | 2026-07-24 | AUDUSD |
| data/USDCAD_D1.csv | 5203 | 2006-07-24 | 2026-07-24 | USDCAD |
| data/AUDCAD_D1.csv | 5208 | 2006-07-24 | 2026-07-24 | AUDCAD |
| data/NZDUSD_D1.csv | 5204 | 2006-07-24 | 2026-07-24 | NZDUSD |

## Dukascopy / prior H1
| File | Notes |
|------|-------|
| data/EURUSD_H1.csv | Dukascopy+Yahoo merge |
| data/GBPUSD_H1.csv | Dukascopy+Yahoo merge |
| data/XAUUSD_H1.csv | Dukascopy 2022-2024 |

## Refresh
```bash
source .venv/bin/activate
python utils/yahoo_fetch.py --interval 1d --period 20y
python utils/dukascopy_fetch.py --symbol EURUSD --start 2022-07-01 --end 2024-07-01
```
