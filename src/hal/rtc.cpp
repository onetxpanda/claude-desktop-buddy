#include "rtc.h"
#include <M5StickCPlus.h>

namespace hal { namespace rtc {

void getTime(Time& out) {
  RTC_TimeTypeDef t;
  M5.Rtc.GetTime(&t);
  out.h = t.Hours; out.m = t.Minutes; out.s = t.Seconds;
}

void getDate(Date& out) {
  RTC_DateTypeDef d;
  M5.Rtc.GetDate(&d);
  out.weekday = d.WeekDay;
  out.month   = d.Month;
  out.day     = d.Date;
  out.year    = d.Year;
}

void setTime(const Time& in) {
  RTC_TimeTypeDef t{};
  t.Hours = in.h; t.Minutes = in.m; t.Seconds = in.s;
  M5.Rtc.SetTime(&t);
}

void setDate(const Date& in) {
  RTC_DateTypeDef d{};
  d.WeekDay = in.weekday;
  d.Month   = in.month;
  d.Date    = in.day;
  d.Year    = in.year;
  M5.Rtc.SetDate(&d);
}

}}
