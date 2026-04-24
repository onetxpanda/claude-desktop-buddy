#pragma once
#include <stdint.h>

namespace hal { namespace rtc {

struct Time { uint8_t h, m, s; };
struct Date { uint8_t weekday, month, day; uint16_t year; };

void getTime(Time& out);
void getDate(Date& out);
void setTime(const Time& in);
void setDate(const Date& in);

}}
