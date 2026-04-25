#pragma once

// Use Btn/BtnEvent to avoid clashing with the M5StickCPlus Button class.
enum class Btn      { A, B, Power };
enum class BtnEvent { Tap, LongPress, Release };
