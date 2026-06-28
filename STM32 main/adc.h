#ifndef ADC_H
#define ADC_H

#include <stdint.h>

// Инициализация ADC1 на PA1
void ADC_Init(void);

// Чтение сырого значения ADC (0-4095)
uint16_t ADC_ReadRaw(void);

#endif