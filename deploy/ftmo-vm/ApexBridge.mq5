//+------------------------------------------------------------------+
//| ApexBridge.mq5 — file-protocol bridge for the Apex V4 engines.   |
//|                                                                  |
//| Telemetry OUT (MQL5/Files/apex/): heartbeat.txt, sym_<S>.txt,    |
//|   bars_<S>_<TF>.csv, positions.txt, deals.txt                    |
//| Commands IN: cmd_*.txt (key=value) -> executes -> res_<id>.txt   |
//| All order execution happens HERE, natively in the terminal —     |
//| no Wine-Python IPC anywhere.                                     |
//+------------------------------------------------------------------+
#property copyright "Apex Algo"
#property version   "1.00"
#property strict

input string InpSymbols   = "BTCUSD,US500"; // comma-separated bridge symbols
input int    InpBars      = 420;            // bars per timeframe file
input int    InpDealsDays = 50;             // deal-history window (days)

string  g_dir = "apex\\";
string  g_syms[];
string  g_tfs[3] = {"H1", "H4", "D1"};
datetime g_last_bar[];
int     g_tick = 0;

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TfEnum(const string t)
  {
   if(t == "M15") return PERIOD_M15;
   if(t == "H1")  return PERIOD_H1;
   if(t == "H4")  return PERIOD_H4;
   return PERIOD_D1;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   int n = StringSplit(InpSymbols, ',', g_syms);
   if(n <= 0) return INIT_PARAMETERS_INCORRECT;
   for(int i = 0; i < n; i++)
     {
      StringTrimLeft(g_syms[i]);
      StringTrimRight(g_syms[i]);
      SymbolSelect(g_syms[i], true);
     }
   ArrayResize(g_last_bar, n * 3);
   ArrayInitialize(g_last_bar, 0);
   FolderCreate("apex");
   DumpAllSymbols();
   EventSetTimer(2);
   Print("ApexBridge online: ", InpSymbols);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void DumpAllSymbols()
  {
   // One-shot inventory of every server symbol — lets the Linux side verify
   // the exact broker naming (US500 vs US500.cash etc.) from facts.
   string body = "";
   int total = SymbolsTotal(false);
   for(int i = 0; i < total; i++)
      body += SymbolName(i, false) + "\n";
   WriteAtomic("symbols_all.txt", body);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
void WriteAtomic(const string name, const string content)
  {
   string tmp = g_dir + name + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   FileWriteString(h, content);
   FileClose(h);
   FileMove(tmp, 0, g_dir + name, FILE_REWRITE);
  }

//+------------------------------------------------------------------+
void WriteHeartbeat()
  {
   string s = StringFormat(
      "ts=%I64d\nconnected=%d\nlogin=%I64d\nserver=%s\ncurrency=%s\nbalance=%.2f\nequity=%.2f\n",
      (long)TimeCurrent(),
      (int)TerminalInfoInteger(TERMINAL_CONNECTED),
      AccountInfoInteger(ACCOUNT_LOGIN),
      AccountInfoString(ACCOUNT_SERVER),
      AccountInfoString(ACCOUNT_CURRENCY),
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY));
   WriteAtomic("heartbeat.txt", s);
  }

//+------------------------------------------------------------------+
void WriteSymbols()
  {
   for(int i = 0; i < ArraySize(g_syms); i++)
     {
      string sym = g_syms[i];
      MqlTick tk;
      if(!SymbolInfoTick(sym, tk)) continue;
      string s = StringFormat(
         "bid=%.8f\nask=%.8f\nts=%I64d\ndigits=%d\npoint=%.8f\ntick_size=%.8f\ntick_value=%.8f\nvol_min=%.4f\nvol_max=%.2f\nvol_step=%.4f\n",
         tk.bid, tk.ask, (long)tk.time,
         (int)SymbolInfoInteger(sym, SYMBOL_DIGITS),
         SymbolInfoDouble(sym, SYMBOL_POINT),
         SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE),
         SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE),
         SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN),
         SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX),
         SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP));
      WriteAtomic("sym_" + sym + ".txt", s);
     }
  }

//+------------------------------------------------------------------+
void WriteBars()
  {
   for(int i = 0; i < ArraySize(g_syms); i++)
      for(int j = 0; j < 3; j++)
        {
         string sym = g_syms[i];
         string tf  = g_tfs[j];
         MqlRates rates[];
         int got = CopyRates(sym, TfEnum(tf), 0, InpBars, rates);
         if(got < 10) continue;
         int slot = i * 3 + j;
         datetime newest = rates[got - 1].time;
         if(newest == g_last_bar[slot] && (g_tick % 30) != 0) continue;
         g_last_bar[slot] = newest;
         string body = "";
         for(int k = 0; k < got; k++)
            body += StringFormat("%I64d,%.8f,%.8f,%.8f,%.8f,%I64d,%I64d\n",
               (long)rates[k].time, rates[k].open, rates[k].high,
               rates[k].low, rates[k].close,
               rates[k].tick_volume, rates[k].real_volume);
         WriteAtomic("bars_" + sym + "_" + tf + ".csv", body);
        }
  }

//+------------------------------------------------------------------+
void WritePositions()
  {
   string body = "";
   for(int i = 0; i < PositionsTotal(); i++)
     {
      string sym = PositionGetSymbol(i);
      if(sym == "") continue;
      body += StringFormat("%I64d;%I64d;%s;%.4f;%.8f;%.8f;%.8f;%d\n",
         PositionGetInteger(POSITION_TICKET),
         PositionGetInteger(POSITION_MAGIC), sym,
         PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_SL),
         PositionGetDouble(POSITION_TP),
         (int)PositionGetInteger(POSITION_TYPE));
     }
   WriteAtomic("positions.txt", body);
  }

//+------------------------------------------------------------------+
void WriteDeals()
  {
   datetime now = TimeCurrent();
   if(!HistorySelect(now - InpDealsDays * 86400, now + 3600)) return;
   string body = "";
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong tk = HistoryDealGetTicket(i);
      if(tk == 0) continue;
      body += StringFormat("%I64d;%I64d;%d;%I64d;%.2f;%.2f;%.2f;%s\n",
         HistoryDealGetInteger(tk, DEAL_POSITION_ID),
         HistoryDealGetInteger(tk, DEAL_MAGIC),
         (int)HistoryDealGetInteger(tk, DEAL_ENTRY),
         HistoryDealGetInteger(tk, DEAL_TIME),
         HistoryDealGetDouble(tk, DEAL_PROFIT),
         HistoryDealGetDouble(tk, DEAL_COMMISSION),
         HistoryDealGetDouble(tk, DEAL_SWAP),
         HistoryDealGetString(tk, DEAL_SYMBOL));
     }
   WriteAtomic("deals.txt", body);
  }

//+------------------------------------------------------------------+
bool SendWithFilling(MqlTradeRequest &req, MqlTradeResult &res)
  {
   ENUM_ORDER_TYPE_FILLING modes[3] = {ORDER_FILLING_IOC, ORDER_FILLING_FOK, ORDER_FILLING_RETURN};
   for(int i = 0; i < 3; i++)
     {
      req.type_filling = modes[i];
      ZeroMemory(res);
      if(OrderSend(req, res) && res.retcode == TRADE_RETCODE_DONE) return true;
      if(res.retcode != TRADE_RETCODE_INVALID_FILL) return false;
     }
   return false;
  }

//+------------------------------------------------------------------+
void ExecCommand(const string fname)
  {
   int h = FileOpen(g_dir + fname, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   string id = "", action = "", symbol = "", comment = "";
   double volume = 0, sl = 0, tp = 0;
   long   position = 0, magic = 0;
   int    deviation = 50;
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      string kv[];
      if(StringSplit(line, '=', kv) < 2) continue;
      if(kv[0] == "id")        id = kv[1];
      else if(kv[0] == "action")    action = kv[1];
      else if(kv[0] == "symbol")    symbol = kv[1];
      else if(kv[0] == "comment")   comment = kv[1];
      else if(kv[0] == "volume")    volume = StringToDouble(kv[1]);
      else if(kv[0] == "sl")        sl = StringToDouble(kv[1]);
      else if(kv[0] == "tp")        tp = StringToDouble(kv[1]);
      else if(kv[0] == "position")  position = StringToInteger(kv[1]);
      else if(kv[0] == "magic")     magic = StringToInteger(kv[1]);
      else if(kv[0] == "deviation") deviation = (int)StringToInteger(kv[1]);
     }
   FileClose(h);
   if(id == "") { FileDelete(g_dir + fname); return; }

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);
   string err = "";

   if(action == "OPEN_BUY")
     {
      req.action   = TRADE_ACTION_DEAL;
      req.symbol   = symbol;
      req.volume   = volume;
      req.type     = ORDER_TYPE_BUY;
      req.price    = SymbolInfoDouble(symbol, SYMBOL_ASK);
      req.sl       = sl;
      req.tp       = tp;
      req.deviation = deviation;
      req.magic    = magic;
      req.comment  = comment;
      req.type_time = ORDER_TIME_GTC;
      if(!SendWithFilling(req, res)) err = "open failed";
     }
   else if(action == "CLOSE")
     {
      if(PositionSelectByTicket((ulong)position))
        {
         req.action   = TRADE_ACTION_DEAL;
         req.position = (ulong)position;
         req.symbol   = PositionGetString(POSITION_SYMBOL);
         req.volume   = (volume > 0) ? volume : PositionGetDouble(POSITION_VOLUME);
         bool isBuy   = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
         req.type     = isBuy ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         req.price    = SymbolInfoDouble(req.symbol, isBuy ? SYMBOL_BID : SYMBOL_ASK);
         req.deviation = deviation;
         req.magic    = PositionGetInteger(POSITION_MAGIC);
         req.comment  = comment;
         if(!SendWithFilling(req, res)) err = "close failed";
        }
      else err = "position not found";
     }
   else if(action == "MODIFY_SL")
     {
      if(PositionSelectByTicket((ulong)position))
        {
         req.action   = TRADE_ACTION_SLTP;
         req.position = (ulong)position;
         req.symbol   = PositionGetString(POSITION_SYMBOL);
         req.sl       = sl;
         req.tp       = (tp > 0) ? tp : PositionGetDouble(POSITION_TP);
         if(!OrderSend(req, res)) err = "modify failed";
        }
      else err = "position not found";
     }
   else err = "unknown action";

   string out = StringFormat("id=%s\nretcode=%d\nprice=%.8f\norder=%I64d\nerror=%s %s\n",
      id, (int)res.retcode, res.price, (long)res.order, err, res.comment);
   WriteAtomic("res_" + id + ".txt", out);
   FileDelete(g_dir + fname);
  }

//+------------------------------------------------------------------+
void ProcessCommands()
  {
   string fname;
   long h = FileFindFirst(g_dir + "cmd_*.txt", fname);
   if(h == INVALID_HANDLE) return;
   string found[];
   int n = 0;
   do
     {
      ArrayResize(found, n + 1);
      found[n++] = fname;
     }
   while(FileFindNext(h, fname));
   FileFindClose(h);
   for(int i = 0; i < n; i++) ExecCommand(found[i]);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   g_tick++;
   WriteHeartbeat();
   WriteSymbols();
   WriteBars();
   WritePositions();
   if(g_tick == 1 || (g_tick % 30) == 0) WriteDeals();
   ProcessCommands();
  }
//+------------------------------------------------------------------+
