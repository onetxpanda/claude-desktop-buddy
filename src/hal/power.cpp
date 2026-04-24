#include "power.h"
#include <M5StickCPlus.h>

namespace hal { namespace power {

float busVoltage() { return M5.Axp.GetVBusVoltage(); }
float batVoltage() { return M5.Axp.GetBatVoltage(); }
float batCurrent() { return M5.Axp.GetBatCurrent(); }
float axpTemp()    { return M5.Axp.GetTempInAXP192(); }

void setBrightness(uint8_t level) { M5.Axp.ScreenBreath(20 + level * 20); }
void setLcdPower(bool on)         { M5.Axp.SetLDO2(on); }
void powerOff()                   { M5.Axp.PowerOff(); }

}}
