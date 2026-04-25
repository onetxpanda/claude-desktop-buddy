#pragma once
#include <stdint.h>
#include "../input.h"

namespace screen { namespace reset {
  void     draw();
  uint8_t  selected();
  void     setSelected(uint8_t i);
  uint8_t  itemCount();
  uint8_t  lastConfirmIdx();
  void     setLastConfirm(uint8_t idx, uint32_t deadlineMs);
  uint32_t confirmDeadline();
  bool     handleButton(Btn b, BtnEvent e);
}}
