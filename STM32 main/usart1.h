#include "stm32f401xc.h"

#ifndef USART1_H
#define USART1_H

void USART1_Init(uint32_t boudrate);
void USART1_SendArray(const uint8_t *data, uint16_t len);
	
#endif