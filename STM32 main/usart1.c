#include "usart1.h"

void USART1_Init(uint32_t boudrate) {
	RCC->APB2ENR |= RCC_APB2ENR_USART1EN;     // Включение тактирования USART1

	USART1->CR1 &= ~USART_CR1_UE;             //Выключение USART1 перед настройкой

	USART1->CR1 &= ~(USART_CR1_M | USART_CR1_PCE);     //8 бит данных, 1 старт-бит, без четности
  USART1->CR2 &= ~USART_CR2_STOP;                    //1 стоп-бит,
	USART1->BRR = 42000000 / boudrate;                  // APB2 = 42 МГц                          
	USART1->CR1 |= (USART_CR1_RE | USART_CR1_RXNEIE);  //Включаем возможность принятия сообщения и прерывание по принятому сообщению
	USART1->CR1 |= USART_CR1_TE;                       //Включаем возможность отправки сообщения
	
	USART1->CR1 |= USART_CR1_UE;              //Включение USART1 после настройки
	
	NVIC_EnableIRQ(USART1_IRQn);       //Включение прерываний
  NVIC_SetPriority(USART1_IRQn, 1);  // Приоритет прерывания
}

void USART1_SendArray(const uint8_t *data, uint16_t len) {
    if (len == 0) {
        return;  // Защита от некорректных данных
    }
    
    for (uint16_t i = 0; i < len; i++) {
        // Ждём, пока регистр передачи освободится (TXE = 1)
        while (!(USART1->SR & USART_SR_TXE));
        
        // Записываем байт в регистр данных
        USART1->DR = data[i];
    }
    
    // Ждём полного завершения передачи (TC = 1)
    // Это важно для последнего байта, чтобы он успел уйти по линии
    while (!(USART1->SR & USART_SR_TC));
}