//+------------------------------------------------------------------+
// ExportH1.mq5 — exports H1 OHLCV for EURUSD, GBPUSD, XAUUSD
// Copy to: MT5/MQL5/Scripts/ExportH1.mq5
// Run via: Tools > Scripts > ExportH1
//+------------------------------------------------------------------+
#property script_show_inputs

input int BarsBack = 50000;

void ExportSymbol(string symbol, ENUM_TIMEFRAMES tf, string filename)
{
   MqlRates rates[];
   int count = CopyRates(symbol, tf, 0, BarsBack, rates);
   if(count <= 0) { Print("No data for ", symbol); return; }

   int fh = FileOpen(filename, FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
   if(fh == INVALID_HANDLE) { Print("Cannot open file: ", filename); return; }

   FileWrite(fh, "time","open","high","low","close","tick_volume","spread","real_volume");
   for(int i = 0; i < count; i++)
   {
      FileWrite(fh,
         TimeToString(rates[i].time, TIME_DATE|TIME_SECONDS),
         rates[i].open, rates[i].high, rates[i].low, rates[i].close,
         rates[i].tick_volume, rates[i].spread, rates[i].real_volume);
   }
   FileClose(fh);
   Print("Exported ", count, " bars -> ", filename);
}

void OnStart()
{
   ExportSymbol("EURUSD", PERIOD_H1, "EURUSD_H1.csv");
   ExportSymbol("GBPUSD", PERIOD_H1, "GBPUSD_H1.csv");
   ExportSymbol("XAUUSD", PERIOD_H1, "XAUUSD_H1.csv");
   Print("All done. Files in MT5/MQL5/Files/");
}
