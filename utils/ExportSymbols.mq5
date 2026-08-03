//+------------------------------------------------------------------+
//| ExportSymbols.mq5 — dump all FTMO symbols to CSV                   |
//| Run: Navigator > Scripts > ExportSymbols                           |
//| Out:  MQL5/Files/ftmo_symbols.csv                                  |
//+------------------------------------------------------------------+
#property script_show_inputs

void OnStart()
{
   int total = SymbolsTotal(false);
   int fh = FileOpen("ftmo_symbols.csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE)
   {
      fh = FileOpen("ftmo_symbols.csv", FILE_WRITE|FILE_CSV|FILE_ANSI, ',');
      if(fh == INVALID_HANDLE)
      {
         Print("Cannot open file: ", GetLastError());
         return;
      }
   }

   FileWrite(fh, "name", "path", "trade_mode", "digits", "point",
             "spread", "contract_size", "currency_base", "currency_profit", "description");

   int written = 0;
   for(int i = 0; i < total; i++)
   {
      string s = SymbolName(i, false);
      if(s == "") continue;
      SymbolSelect(s, true);

      FileWrite(fh,
         s,
         SymbolInfoString(s, SYMBOL_PATH),
         (int)SymbolInfoInteger(s, SYMBOL_TRADE_MODE),
         (int)SymbolInfoInteger(s, SYMBOL_DIGITS),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_POINT), 8),
         (int)SymbolInfoInteger(s, SYMBOL_SPREAD),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE), 2),
         SymbolInfoString(s, SYMBOL_CURRENCY_BASE),
         SymbolInfoString(s, SYMBOL_CURRENCY_PROFIT),
         SymbolInfoString(s, SYMBOL_DESCRIPTION)
      );
      written++;
   }
   FileClose(fh);
   Print("Exported ", written, " / ", total, " symbols -> ftmo_symbols.csv");
}
