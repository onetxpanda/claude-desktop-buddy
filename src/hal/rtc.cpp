#include "rtc.h"
#include <M5Unified.h>

namespace hal { namespace rtc {

void getTime(Time& out) {
  auto dt = M5.Rtc.getDateTime();
  out.h = dt.time.hours;
  out.m = dt.time.minutes;
  out.s = dt.time.seconds;
}

void getDate(Date& out) {
  auto dt = M5.Rtc.getDateTime();
  out.weekday = dt.date.weekDay;
  out.month   = dt.date.month;
  out.day     = dt.date.date;
  out.year    = dt.date.year;
}

void setTime(const Time& in) {
  auto dt = M5.Rtc.getDateTime();
  dt.time.hours   = in.h;
  dt.time.minutes = in.m;
  dt.time.seconds = in.s;
  M5.Rtc.setDateTime(dt);
}

void setDate(const Date& in) {
  auto dt = M5.Rtc.getDateTime();
  dt.date.weekDay = in.weekday;
  dt.date.month   = in.month;
  dt.date.date    = in.day;
  dt.date.year    = in.year;
  M5.Rtc.setDateTime(dt);
}

}}
