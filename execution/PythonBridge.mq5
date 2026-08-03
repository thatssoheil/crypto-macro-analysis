//+------------------------------------------------------------------+
//|                                                 PythonBridge.mq5 |
//|          Bridge between Linux Python and Wine MT5 for AutoTSMOM  |
//|          V1.09 — SL and TP set via PositionModify               |
//+------------------------------------------------------------------+
#property copyright "Hermes Agent"
#property version   "1.09"

#include <Trade\Trade.mqh>

CTrade trade;
string SYMBOLS[] = {"XAUUSD", "US100.cash", "US500.cash", "USDJPY"};
string STATE_FILE = "mt5_state.csv";
string TARGET_FILE = "mt5_targets.csv";
int MAGIC = 999111;

int tick_counter = 0;

int OnInit()
{
   trade.SetExpertMagicNumber(MAGIC);
   Print("PythonBridge V1.09 INITIALIZED on ", Symbol(), " Magic: ", MAGIC);
   SymbolSelect("EURUSD", true);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   Print("PythonBridge DEINIT");
}

void WriteState()
{
   int fh = FileOpen(STATE_FILE, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE) return;
   
   FileWrite(fh, "Equity", DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   
   for(int i=0; i<ArraySize(SYMBOLS); i++)
   {
      string sym = SYMBOLS[i];
      SymbolSelect(sym, true);
      
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
      double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      
      double current_vol = 0.0;
      for(int p=0; p<PositionsTotal(); p++)
      {
         ulong ticket = PositionGetTicket(p);
         if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == MAGIC)
         {
            double v = PositionGetDouble(POSITION_VOLUME);
            if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL) v = -v;
            current_vol += v; 
         }
      }
      
      FileWrite(fh, sym, ask, bid, contract, step, current_vol);
   }
   FileClose(fh);
}

// Execute one symbol's rebalance. SL and TP parsed from targets CSV.
bool ExecuteSymbol(string sym, double target_lots, double sl_price, double tp_price)
{
   // Get current volume
   double current_vol = 0.0;
   ulong pos_ticket = 0;
   
   for(int p=0; p<PositionsTotal(); p++)
   {
      ulong ticket = PositionGetTicket(p);
      if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == MAGIC)
      {
         pos_ticket = ticket;
         double v = PositionGetDouble(POSITION_VOLUME);
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL) v = -v;
         current_vol += v;
      }
   }
   
   current_vol = NormalizeDouble(current_vol, 2);
   target_lots = NormalizeDouble(target_lots, 2);
   // No change needed — but still update SL/TP if provided
   if(current_vol == target_lots)
   {
      Print(sym, ": no change needed (", current_vol, " == ", target_lots, ")");
      // Update SL/TP on existing position if provided
      if(sl_price > 0 || tp_price > 0)
      {
         if(pos_ticket > 0 && trade.PositionModify(pos_ticket, sl_price, tp_price))
            Print("SL/TP updated: SL=", sl_price, " TP=", tp_price);
         else if(pos_ticket > 0)
            Print("FAIL update SL/TP on ", sym, " ticket=", pos_ticket, ": err=", trade.ResultRetcode());
      }
      return true;
   }
   
   bool all_ok = true;
   
   // Close existing positions for this symbol
   if(current_vol != 0.0)
   {
      for(int p=PositionsTotal()-1; p>=0; p--)
      {
         ulong ticket = PositionGetTicket(p);
         if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == MAGIC)
         {
            if(!trade.PositionClose(ticket))
            {
               Print("FAIL close ", sym, " ticket=", ticket, " err=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
               all_ok = false;
            }
            else
            {
               Print("Closed ", sym, " ticket=", ticket);
            }
         }
      }
   }
   
   // Open new position with SL/TP (set after opening for reliability)
   if(target_lots != 0.0)
   {
      double abs_target = MathAbs(target_lots);
      bool result;
      
      if(target_lots > 0)
         result = trade.Buy(abs_target, sym);
      else
         result = trade.Sell(abs_target, sym);
      
      if(!result || trade.ResultRetcode() != TRADE_RETCODE_DONE)
      {
         Print("FAIL open ", sym, " ", target_lots, " lots, err=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
         all_ok = false;
      }
      else
      {
         string dir = (target_lots > 0) ? "BUY" : "SELL";
         Print("Opened ", dir, " ", sym, " ", abs_target, " lots @ ", trade.ResultPrice());
         
         // Find the position ticket and set SL/TP after opening
         if(sl_price > 0 || tp_price > 0)
         {
            for(int p=0; p<PositionsTotal(); p++)
            {
               ulong t = PositionGetTicket(p);
               if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == MAGIC)
               {
                  if(trade.PositionModify(t, sl_price, tp_price))
                     Print("SL/TP set: ticket=", t, " SL=", sl_price, " TP=", tp_price);
                  else
                     Print("FAIL set SL on ticket ", t, ": err=", trade.ResultRetcode());
                  break;
               }
            }
         }
      }
   }
   
   return all_ok;
}

void ReadTargetsAndExecute()
{
   if(!FileIsExist(TARGET_FILE, FILE_COMMON)) return;

   int fh = FileOpen(TARGET_FILE, FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(fh == INVALID_HANDLE) return; 
   
   string flag = FileReadString(fh);
   if(flag != "EXECUTE") 
   {
      FileClose(fh);
      return;
   }
   
   Print("EXECUTE flag found. Processing targets...");
   
   bool all_trades_ok = true;
   int symbols_processed = 0;
   
   while(!FileIsEnding(fh))
   {
      string sym = FileReadString(fh);
      if(sym == "") break;
      string target_str = FileReadString(fh);
      double target_lots = StringToDouble(target_str);
      
      // Read optional SL price (3rd column)
      double sl_price = 0;
      if(!FileIsEnding(fh))
      {
         string sl_str = FileReadString(fh);
         sl_price = StringToDouble(sl_str);
      }
      
      // Read optional TP price (4th column)
      double tp_price = 0;
      if(!FileIsEnding(fh))
      {
         string tp_str = FileReadString(fh);
         tp_price = StringToDouble(tp_str);
      }
      
      Print("Target: ", sym, " = ", target_lots, " lots  SL=", sl_price, "  TP=", tp_price);
      
      if(!ExecuteSymbol(sym, target_lots, sl_price, tp_price))
         all_trades_ok = false;
      
      symbols_processed++;
   }
   FileClose(fh);
   
   if(all_trades_ok)
   {
      FileDelete(TARGET_FILE, FILE_COMMON);
      Print("All ", symbols_processed, " symbols OK. Target file deleted.");
   }
   else
   {
      Print("WARNING: Some trades failed. Target file RETAINED.");
   }
}

void OnTick()
{
   tick_counter++;
   if(tick_counter >= 30)
   {
      tick_counter = 0;
      WriteState();
      Print("HB: PythonBridge alive, Equity: ", DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2));
   }
   
   ReadTargetsAndExecute();
}
