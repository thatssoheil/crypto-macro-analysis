//+------------------------------------------------------------------+
//| ExportBars.mq5 — export OHLCV for FTMO symbols                     |
//| Inputs: symbol, timeframe, bars                                    |
//| Out: Common/Files/{symbol}_{TF}.csv                                |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpSymbol   = "US30.cash";
input ENUM_TIMEFRAMES InpTF = PERIOD_H1;
input int    InpBars     = 50000;
input bool   InpAllTF    = true;  // if true: M15,H1,D1 for symbol

string TFStr(ENUM_TIMEFRAMES tf)
{
   if(tf == PERIOD_M5)  return "M5";
   if(tf == PERIOD_M15) return "M15";
   if(tf == PERIOD_M30) return "M30";
   if(tf == PERIOD_H1)  return "H1";
   if(tf == PERIOD_H4)  return "H4";
   if(tf == PERIOD_D1)  return "D1";
   if(tf == PERIOD_W1)  return "W1";
   return IntegerToString((int)tf);
}

string SafeName(string s)
{
   string o = s;
   StringReplace(o, ".", "_");
   return o;
}

int ExportOne(string sym, ENUM_TIMEFRAMES tf, int bars_req)
{
   if(!SymbolSelect(sym, true))
   {
      Print("SymbolSelect failed: ", sym, " err=", GetLastError());
      return 0;
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(sym, tf, 0, bars_req, rates);
   if(copied <= 0)
   {
      Print("CopyRates failed ", sym, " ", TFStr(tf), " err=", GetLastError());
      return 0;
   }

   string fname = SafeName(sym) + "_" + TFStr(tf) + ".csv";
   int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
   {
      fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
      if(fh == INVALID_HANDLE)
      {
         Print("FileOpen fail ", fname, " ", GetLastError());
         return 0;
      }
   }

   FileWrite(fh, "time", "Open", "High", "Low", "Close", "Volume", "spread", "real_volume");
   for(int i = 0; i < copied; i++)
   {
      FileWrite(fh,
         TimeToString(rates[i].time, TIME_DATE|TIME_MINUTES),
         DoubleToString(rates[i].open, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
         DoubleToString(rates[i].high, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
         DoubleToString(rates[i].low, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
         DoubleToString(rates[i].close, (int)SymbolInfoInteger(sym, SYMBOL_DIGITS)),
         (long)rates[i].tick_volume,
         rates[i].spread,
         (long)rates[i].real_volume
      );
   }
   FileClose(fh);
   Print("Wrote ", copied, " bars -> ", fname,
         " first=", TimeToString(rates[0].time),
         " last=", TimeToString(rates[copied-1].time));
   return copied;
}

void OnStart()
{
   string sym = InpSymbol;
   int total = 0;
   if(InpAllTF)
   {
      total += ExportOne(sym, PERIOD_M15, InpBars);
      total += ExportOne(sym, PERIOD_H1,  InpBars);
      total += ExportOne(sym, PERIOD_D1,  MathMin(InpBars, 10000));
   }
   else
      total += ExportOne(sym, InpTF, InpBars);

   // also core set for portfolio path
   string extras[] = {"US500.cash", "US100.cash", "XAUUSD", "EURUSD", "GBPUSD"};
   if(InpAllTF)
   {
      for(int i = 0; i < ArraySize(extras); i++)
      {
         if(extras[i] == sym) continue;
         total += ExportOne(extras[i], PERIOD_H1, InpBars);
         total += ExportOne(extras[i], PERIOD_D1, MathMin(InpBars, 10000));
      }
   }
   Print("ExportBars done total_rows=", total);
}
