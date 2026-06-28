#include "stm32f401xc.h"

// TIM4, APB1 timer clock = 84 MHz
// PSC=41999 -> 84MHz/42000 = 2000 Hz
// ARR=999   -> 2000/1000  = 2 Hz -> прерывание каждые 500 мс -> toggle -> период 1 с
void LedBlink_Init(void) {
    RCC->APB1ENR |= RCC_APB1ENR_TIM4EN;

    TIM4->PSC  = 41999;
    TIM4->ARR  = 250;
    TIM4->DIER |= TIM_DIER_UIE;

    NVIC_SetPriority(TIM4_IRQn, 2);
    NVIC_EnableIRQ(TIM4_IRQn);

    TIM4->CR1 |= TIM_CR1_CEN;
}
