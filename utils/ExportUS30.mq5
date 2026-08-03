//+------------------------------------------------------------------+
//| ExportUS30.mq5 — FAST single-symbol bar export                     |
//| Drag onto ANY chart. No multi-symbol loops.                        |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input string InpSymbol = "US30.cash";
input int    InpBars   = 20000;

void Dump(const string sym, ENUM_TIMEFRAMES tf, const string tag)
{
   if(!SymbolSelect(sym, true))
   {
      Print("FAIL SymbolSelect ", sym, " err=", GetLastError());
      return;
   }
   // force history
   datetime from = TimeCurrent() - (datetime)InpBars * PeriodSeconds(tf);
   datetime to   = TimeCurrent();
   int waited = 0;
   while(!SeriesInfoInteger(sym, tf, SERIES_SYNCHRONIZED) && waited < 50)
   {
      Sleep(100);
      waited++;
   }
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int n = CopyRates(sym, tf, 0, InpBars, rates);
   if(n <= 0)
   {
      // retry from range
      n = CopyRates(sym, tf, from, to, rates);
   }
   if(n <= 0)
   {
      Print("FAIL CopyRates ", sym, " ", tag, " err=", GetLastError());
      return;
   }
   string fname = "US30_cash_" + tag + ".csv";
   // prefer Common\\Files
   int fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
      fh = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
   {
      Print("FAIL FileOpen ", fname, " err=", GetLastError());
      return;
   }
   FileWrite(fh, "time", "Open", "High", "Low", "Close", "Volume");
   int dig = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   for(int i = 0; i < n; i++)
   {
      FileWrite(fh,
         TimeToString(rates[i].time, TIME_DATE|TIME_MINUTES),
         DoubleToString(rates[i].open, dig),
         DoubleToString(rates[i].high, dig),
         DoubleToString(rates[i].low, dig),
         DoubleToString(rates[i].close, dig),
         (long)rates[i].tick_volume);
   }
   FileClose(fh);
   Print("OK ", fname, " bars=", n,
         " first=", TimeToString(rates[0].time),
         " last=", TimeToString(rates[n-1].time));
}

void OnStart()
{
   Print("ExportUS30 start ", InpSymbol);
   Dump(InpSymbol, PERIOD_M15, "M15");
   Dump(InpSymbol, PERIOD_H1,  "H1");
   Dump(InpSymbol, PERIOD_D1,  "D1");
   Print("ExportUS30 DONE");
}
