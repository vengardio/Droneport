#ifndef PWM_H
#define PWM_H

#include <stdint.h>

// Инициализация PWM на PA6 (TIM3_CH1)
void PWM_Init(void);

// Установка ширины импульса в микросекундах (для ESC)
// Диапазон: 1000 - 2000 мкс
void PWM_SetPulseWidth(uint16_t microseconds);

// Установка процента заполнения (0-100%)
void PWM_SetDutyPercent(uint8_t percent);

// Включение/выключение PWM сигнала
void PWM_Enable(void);
void PWM_Disable(void);

#endif