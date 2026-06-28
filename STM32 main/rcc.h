#include "stm32f401xc.h"

#ifndef RCC_H
#define RCC_H
#define LOOPS_PER_US  5       // 84 МГц, подобрано экспериментально
#define LOOPS_PER_MS  5000    // LOOPS_PER_US * 1000

int ClockInit(void);
void delayMicroseconds(uint32_t microsec);
void delay(uint32_t ms);
void MicroTimer_Init(void);
uint32_t getMicros(void);

#endif