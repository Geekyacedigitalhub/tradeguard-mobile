#property strict
#property version   "0.1.0"
#property description "TradeGuard cloud execution bridge. Runs inside MT5; no Python/Windows bridge required."
#property description "Add the TradeGuard API URL to Tools > Options > Expert Advisors > Allow WebRequest."

#include <Trade\\Trade.mqh>

input string ApiBaseUrl = "https://YOUR-TRADEGUARD-API";
input string UserId = "";
input string BridgeSecret = "";\ninput string BridgeId = "cloud-mt5-ea";
input int    PollSeconds = 5;
input int    LiveTickSeconds = 1;
input string LiveSymbols = "EURUSD,GBPUSD,USDJPY,XAUUSD";
input ulong  MagicNumber = 26071001;
input int    DeviationPoints = 20;

CTrade Trade;

string Trim(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

string Url(const string path)
{
   string base = ApiBaseUrl;
   StringTrimRight(base);
   if(StringSubstr(base, StringLen(base)-1, 1) == "/")
      base = StringSubstr(base, 0, StringLen(base)-1);
   return base + path;
}

string JsonString(const string json, const string key)
{
   string needle = "\"" + key + "\"";
   int p = StringFind(json, needle);
   if(p < 0) return "";
   p = StringFind(json, ":", p + StringLen(needle));
   if(p < 0) return "";
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t'))
      p++;
   if(p >= StringLen(json) || StringGetCharacter(json,p) != '"') return "";
   p++;
   int start = p;
   while(p < StringLen(json))
   {
      if(StringGetCharacter(json,p)=='"' && (p==start || StringGetCharacter(json,p-1)!='\\'))
         return StringSubstr(json,start,p-start);
      p++;
   }
   return "";
}

double JsonNumber(const string json, const string key, const double fallback=0.0)
{
   string needle = "\"" + key + "\"";
   int p = StringFind(json, needle);
   if(p < 0) return fallback;
   p = StringFind(json, ":", p + StringLen(needle));
   if(p < 0) return fallback;
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json,p)==' ' || StringGetCharacter(json,p)=='\t'))
      p++;
   int start = p;
   while(p < StringLen(json))
   {
      ushort c = StringGetCharacter(json,p);
      if(c==',' || c=='}' || c==']' || c==' ' || c=='\r' || c=='\n')
         break;
      p++;
   }
   string raw = StringSubstr(json,start,p-start);
   if(raw=="null" || raw=="") return fallback;
   return StringToDouble(raw);
}

long JsonLong(const string json, const string key, const long fallback=0)
{
   return (long)JsonNumber(json,key,(double)fallback);
}

string JsonEscape(string value)
{
   StringReplace(value,"\\","\\\\");
   StringReplace(value,"\"","\\\"");
   StringReplace(value,"\r","\\r");
   StringReplace(value,"\n","\\n");
   return value;
}

string Header()
{
   return "Content-Type: application/json\\r\\nX-Bridge-Secret: " + BridgeSecret + "\\r\\nX-Bridge-User: " + UserId + "\\r\\nX-Bridge-Id: " + BridgeId + "\\r\\n";
}

bool HttpRequest(const string method,const string path,const string body,string &response,int &status)
{
   char data[];
   char result[];
   string result_headers;
   if(body != "")
   {
      int size = StringToCharArray(body,data,0,-1,CP_UTF8);
      if(size > 0) ArrayResize(data,size-1);
   }
   else
      ArrayResize(data,0);

   ResetLastError();
   status = WebRequest(method,Url(path),Header(),10000,data,ArraySize(data),result,result_headers);
   if(status < 0)
   {
      PrintFormat("TradeGuard WebRequest failed path=%s error=%d",path,GetLastError());
      response="";
      return false;
   }

   response = CharArrayToString(result,0,-1,CP_UTF8);
   if(status < 200 || status >= 300)
   {
      PrintFormat("TradeGuard HTTP %d path=%s response=%s",status,path,StringSubstr(response,0,500));
      return false;
   }
   return true;
}

string PositionsJson()
{
   string json="[";
   bool first=true;

   for(int i=0;i<PositionsTotal();i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;

      if(!first) json+=",";
      first=false;

      long type=PositionGetInteger(POSITION_TYPE);
      string side=(type==POSITION_TYPE_BUY ? "BUY" : "SELL");

      json+="{";
      json+="\"ticket\":"+IntegerToString((long)ticket)+",";
      json+="\"symbol\":\"" + JsonEscape(PositionGetString(POSITION_SYMBOL)) + "\",";
      json+="\"side\":\"" + side + "\",";
      json+="\"volume\":"+DoubleToString(PositionGetDouble(POSITION_VOLUME),8)+",";
      json+="\"price_open\":"+DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN),10)+",";
      json+="\"price_current\":"+DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT),10)+",";
      json+="\"stop_loss\":"+DoubleToString(PositionGetDouble(POSITION_SL),10)+",";
      json+="\"take_profit\":"+DoubleToString(PositionGetDouble(POSITION_TP),10)+",";
      json+="\"profit\":"+DoubleToString(PositionGetDouble(POSITION_PROFIT),2);
      json+="}";
   }

   json+="]";
   return json;
}

bool Heartbeat()
{
   string body="{";
   body+="\"user_id\":\"" + JsonEscape(UserId) + "\",";
   body+="\"account\":\"" + IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN)) + "\",";
   body+="\"environment\":\"demo\",";
   body+="\"terminal\":\"MT5 Cloud EA\",";
   body+="\"connected\":true,";
   body+="\"balance\":"+DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2)+",";
   body+="\"equity\":"+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2)+",";
   body+="\"today_pl\":0,";
   body+="\"positions\":"+PositionsJson();
   body+="}";

   string response;
   int status;
   return HttpRequest("POST","/v1/bridge/heartbeat",body,response,status);
}

bool PublishTicks()
{
   string body="{\"user_id\":\"" + JsonEscape(UserId) + "\",\"ticks\":[";
   bool first=true;
   string symbols[];
   int count=StringSplit(LiveSymbols,',',symbols);
   for(int i=0;i<count;i++)
   {
      string requested=Trim(symbols[i]);
      if(requested=="") continue;
      string symbol=ResolveSymbol(requested);
      if(symbol=="") continue;

      MqlTick tick;
      if(!SymbolInfoTick(symbol,tick)) continue;

      if(!first) body+=",";
      first=false;
      double price=(tick.last>0 ? tick.last : (tick.bid+tick.ask)/2.0);
      body+="{\"symbol\":\"" + JsonEscape(symbol) + "\",";
      body+="\"bid\":"+DoubleToString(tick.bid,10)+",";
      body+="\"ask\":"+DoubleToString(tick.ask,10)+",";
      body+="\"price\":"+DoubleToString(price,10)+",";
      body+="\"time\":"+IntegerToString((long)tick.time)+",";
      body+="\"time_msc\":"+IntegerToString((long)tick.time_msc)+"}";
   }
   body+="]}";

   string response;
   int status;
   return HttpRequest("POST","/v1/internal/live-ticks",body,response,status);
}

string ResolveSymbol(string requested)
{
   requested=Trim(requested);
   if(requested=="") return "";

   if(SymbolSelect(requested,true))
      return requested;

   string candidates[];
   int count=StringSplit(requested,StringGetCharacter(",",0),candidates);
   if(count>0)
   {
      for(int i=0;i<count;i++)
      {
         string candidate=Trim(candidates[i]);
         if(candidate!="" && SymbolSelect(candidate,true))
            return candidate;
      }
   }

   string aliases[];
   ArrayResize(aliases,8);
   aliases[0]=requested+"m";
   aliases[1]=requested+".m";
   aliases[2]=requested+".a";
   aliases[3]=requested+"-ECN";
   aliases[4]=requested+"_i";
   aliases[5]=requested+"pro";
   aliases[6]=requested+".pro";
   aliases[7]=requested+"USD";

   for(int i=0;i<ArraySize(aliases);i++)
      if(SymbolSelect(aliases[i],true))
         return aliases[i];

   return "";
}

double NormalizeVolume(const string symbol,double volume)
{
   double minv=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
   double maxv=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   if(minv<=0 || maxv<=0 || step<=0) return 0;

   volume=MathMax(minv,MathMin(maxv,volume));
   volume=MathFloor(volume/step+1e-9)*step;

   int digits=0;
   double s=step;
   while(digits<8 && MathAbs(s-MathRound(s))>1e-9)
   {
      s*=10.0;
      digits++;
   }
   return NormalizeDouble(volume,digits);
}

bool ProtectionValid(const string symbol,const string side,double sl,double tp,string &reason)
{
   if(sl<=0 || tp<=0)
   {
      reason="Both stop_loss and take_profit are required. Refusing unprotected execution.";
      return false;
   }

   MqlTick tick;
   if(!SymbolInfoTick(symbol,tick))
   {
      reason="No current tick for "+symbol;
      return false;
   }

   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   long stops=(long)SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double minDistance=stops*point;

   if(side=="BUY")
   {
      if(sl>=tick.bid || tp<=tick.ask)
      {
         reason="BUY protection is on the wrong side of market.";
         return false;
      }
      if(minDistance>0 && (tick.bid-sl)<minDistance)
      {
         reason="BUY stop_loss violates broker stop distance.";
         return false;
      }
      if(minDistance>0 && (tp-tick.ask)<minDistance)
      {
         reason="BUY take_profit violates broker stop distance.";
         return false;
      }
   }
   else if(side=="SELL")
   {
      if(sl<=tick.ask || tp>=tick.bid)
      {
         reason="SELL protection is on the wrong side of market.";
         return false;
      }
      if(minDistance>0 && (sl-tick.ask)<minDistance)
      {
         reason="SELL stop_loss violates broker stop distance.";
         return false;
      }
      if(minDistance>0 && (tick.bid-tp)<minDistance)
      {
         reason="SELL take_profit violates broker stop distance.";
         return false;
      }
   }
   else
   {
      reason="Unsupported trade side.";
      return false;
   }

   return true;
}

bool FindPositionTicket(const string symbol,ulong &ticket)
{
   ticket=0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong t=PositionGetTicket(i);
      if(t==0 || !PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL)==symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==MagicNumber)
      {
         ticket=t;
         return true;
      }
   }
   return false;
}

string OpenMarket(const string symbol,string side,double volume,double sl,double tp,string &error)
{
   error="";
   string resolved=ResolveSymbol(symbol);
   if(resolved=="")
   {
      error="Symbol unavailable: "+symbol;
      return "";
   }

   if(!ProtectionValid(resolved,side,sl,tp,error))
      return "";

   volume=NormalizeVolume(resolved,volume);
   if(volume<=0)
   {
      error="Invalid volume for "+resolved;
      return "";
   }

   Trade.SetExpertMagicNumber(MagicNumber);
   Trade.SetDeviationInPoints(DeviationPoints);
   if(!Trade.SetTypeFillingBySymbol(resolved))
   {
      error="Could not determine broker filling mode for "+resolved;
      return "";
   }

   bool sent=false;
   if(side=="BUY")
      sent=Trade.Buy(volume,resolved,0.0,sl,tp,"TradeGuard");
   else if(side=="SELL")
      sent=Trade.Sell(volume,resolved,0.0,sl,tp,"TradeGuard");
   else
   {
      error="Unsupported side: "+side;
      return "";
   }

   if(!sent || (Trade.ResultRetcode()!=TRADE_RETCODE_DONE &&
                 Trade.ResultRetcode()!=TRADE_RETCODE_PLACED &&
                 Trade.ResultRetcode()!=TRADE_RETCODE_DONE_PARTIAL))
   {
      error=Trade.ResultRetcodeDescription();
      return "";
   }

   ulong ticket=0;
   FindPositionTicket(resolved,ticket);
   double price=Trade.ResultPrice();

   string result="{";
   result+="\"ticket\":"+IntegerToString((long)ticket)+",";
   result+="\"deal\":"+IntegerToString((long)Trade.ResultDeal())+",";
   result+="\"order\":"+IntegerToString((long)Trade.ResultOrder())+",";
   result+="\"price\":"+DoubleToString(price,10)+",";
   result+="\"stop_loss\":"+DoubleToString(sl,10)+",";
   result+="\"take_profit\":"+DoubleToString(tp,10)+",";
   result+="\"symbol\":\"" + JsonEscape(resolved) + "\"";
   result+="}";
   return result;
}

string ClosePosition(const ulong ticket,string &error)
{
   error="";
   if(ticket==0 || !PositionSelectByTicket(ticket))
   {
      error="Position not found: "+IntegerToString((long)ticket);
      return "";
   }

   Trade.SetExpertMagicNumber(MagicNumber);
   Trade.SetDeviationInPoints(DeviationPoints);

   if(!Trade.PositionClose(ticket,DeviationPoints))
   {
      error=Trade.ResultRetcodeDescription();
      return "";
   }

   if(Trade.ResultRetcode()!=TRADE_RETCODE_DONE &&
      Trade.ResultRetcode()!=TRADE_RETCODE_DONE_PARTIAL)
   {
      error=Trade.ResultRetcodeDescription();
      return "";
   }

   string result="{";
   result+="\"ticket\":"+IntegerToString((long)ticket)+",";
   result+="\"price\":"+DoubleToString(Trade.ResultPrice(),10);
   result+="}";
   return result;
}

void SendCommandResult(const long commandId,const string status,const string resultJson)
{
   string body="{";
   body+="\"command_id\":"+IntegerToString(commandId)+",";
   body+="\"status\":\"" + status + "\",";
   body+="\"result\":" + (resultJson=="" ? "{}" : resultJson);
   body+="}";

   string response;
   int httpStatus;
   HttpRequest("POST","/v1/bridge/commands/result",body,response,httpStatus);
}

void PollCommands()
{
   string response;
   int status;
   string path="/v1/bridge/commands?limit=1";

   if(!HttpRequest("GET",path,"",response,status))
      return;

   int commandsPos=StringFind(response,"\"commands\"");
   if(commandsPos<0) return;

   int arrayStart=StringFind(response,"[",commandsPos);
   int arrayEnd=StringFind(response,"]",arrayStart);
   if(arrayStart<0 || arrayEnd<0 || arrayEnd<=arrayStart+1)
      return;

   string command=StringSubstr(response,arrayStart+1,arrayEnd-arrayStart-1);
   long commandId=JsonLong(command,"id",0);
   string type=JsonString(command,"type");
   if(commandId<=0 || type=="")
      return;

   string payload=command;
   int payloadPos=StringFind(command,"\"payload\"");
   if(payloadPos>=0)
   {
      int brace=StringFind(command,"{",payloadPos);
      int end=StringFind(command,"}",brace);
      if(brace>=0 && end>brace)
         payload=StringSubstr(command,brace,end-brace+1);
   }

   string error="";
   string result="";

   if(type=="open_market")
   {
      string symbol=JsonString(payload,"symbol");
      string side=JsonString(payload,"side");
      double volume=JsonNumber(payload,"volume",0);
      double sl=JsonNumber(payload,"stop_loss",0);
      double tp=JsonNumber(payload,"take_profit",0);

      result=OpenMarket(symbol,side,volume,sl,tp,error);
   }
   else if(type=="close_position")
   {
      ulong ticket=(ulong)JsonLong(payload,"ticket",0);
      result=ClosePosition(ticket,error);
   }
   else if(type=="switch_account")
   {
      error="Account switching is intentionally disabled in EA v0.1. Use the MT5 account configured on this cloud terminal.";
   }
   else
   {
      error="Unsupported command: "+type;
   }

   if(result!="")
      SendCommandResult(commandId,"completed",result);
   else
   {
      string failure="{\"error\":\"" + JsonEscape(error=="" ? "Execution failed" : error) + "\"}";
      SendCommandResult(commandId,"failed",failure);
   }
}

void OnTimer()
{
   static ulong lastTickPushMs=0;
   if(UserId=="" || BridgeSecret=="" || StringFind(ApiBaseUrl,"YOUR-TRADEGUARD-API")>=0)
   {
      Print("TradeGuard EA is not configured. Set ApiBaseUrl, UserId and BridgeSecret.");
      return;
   }

   Heartbeat();
   ulong nowMs=GetTickCount64();
   if(lastTickPushMs==0 || nowMs-lastTickPushMs >= (ulong)MathMax(1,LiveTickSeconds)*1000)
   {
      PublishTicks();
      lastTickPushMs=nowMs;
   }
   PollCommands();
}

int OnInit()
{
   if(PollSeconds<2) PollSeconds=2;

   Trade.SetExpertMagicNumber(MagicNumber);
   Trade.SetDeviationInPoints(DeviationPoints);

   EventSetTimer(PollSeconds);
   Print("TradeGuard cloud EA initialized. Demo execution only.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   PrintFormat("TradeGuard cloud EA stopped. reason=%d",reason);
}
